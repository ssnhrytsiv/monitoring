from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Callable, Optional, Dict, Any
from difflib import SequenceMatcher
import json

from sqlalchemy import update

from telethon import events
from telethon.tl.types import Message

from app.logging_json import get_logger
from app.DAL import watch_posts_operations as watch_posts_db
from app.DAL import watch_events_operations as watch_events_db
from app.DAL import watch_processing_operations as watch_proc_db
from app.DAL import watch_candidates_operations as watch_candidates_db
from app.DAL import session_scope
from app.services.html_match import exact_html_equal
from app.services.html_render import render_html
from app.services.account_pool import iter_pool_clients, session_name
from app.utils.time_utils import MOSCOW_TIME_FORMAT, moscow_now
from app.utils.link_parser import extract_links_from_html
from app.db import models as m
from app import config
from app.utils.html_normalize import (
    normalize_html_full,
    normalize_html_for_edit,
    strip_tags_to_text,
    strip_simple_tags,
    normalize_html_links,
)

try:
    from app.DAL.post_templates_operations import list_templates_full
except Exception:
    list_templates_full = None  # type: ignore

SHEETS_OK = False
try:
    from app.sheet_bot.services import gsheets_buffer

    SHEETS_OK = True
except Exception:
    gsheets_buffer = None  # type: ignore

log = get_logger("plugin.posts_watch_listener")
_pylog = logging.getLogger("plugin.posts_watch_listener")

COVERAGE_POLL_TICK_SEC = 30

_GLOBAL_DELETED_SEEN: Dict[int, float] = {}
GLOBAL_DELETED_TTL = 180.0
_GLOBAL_CANDIDATE_SEEN: Dict[tuple[int, int], float] = {}
CANDIDATE_SEEN_TTL = 24 * 60 * 60  # 1 доба
CANDIDATE_SIM_THRESHOLD = 0.70
# Якщо текстові кандидат-пости схожі >= 0.99, вважаємо їх одним і тим самим кандидатам (не дублюємо).
NEAR_IDENTICAL_TEXT_THRESHOLD = 0.99
GROUP_NEAR_IDENTICAL_THRESHOLD = 0.95
# Редагування: дрібні відмінності не вважаємо суттєвими, якщо ratio майже 1.0
EDIT_NEAR_THRESHOLD = 0.99


def _short_diff(a: str | None, b: str | None, context: int = 40) -> str:
    """
    Повертає короткий опис першої відмінності між рядками (для дебагу).
    """
    if not a or not b:
        return "one is empty"
    sm = SequenceMatcher(None, a, b)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        return f"{tag}: exp[{i1}:{i2}]=`{a[i1:i2][:context]}` vs msg[{j1}:{j2}]=`{b[j1:j2][:context]}`"
    return "equal"


def _now_monotonic() -> float:
    return asyncio.get_event_loop().time()


def _human(dt: datetime) -> str:
    return dt.strftime(MOSCOW_TIME_FORMAT)


def _read_default_coverage_hours() -> float:
    m = os.getenv("WATCH_COVERAGE_MINUTES")
    if m:
        try:
            return float(m) / 60.0
        except Exception:
            pass
    h = os.getenv("WATCH_COVERAGE_HOURS", "24")
    try:
        return float(h)
    except Exception:
        return 24


DEFAULT_COVERAGE_HOURS: float = _read_default_coverage_hours()


def _calc_coverage_at(hours_after: float | None = None) -> Optional[str]:
    if not config.WATCH_VIEWS_ENABLED:
        return None
    hrs = hours_after if hours_after is not None else DEFAULT_COVERAGE_HOURS
    now_msq = moscow_now()
    return _human(now_msq + timedelta(hours=hrs))


def _render_message_html(msg: Message) -> str:
    """
    Єдиний спосіб побудови HTML з повідомлення: через наш render_html з app.services.html_render.
    Якщо щось пішло не так, повертаємо екранований plain-text.
    """
    try:
        return render_html(msg)
    except Exception:
        txt = getattr(msg, "message", "") or ""
        return txt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_HTML_RENDER: Callable[[Message], str] = _render_message_html
_HTML_RENDER_SRC = "app.services.html_render.render_html"


def _db_get_watch_core(wid: int) -> Optional[Dict[str, Any]]:
    try:
        info = watch_posts_db.get_watch_post_details_by_id(wid)
        if not info:
            return None
        expected_raw = info.expected_text_hash or ""
        expected_norm = normalize_html_full(expected_raw) if expected_raw else ""
        if info.channel_id is None:
            return None
        return {
            "channel_id": int(info.channel_id),
            "template_id": int(info.template_id) if info.template_id is not None else None,
            "expected_text_hash": expected_norm,
            "expected_links_json": info.expected_links_json,
            "time_window_start": info.time_window_start,
            "time_window_end": info.time_window_end,
        }
    except Exception:
        _pylog.exception("_db_get_watch_core failed (wid=%s)", wid)
    return None


# --- HTML normalization ------------------------------------------------------


def _strip_simple_tags(html_fragment: str) -> str:
    return strip_simple_tags(html_fragment)

def _normalize_html_full(html_text: str) -> str:
    return normalize_html_full(html_text)


def _normalize_html_for_edit(html_text: str) -> str:
    return normalize_html_for_edit(html_text)


def _strip_tags_to_text(html_text: str) -> str:
    return strip_tags_to_text(html_text)


def _normalize_html_links(html: str) -> str:
    return normalize_html_links(html)


# --- Workers -----------------------------------------------------------------


async def _views_worker():
    if not config.WATCH_VIEWS_ENABLED:
        log.info("posts_watch_listener: views disabled")
        return

    log.info("posts_watch_listener: views worker started (tick=%ss)", COVERAGE_POLL_TICK_SEC)
    while True:
        try:
            slots = iter_pool_clients()
            if not slots:
                await asyncio.sleep(COVERAGE_POLL_TICK_SEC)
                continue
            pool_map = {session_name(s.client): s.client for s in slots}
            any_cli = next(iter(pool_map.values()))

            due = watch_proc_db.list_due_coverage_db()
            for watch_id, channel_id, msg_id, matched_session in due:
                cli = pool_map.get(matched_session) if matched_session else None
                if cli is None:
                    cli = any_cli
                msg: Message | None = None
                try:
                    msg = await cli.get_messages(entity=channel_id, ids=msg_id)
                except Exception as e:
                    _pylog.exception("views: get_messages failed (wid=%s cid=%s mid=%s): %s", watch_id, channel_id,
                                     msg_id, e)
                    # Спроба підвантажити entity через source_url (username/інвайт)
                    fallback_url: str | None = None
                    try:
                        details = watch_posts_db.get_watch_post_details_by_id(watch_id)
                        fallback_url = details.source_url if details else None
                    except Exception:
                        _pylog.exception("views: get_watch_source_url failed (wid=%s)", watch_id)

                    if fallback_url:
                        try:
                            ent = await cli.get_entity(fallback_url)
                            msg = await cli.get_messages(entity=ent, ids=msg_id)
                            _pylog.info(
                                "views: resolved entity via source_url (wid=%s cid=%s url=%s)",
                                watch_id,
                                channel_id,
                                fallback_url,
                            )
                        except Exception as e2:
                            _pylog.exception(
                                "views: fallback get_messages failed (wid=%s cid=%s url=%s): %s",
                                watch_id,
                                channel_id,
                                fallback_url,
                                e2,
                            )

                    # якщо не змогли отримати entity — вважаємо покритим, щоб не зациклитись
                    if msg is None:
                        try:
                            watch_proc_db.mark_done_views_db(watch_id, 0)
                            watch_events_db.insert_watch_event(
                                watch_id,
                                "views",
                                json.dumps(
                                    {
                                        "watch_id": watch_id,
                                        "channel_id": channel_id,
                                        "message_id": msg_id,
                                        "views": 0,
                                        "status": "entity_miss",
                                    }
                                ),
                            )
                        except Exception:
                            _pylog.exception("views: mark_done_views failed (wid=%s) after entity miss", watch_id)
                        msg = None

                if msg is None:
                    continue

                views = int(getattr(msg, "views", 0) or 0)
                try:
                    watch_proc_db.mark_done_views_db(watch_id, views)
                    watch_events_db.insert_watch_event(
                        watch_id,
                        "views",
                        json.dumps(
                            {
                                "watch_id": watch_id,
                                "channel_id": channel_id,
                                "message_id": msg_id,
                                "views": views,
                            }
                        ),
                    )
                    log.info("views: wid=%s views=%s -> done", watch_id, views)
                except Exception:
                    _pylog.exception("views: mark_done_views failed (wid=%s)", watch_id)

                if SHEETS_OK and gsheets_buffer:
                    try:
                        gsheets_buffer.record_views(watch_id, views)
                    except Exception:
                        _pylog.exception("gsheets_buffer.record_views failed (wid=%s)", watch_id)

        except asyncio.CancelledError:
            log.warning("views worker cancelled")
            break
        except Exception:
            _pylog.exception("views tick failed")

        await asyncio.sleep(COVERAGE_POLL_TICK_SEC)


async def _pending_expire_worker():
    log.info("posts_watch_listener: pending-expire worker started (tick=%ss)", COVERAGE_POLL_TICK_SEC)
    while True:
        try:
            with session_scope() as db:
                due_ids = watch_proc_db.list_due_pending_expire_db(db)
            for wid in due_ids:
                try:
                    with session_scope() as db:
                        watch_proc_db.mark_expired_db(db, wid)
                        watch_events_db.insert_watch_event(
                            db,
                            wid,
                            "expired",
                            json.dumps({"watch_id": wid}),
                        )
                        log.info("expire: wid=%s -> expired", wid)
                except Exception:
                    _pylog.exception("expire: mark_expired failed (wid=%s)", wid)

                if SHEETS_OK and gsheets_buffer:
                    try:
                        gsheets_buffer.record_expired(wid)
                    except Exception:
                        _pylog.exception("gsheets_buffer.record_expired failed (wid=%s)", wid)

        except asyncio.CancelledError:
            log.warning("pending-expire worker cancelled")
            break
        except Exception:
            _pylog.exception("pending-expire tick failed")

        await asyncio.sleep(COVERAGE_POLL_TICK_SEC)


def _mark_done_edited_other(wid: int) -> str:
    now_str = _human(moscow_now())
    try:
        with session_scope() as db:
            db.execute(
                update(m.WatchPost)
                .where(
                    m.WatchPost.id == int(wid),
                    m.WatchPost.status.in_(["matched", "done", "edited"]),
                )
                .values(status="edited", updated_at=now_str)
            )
    except Exception:
        _pylog.exception("mark edited-other failed (wid=%s)", wid)
    return now_str


# --- Telethon listeners ------------------------------------------------------


def _attach_listener_for_client(tag: str, cli) -> None:
    @cli.on(events.NewMessage())
    async def _on_new_message(ev: events.NewMessage.Event):
        m: Message = ev.message
        #_pylog.info(m)
        cid = None
        try:
            if hasattr(m, "peer_id") and getattr(m.peer_id, "channel_id", None) is not None:
                cid = int(m.peer_id.channel_id)
            elif getattr(m, "chat_id", None) is not None:
                cid = int(m.chat_id)
        except Exception as e:
            _pylog.info(f"Exception: {m.message}{e}")
            cid = None

        if not cid or cid <= 0:
            return

        mid = int(getattr(m, "id", 0) or 0)

        #_pylog.info("listen: NEW_MESSAGE cid=%s mid=%s session=%s", cid, mid, tag)

        try:
            pending = watch_proc_db.get_pending_by_channel_db(cid)
        except Exception:
            _pylog.exception("listen: get_pending_by_channel failed (cid=%s)", cid)
            return

        if not pending:
            return

        _pylog.info("listen: found %s pending watches for cid=%s mid=%s sess=%s", len(pending), cid, mid, tag)

        try:
            msg_html = _HTML_RENDER(m)
        except Exception:
            _pylog.exception("listen: HTML render failed (cid=%s mid=%s)", cid, mid)
            msg_html = (getattr(m, "message", "") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        for row in pending:
            wid = int(row["id"])
            expected_html = row.get("expected_text_hash")
            expected_links_json = row.get("expected_links_json")
            if not expected_html:
                _pylog.warning("listen: wid=%s cid=%s mid=%s has no expected_html, skip", wid, cid, mid)
                continue
            _pylog.debug(
                "listen: match_start wid=%s cid=%s mid=%s exp_len=%s links=%s tw=(%s,%s)",
                wid,
                cid,
                mid,
                len(expected_html or ""),
                expected_links_json,
                row.get("time_window_start"),
                row.get("time_window_end"),
            )
            msg_html_norm = msg_html
            expected_html_norm = expected_html
            ratio = 0.0
            ratio_text = 0.0

            try:
                # Використовуємо той самий нормалізатор, що й при записі шаблону,
                # щоб HTML-представлення були ідентичними на етапі match.
                msg_html_norm = _normalize_html_full(msg_html)
                expected_html_norm = _normalize_html_full(expected_html)
                ok = exact_html_equal(msg_html_norm, expected_html_norm)
            except Exception:
                _pylog.exception("listen: exact_html_equal failed (wid=%s cid=%s mid=%s)", wid, cid, mid)
                ok = False
            if ok:
                _pylog.info(
                    "listen: exact_match wid=%s cid=%s mid=%s sess=%s exp_len=%s msg_len=%s",
                    wid,
                    cid,
                    mid,
                    tag,
                    len(expected_html_norm or ""),
                    len(msg_html_norm or ""),
                )
            _pylog.debug(
                "similar_check: wid=%s cid=%s mid=%s ok=%s exp_len=%s msg_len=%s",
                wid,
                cid,
                mid,
                ok,
                len(expected_html_norm or ""),
                len(msg_html_norm or ""),
            )

            if not ok:
                try:
                    exp_links_dbg = extract_links_from_html(expected_html_norm)
                except Exception:
                    exp_links_dbg = []
                try:
                    msg_links_dbg = extract_links_from_html(msg_html_norm)
                except Exception:
                    msg_links_dbg = []
                try:
                    msg_plain = _strip_tags_to_text(msg_html_norm)
                    expected_plain = _strip_tags_to_text(expected_html_norm)
                except Exception:
                    msg_plain = msg_html_norm
                    expected_plain = expected_html_norm
                _pylog.debug(
                    "listen: no_exact wid=%s cid=%s mid=%s exp_links=%s msg_links=%s "
                    "exp_snip=%r msg_snip=%r plain_exp_snip=%r plain_msg_snip=%r",
                    wid,
                    cid,
                    mid,
                    exp_links_dbg,
                    msg_links_dbg,
                    (expected_html_norm or "")[:120],
                    (msg_html_norm or "")[:120],
                    (expected_plain or "")[:120],
                    (msg_plain or "")[:120],
                )
                # Фаззі-перевірка схожості (якщо дуже схоже, додаємо в кандидати)
                try:
                    ratio = SequenceMatcher(None, msg_html_norm, expected_html_norm).ratio()
                except Exception:
                    ratio = 0.0
                ratio_text = 0.0
                try:
                    msg_plain = _strip_tags_to_text(msg_html_norm)
                    expected_plain = _strip_tags_to_text(expected_html_norm)
                    ratio_text = SequenceMatcher(None, msg_plain, expected_plain).ratio()
                    # якщо plain-текст повністю збігається — вважаємо схожість ідеальною
                    if msg_plain == expected_plain:
                        ratio_text = 1.0
                except Exception:
                    ratio_text = 0.0

                combined_ratio = max(ratio, ratio_text)

                if combined_ratio < 0.99:
                    _pylog.debug(
                        "diff_html wid=%s cid=%s mid=%s ratio=%.3f ratio_text=%.3f %s",
                        wid,
                        cid,
                        mid,
                        ratio,
                        ratio_text,
                        _short_diff(expected_html_norm, msg_html_norm),
                    )
                    if ratio_text < 1.0:
                        _pylog.debug(
                            "diff_plain wid=%s cid=%s mid=%s %s",
                            wid,
                            cid,
                            mid,
                            _short_diff(expected_plain, msg_plain),
                        )

                if combined_ratio >= CANDIDATE_SIM_THRESHOLD:
                    _pylog.debug(
                        "listen: fuzzy_candidate wid=%s cid=%s mid=%s ratio=%.3f ratio_text=%.3f",
                        wid,
                        cid,
                        mid,
                        ratio,
                        ratio_text,
                    )
                    # якщо лінки не збігаються — відправляємо у foreign
                    exp_links = extract_links_from_html(expected_html_norm)
                    if not exp_links and expected_links_json:
                        try:
                            data = json.loads(expected_links_json)
                            if isinstance(data, list):
                                exp_links = [str(x) for x in data if x]
                        except Exception:
                            pass
                    cand_links = extract_links_from_html(msg_html_norm)

                    links_mismatch = False
                    if exp_links and cand_links and sorted(exp_links) != sorted(cand_links):
                        links_mismatch = True
                    elif not exp_links and cand_links:
                        # якщо очікуваних лінків немає, а у фактичному повідомленні вони є — теж вважаємо mismatch
                        links_mismatch = True
                    _pylog.debug(
                        "links_compare: wid=%s cid=%s mid=%s exp=%d msg=%d mismatch=%s exp_raw=%s msg_raw=%s",
                        wid,
                        cid,
                        mid,
                        len(exp_links),
                        len(cand_links),
                        links_mismatch,
                        exp_links,
                        cand_links,
                    )

                    if links_mismatch:
                        try:
                            watch_proc_db.insert_watch_candidate(
                                watch_id=wid,
                                channel_id=cid,
                                message_id=mid,
                                similarity=combined_ratio,
                                message_text=msg_html,
                                text_hash="",
                                ttl_days=1.0,
                                status="foreign",
                            )
                            try:
                                watch_events_db.insert_watch_event(
                                    wid,
                                    "foreign",
                                    json.dumps(
                                        {
                                            "watch_id": wid,
                                            "channel_id": cid,
                                            "message_id": mid,
                                            "similarity": combined_ratio,
                                            "reason": "links_mismatch",
                                        }
                                    ),
                                )
                            except Exception:
                                _pylog.exception(
                                    "similar: insert foreign event failed (wid=%s cid=%s mid=%s)", wid, cid, mid
                                )
                            log.info(
                                "similar: wid=%s cid=%s mid=%s ratio=%.3f -> foreign (links mismatch)",
                                wid,
                                cid,
                                mid,
                                combined_ratio,
                            )
                        except Exception:
                            _pylog.exception(
                                "similar: insert foreign candidate failed (wid=%s cid=%s mid=%s)", wid, cid, mid
                            )
                        continue

                    text_close_enough = ratio_text >= NEAR_IDENTICAL_TEXT_THRESHOLD
                    html_close_enough = ratio >= NEAR_IDENTICAL_TEXT_THRESHOLD

                    # Вважаємо matched лише якщо збігається і HTML, і plain (форматування не втрачено)
                    if html_close_enough and text_close_enough:
                        coverage_at = _calc_coverage_at()
                        matched_session = tag
                        matched_ok = True
                        try:
                            watch_proc_db.mark_matched_db(
                                wid, mid, coverage_at, matched_session=matched_session
                            )
                            watch_events_db.insert_watch_event(
                                wid,
                                "matched",
                                json.dumps(
                                    {
                                        "watch_id": wid,
                                        "channel_id": cid,
                                        "message_id": mid,
                                        "session": matched_session,
                                    }
                                ),
                            )
                        except Exception:
                            matched_ok = False

                        if matched_ok and SHEETS_OK and gsheets_buffer:
                            try:
                                gsheets_buffer.record_matched(wid)
                            except Exception:
                                _pylog.exception("gsheets_buffer.record_matched failed (wid=%s)", wid)
                        log.info(
                            "matched (html+text): wid=%s cid=%s mid=%s ratio=%.3f ratio_text=%.3f",
                            wid,
                            cid,
                            mid,
                            ratio,
                            ratio_text,
                        )
                        continue

                    text_hash_input = msg_plain or msg_html_norm
                    text_hash = watch_proc_db.calc_text_hash(text_hash_input)
                    key = (wid, text_hash)
                    now_m = _now_monotonic()
                    last_seen = _GLOBAL_CANDIDATE_SEEN.get(key)
                    if last_seen is None or (now_m - last_seen) >= CANDIDATE_SEEN_TTL:
                        _GLOBAL_CANDIDATE_SEEN[key] = now_m

                        try:
                            with session_scope() as db:
                                watch_proc_db.insert_watch_candidate_db(
                                    db,
                                    watch_id=wid,
                                    channel_id=cid,
                                    message_id=mid,
                                    similarity=combined_ratio,
                                    message_text=msg_html,
                                    text_hash=text_hash,
                                    ttl_days=1.0,
                                    status=watch_candidates_db.CANDIDATE_PENDING_STATUS,
                                )
                                watch_events_db.insert_watch_event(
                                    wid,
                                    "candidate",
                                    json.dumps(
                                        {
                                            "watch_id": wid,
                                            "channel_id": cid,
                                            "message_id": mid,
                                            "similarity": combined_ratio,
                                            "text_hash": text_hash,
                                        }
                                    ),
                                )
                            log.info("similar: wid=%s cid=%s mid=%s ratio=%.3f -> candidate", wid, cid, mid, combined_ratio)
                        except Exception:
                            _pylog.exception("similar: insert_watch_candidate failed (wid=%s cid=%s mid=%s)", wid, cid, mid)
                else:
                    _pylog.info(
                        "listen: no_match wid=%s cid=%s mid=%s sess=%s ratio=%.3f ratio_text=%.3f reason=ratio_low",
                        wid,
                        cid,
                        mid,
                        tag,
                        ratio,
                        ratio_text,
                    )
                continue

            # exact match пройшов — фіксуємо matched
            coverage_at = _calc_coverage_at()
            matched_session = tag
            matched_ok = True
            try:
                watch_proc_db.mark_matched_db(wid, mid, coverage_at, matched_session=matched_session)
                watch_events_db.insert_watch_event(
                    wid,
                    "matched",
                    json.dumps(
                        {
                            "watch_id": wid,
                            "channel_id": cid,
                            "message_id": mid,
                            "session": matched_session,
                        }
                    ),
                )
            except Exception:
                matched_ok = False

            if matched_ok and SHEETS_OK and gsheets_buffer:
                try:
                    gsheets_buffer.record_matched(wid)
                except Exception:
                    _pylog.exception("gsheets_buffer.record_matched failed (wid=%s)", wid)

    @cli.on(events.MessageEdited())
    async def _on_edited(ev: events.MessageEdited.Event):
        m: Message = ev.message

        cid = None
        try:
            if hasattr(m, "peer_id") and getattr(m.peer_id, "channel_id", None) is not None:
                cid = int(m.peer_id.channel_id)
            elif getattr(m, "chat_id", None) is not None:
                cid = int(m.chat_id)
        except Exception:
            cid = None

        if not cid or cid <= 0:
            return

        mid = int(getattr(m, "id", 0) or 0)
        if not mid:
            return

        try:
            wids = watch_proc_db.find_matched_by_message_db(cid, mid)
        except Exception:
            _pylog.exception("edited: find_matched_by_message failed (cid=%s mid=%s)", cid, mid)
            return

        candidate_entries: list[Any] = []
        if not wids:
            try:
                candidate_entries = watch_candidates_db.find_candidates_by_channel_message(
                    cid, mid, status=watch_candidates_db.CANDIDATE_PENDING_STATUS
                )
            except Exception:
                _pylog.exception("edited: find_candidates_by_channel_message failed (cid=%s mid=%s)", cid, mid)
                candidate_entries = []
            if not candidate_entries:
                return

        try:
            msg_html = _HTML_RENDER(m)
        except Exception:
            _pylog.exception("edited: HTML render failed (cid=%s mid=%s)", cid, mid)
            msg_html = (getattr(m, "message", "") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        target_wids = wids if wids else [int(c.watch_id) for c in candidate_entries if c.watch_id]

        for wid in target_wids:
            wc = _db_get_watch_core(int(wid))
            if not wc:
                continue
            expected_html = wc.get("expected_text_hash")
            if not expected_html:
                continue

            try:
                msg_html_norm = _normalize_html_for_edit(msg_html)
                expected_html_norm = _normalize_html_for_edit(expected_html)
                # Для edit: або повна ідентичність, або допускаємо дуже малу різницю (ratio>=EDIT_NEAR_THRESHOLD) без зміни лінків
                ok = msg_html_norm == expected_html_norm
                diff_ratio = 1.0
                links_same = True
                if not ok:
                    try:
                        exp_links = sorted(extract_links_from_html(expected_html_norm))
                        msg_links = sorted(extract_links_from_html(msg_html_norm))
                        links_same = exp_links == msg_links
                    except Exception:
                        links_same = True
                    try:
                        diff_ratio = SequenceMatcher(None, msg_html_norm, expected_html_norm).ratio()
                    except Exception:
                        diff_ratio = 0.0
                    if diff_ratio >= EDIT_NEAR_THRESHOLD and links_same:
                        ok = True
                        _pylog.debug(
                            "edited: wid=%s cid=%s mid=%s diff_ratio=%.3f (links unchanged) -> skip minor edit",
                            wid,
                            cid,
                            mid,
                            diff_ratio,
                        )
            except Exception:
                _pylog.exception("edited: exact_html_equal failed (wid=%s cid=%s mid=%s)", wid, cid, mid)
                ok = False

            if ok:
                continue

            # Лог додаткових даних для аналізу відмінностей
            try:
                diff_ratio = SequenceMatcher(None, msg_html_norm, expected_html_norm).ratio()
            except Exception:
                diff_ratio = 0.0
            _pylog.info(
                "edited: wid=%s cid=%s mid=%s -> edited (ratio=%.3f exp_len=%s msg_len=%s)",
                wid,
                cid,
                mid,
                diff_ratio,
                len(expected_html_norm or ""),
                len(msg_html_norm or ""),
            )

            now_str = _mark_done_edited_other(int(wid))
            try:
                event_type = "edited_other" if wid in wids else "edited_candidate"
                watch_events_db.insert_watch_event(
                    int(wid),
                    event_type,
                    json.dumps(
                        {
                            "watch_id": int(wid),
                            "channel_id": cid,
                            "message_id": mid,
                            "edited_at": now_str,
                        }
                    ),
                )
            except Exception:
                pass

            if wid not in wids and candidate_entries:
                for c in candidate_entries:
                    if int(c.watch_id or 0) != int(wid):
                        continue
                    try:
                        msg_plain = _strip_tags_to_text(msg_html_norm)
                        expected_plain = _strip_tags_to_text(expected_html_norm)
                        sim_val = SequenceMatcher(None, msg_plain, expected_plain).ratio()
                    except Exception:
                        sim_val = 0.0
                    try:
                        watch_candidates_db.merge_watch_candidate(
                            int(c.id),
                            mid,
                            watch_proc_db.calc_text_hash(msg_html_norm),
                            sim_val,
                            msg_html_norm,
                        )
                    except Exception:
                        _pylog.exception("edited: merge_watch_candidate failed (cid=%s mid=%s cand_id=%s)", cid, mid, c.id)

            log.info("edited: wid=%s cid=%s mid=%s -> edited_other at=%s", wid, cid, mid, now_str)

            if SHEETS_OK and gsheets_buffer:
                try:
                    gsheets_buffer.record_edited_other_post(int(wid), now_str)
                except Exception:
                    _pylog.exception("gsheets_buffer.record_edited_other_post failed (wid=%s)", wid)

    @cli.on(events.MessageDeleted())
    async def _on_deleted(ev: events.MessageDeleted.Event):
        cid: Optional[int] = None

        try:
            chat = await ev.get_chat()
            if chat is not None and getattr(chat, "id", None) is not None:
                cid = int(chat.id)
        except Exception:
            cid = None

        if not cid:
            try:
                raw = int(getattr(ev, "chat_id", 0) or 0)
                if raw:
                    cid = abs(raw)
                    if cid > 10 ** 12:
                        cid = cid - 10 ** 12
            except Exception:
                cid = None

        if not cid or cid <= 0:
            return

        for mid in (ev.deleted_ids or []):
            try:
                wids = watch_proc_db.find_matched_by_message_db(cid, int(mid))
            except Exception:
                _pylog.exception("deleted: DB lookup failed (cid=%s mid=%s)", cid, mid)
                continue

            if not wids:
                continue

            now_m = _now_monotonic()

            for wid in wids:
                last = _GLOBAL_DELETED_SEEN.get(wid)
                if last is not None and (now_m - last) < GLOBAL_DELETED_TTL:
                    continue
                _GLOBAL_DELETED_SEEN[wid] = now_m

                try:
                    prev_status = watch_proc_db.mark_done_deleted_db(wid)
                    # Якщо пост уже відстояв перегляди (status=done), не шлемо повторну подію
                    if prev_status == "done":
                        log.info("deleted: wid=%s cid=%s mid=%s -> status done, event skipped", wid, cid, mid)
                        continue

                    watch_events_db.insert_watch_event(
                        wid,
                        "deleted",
                        json.dumps(
                            {
                                "watch_id": wid,
                                "channel_id": cid,
                                "message_id": int(mid),
                            }
                        ),
                    )
                    log.info("deleted: wid=%s cid=%s mid=%s -> deleted", wid, cid, mid)
                except Exception:
                    _pylog.exception("deleted: mark_done_deleted/insert_event failed (wid=%s)", wid)

                if SHEETS_OK and gsheets_buffer:
                    try:
                        gsheets_buffer.record_deleted(wid)
                    except Exception:
                        _pylog.exception("gsheets_buffer.record_deleted failed (wid=%s)", wid)


# --- Setup -------------------------------------------------------------------


def setup(client=None, control_peer=None, monitor_buffer=None, **_):
    with session_scope() as db:
        active_channels = set(watch_proc_db.list_active_channels_db(db))
    log.info("posts_watch_listener: active_channels=%s", len(active_channels))

    if SHEETS_OK and gsheets_buffer:
        try:
            gsheets_buffer.set_flush_interval(15)
            gsheets_buffer.start_flusher()
            log.info("posts_watch_listener: gsheets_buffer flusher started")
        except Exception:
            _pylog.exception("failed to start gsheets_buffer flusher")

    slots = iter_pool_clients()
    for s in slots:
        try:
            tag = session_name(s.client)
            _attach_listener_for_client(tag, s.client)
            log.info("posts_watch_listener: attached listener to pool client: %s %s", tag, s.client)
        except Exception:
            _pylog.exception("attach failed for pool client: %s", getattr(s, "name", "?"))


    loop = asyncio.get_event_loop()

    if config.WATCH_VIEWS_ENABLED:
        loop.create_task(_views_worker(), name="posts_watch_views")
        log.info("posts_watch_listener: views worker scheduled")

    loop.create_task(_pending_expire_worker(), name="posts_watch_expire_pending")
    log.info("posts_watch_listener: pending-expire worker scheduled")

    try:
        with session_scope() as db:
            missing = watch_proc_db.list_pending_without_expected_db(db, limit=50)
            if missing:
                _pylog.warning(
                    "health-check: pending watches without expected_html: count=%s sample=%s",
                    len(missing),
                    missing[:10],
                )
    except Exception:
        _pylog.exception("health-check: list_pending_without_expected failed")
