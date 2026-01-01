from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Callable, Optional, Dict, Any
from zoneinfo import ZoneInfo
import re

from telethon import events
from telethon.tl.types import Message

from app.telethon_client import client as MAIN_CLIENT
from app.logging_json import get_logger
from app.services.posts_watch_result_db import (
    list_active_channels,
    get_pending_by_channel,
    mark_matched,
    list_due_coverage,
    mark_done_views,
    mark_done_deleted,
    find_matched_by_message,
    list_due_pending_expire,
    mark_expired,
    raw_connection,
    insert_watch_event,
)
from app.services.html_match import exact_html_equal
from app.services.account_pool import iter_pool_clients, session_name
from app import config
import html as _html_mod

try:
    from app.services.post_watch_db import list_templates_full
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

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
COVERAGE_POLL_TICK_SEC = 30

_GLOBAL_DELETED_SEEN: Dict[int, float] = {}
GLOBAL_DELETED_TTL = 180.0


def _now_monotonic() -> float:
    return asyncio.get_event_loop().time()


def _human(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


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
        return 24.0


DEFAULT_COVERAGE_HOURS: float = _read_default_coverage_hours()


def _calc_coverage_at(hours_after: float | None = None) -> Optional[str]:
    if not config.WATCH_VIEWS_ENABLED:
        return None
    hrs = hours_after if hours_after is not None else DEFAULT_COVERAGE_HOURS
    now_msq = datetime.now(MOSCOW_TZ)
    return _human(now_msq + timedelta(hours=hrs))


_HTML_RENDER: Optional[Callable[[Message], str]] = None
_HTML_RENDER_SRC = None


def _init_html_renderer():
    global _HTML_RENDER, _HTML_RENDER_SRC
    try:
        from app.plugins.post_templates import _extract_message_html as _rh  # type: ignore
        _HTML_RENDER = _rh
        _HTML_RENDER_SRC = "app.plugins.post_templates._extract_message_html"
        return
    except Exception:
        pass
    try:
        from app.services.html_render import render_html as _rh  # type: ignore
        _HTML_RENDER = _rh
        _HTML_RENDER_SRC = "app.services.html_render.render_html"
        return
    except Exception:
        pass
    for mod, attr in [
        ("app.services.post_match", "render_html"),
        ("app.services.post_matcher", "render_html"),
        ("app.services.post_match", "message_to_html"),
        ("app.services.html_match", "message_to_html"),
    ]:
        try:
            _HTML_RENDER = getattr(__import__(mod, fromlist=[attr]), attr)  # type: ignore
            _HTML_RENDER_SRC = f"{mod}.{attr}"
            return
        except Exception:
            pass

    def _fallback_render(m: Message) -> str:
        txt = getattr(m, "message", "") or ""
        return txt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    _HTML_RENDER = _fallback_render
    _HTML_RENDER_SRC = "fallback_plaintext_no_br"


_init_html_renderer()


def _db_get_watch_core(wid: int) -> Optional[Dict[str, Any]]:
    try:
        conn = raw_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT channel_id, template_id, expected_text_hash, expected_links_json,
                   time_window_start, time_window_end
            FROM watch_posts
            WHERE id = ?
            """,
            (wid,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "channel_id": int(row[0]),
            "template_id": int(row[1]) if row[1] is not None else None,
            "expected_text_hash": row[2],
            "expected_links_json": row[3],
            "time_window_start": row[4],
            "time_window_end": row[5],
        }
    except Exception:
        _pylog.exception("_db_get_watch_core failed (wid=%s)", wid)
    return None


# --- HTML normalization ------------------------------------------------------

_A_TAG_RE = re.compile(r'<a\s+href=(?P<q1>"|\')(?P<href>.+?)(?P=q1)>(?P<body>.*?)</a>', re.DOTALL | re.IGNORECASE)


def _strip_simple_tags(html_fragment: str) -> str:
    """
    Видаляє прості теги форматування (<b>, <u>, <i>, <strong>, <em>) з фрагмента,
    залишаючи тільки текст усередині.
    """
    # прибираємо відкриваючі/закриваючі теги b/u/i/strong/em (без атрибутів)
    return re.sub(r'</?(?:b|u|i|strong|em)>', '', html_fragment, flags=re.IGNORECASE)


def _normalize_html_full(html_text: str) -> str:
    """
    Розширена нормалізація HTML для вотчів:
      - застосовує _normalize_html_links (розкриває <a>, приводить &amp; -> &);
      - декодує HTML-ентіті (&quot; -> ", &nbsp; -> пробіл, ...);
      - трохи чистить пробіли.

    Це якраз фіксить кейси типу:
      <i>&quot;Бывший коллега</i> ...
      <i>"Бывший коллега</i> ...
    щоб вони вважалися однаковими.
    """
    if not html_text:
        return ""

    # 1) твоя існуюча нормалізація лінків
    s = _normalize_html_links(html_text)

    # 2) декодуємо HTML-ентіті (&quot; -> ", &nbsp; -> пробіл, &amp; -> &, ...)
    s = _html_mod.unescape(s)

    # 3) легка нормалізація пробілів
    # прибираємо подвоєні/троєні пробіли
    s = re.sub(r"\s{2,}", " ", s)
    # обрізаємо зайві пробіли по краях
    s = s.strip()

    return s


def _normalize_html_links(html: str) -> str:
    """
    Нормалізує HTML так, щоб такі варіанти вважалися однаковими:

      X
      <u>X</u>
      <b><u>X</u></b>
      <a href="X">X</a>
      <a href="X"><u>X</u></a>
      <a href="X"><b><u>X</u></b></a>
      та подібні комбінації форматування навколо X.

    Якщо весь текст усередині <a> після видалення простих тегів дорівнює href,
    ми розкриваємо <a> і залишаємо лише його тіло (з форматуванням).
    """
    if not html:
        return html

    def _replace_a(m: re.Match) -> str:
        href = m.group("href")
        body = m.group("body")

        # Текст усередині <a> без b/u/i/strong/em
        inner_plain = _strip_simple_tags(body)
        # Також прибираємо зайві пробіли
        inner_plain_stripped = inner_plain.strip()
        href_stripped = href.strip()

        if inner_plain_stripped == href_stripped:
            # href і (розформатований) текст однакові → прибираємо сам <a>,
            # але зберігаємо внутрішні теги форматування (<b>, <u>, ...)
            return body
        else:
            # інакше залишаємо <a> як є
            return m.group(0)

    # 1) Нормалізація <a href="X">...</a>, де ... по суті X з простим форматуванням
    html = _A_TAG_RE.sub(_replace_a, html)

    # 2) &amp; → &
    html = html.replace("&amp;", "&")

    # 3) Прибрати зайві пробіли навколо <a> (якщо ще лишилися)
    html = re.sub(r">\s+([^<])", r">\1", html)  # <a ...>  X -> <a ...>X
    html = re.sub(r"([^>])\s+</a>", r"\1</a>", html)  # X  </a> -> X</a>

    return html


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

            due = list_due_coverage()
            for watch_id, channel_id, msg_id, matched_session in due:
                cli = pool_map.get(matched_session) if matched_session else None
                if cli is None:
                    cli = any_cli
                try:
                    msg: Message | None = await cli.get_messages(entity=channel_id, ids=msg_id)
                except Exception as e:
                    _pylog.exception("views: get_messages failed (wid=%s cid=%s mid=%s): %s", watch_id, channel_id,
                                     msg_id, e)
                    # якщо не можемо отримати entity — вважаємо покритим, щоб не зациклитись
                    try:
                        mark_done_views(watch_id, 0)
                        insert_watch_event(
                            watch_id,
                            "views",
                            {
                                "watch_id": watch_id,
                                "channel_id": channel_id,
                                "message_id": msg_id,
                                "views": 0,
                                "status": "entity_miss",
                            },
                        )
                    except Exception:
                        _pylog.exception("views: mark_done_views failed (wid=%s) after entity miss", watch_id)
                    msg = None

                if msg is None:
                    continue

                views = int(getattr(msg, "views", 0) or 0)
                try:
                    mark_done_views(watch_id, views)
                    insert_watch_event(
                        watch_id,
                        "views",
                        {
                            "watch_id": watch_id,
                            "channel_id": channel_id,
                            "message_id": msg_id,
                            "views": views,
                        },
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
            due_ids = list_due_pending_expire()
            for wid in due_ids:
                try:
                    mark_expired(wid)
                    insert_watch_event(wid, "expired", {"watch_id": wid})
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
    now_str = _human(datetime.now(MOSCOW_TZ))
    try:
        conn = raw_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE watch_posts
            SET status='done', updated_at=?
            WHERE id=? AND status IN ('matched','done')
            """,
            (now_str, int(wid)),
        )
        conn.commit()
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
        # ігноруємо MAIN
        if tag == "MAIN":
            return
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
            pending = get_pending_by_channel(cid)
        except Exception:
            _pylog.exception("listen: get_pending_by_channel failed (cid=%s)", cid)
            return

        if not pending:
            _pylog.info("listen: no pending watches for cid=%s", cid)
            return

        _pylog.info("listen: found %s pending watches for cid=%s", len(pending), cid)

        try:
            msg_html = _HTML_RENDER(m) if _HTML_RENDER else (getattr(m, "message", "") or "")
        except Exception:
            _pylog.exception("listen: HTML render failed (cid=%s mid=%s)", cid, mid)
            msg_html = (getattr(m, "message", "") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        matched_any = False

        for row in pending:
            wid = int(row["id"])
            expected_html = row.get("expected_text_hash")
            if not expected_html:
                _pylog.info("listen: wid=%s has no expected_html, skip", wid)
                continue

            try:
                # РОЗШИРЕНА нормалізація:
                #  - _normalize_html_links (a href="X" vs X)
                #  - html.unescape (&quot; vs ")
                msg_html_norm = _normalize_html_full(msg_html)
                expected_html_norm = _normalize_html_full(expected_html)

                ok = exact_html_equal(msg_html_norm, expected_html_norm)
               # _pylog.info(
                #    "listen: compare wid=%s cid=%s mid=%s session=%s -> %s",
                #    wid, cid, mid, tag, ok,
                #)
            except Exception:
                _pylog.exception("listen: exact_html_equal failed (wid=%s cid=%s mid=%s)", wid, cid, mid)
                ok = False

            if not ok:
                continue

            coverage_at = _calc_coverage_at()
            matched_session = tag
            try:
                mark_matched(wid, mid, coverage_at, matched_session=matched_session)
                insert_watch_event(
                    wid,
                    "matched",
                    {
                        "watch_id": wid,
                        "channel_id": cid,
                        "message_id": mid,
                        "session": matched_session,
                    },
                )
                matched_any = True
                #log.info("listen: MATCH wid=%s cid=%s mid=%s session=%s", wid, cid, mid, matched_session)
            except Exception:
                #_pylog.exception("listen: mark_matched failed (wid=%s cid=%s mid=%s)", wid, cid, mid)
                continue

            if SHEETS_OK and gsheets_buffer:
                try:
                    gsheets_buffer.record_matched(wid)
                except Exception:
                    _pylog.exception("gsheets_buffer.record_matched failed (wid=%s)", wid)

        if not matched_any:
            return

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
            wids = find_matched_by_message(cid, mid)
        except Exception:
            _pylog.exception("edited: find_matched_by_message failed (cid=%s mid=%s)", cid, mid)
            return

        if not wids:
            return

        try:
            msg_html = _HTML_RENDER(m) if _HTML_RENDER else (getattr(m, "message", "") or "")
        except Exception:
            _pylog.exception("edited: HTML render failed (cid=%s mid=%s)", cid, mid)
            msg_html = (getattr(m, "message", "") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        for wid in wids:
            wc = _db_get_watch_core(int(wid))
            if not wc:
                continue
            expected_html = wc.get("expected_text_hash")
            if not expected_html:
                continue

            try:
                msg_html_norm = _normalize_html_full(msg_html)
                expected_html_norm = _normalize_html_full(expected_html)
                ok = exact_html_equal(msg_html_norm, expected_html_norm)
            except Exception:
                _pylog.exception("edited: exact_html_equal failed (wid=%s cid=%s mid=%s)", wid, cid, mid)
                ok = False

            if ok:
                continue

            now_str = _mark_done_edited_other(int(wid))
            try:
                insert_watch_event(
                    int(wid),
                    "edited_other",
                    {
                        "watch_id": int(wid),
                        "channel_id": cid,
                        "message_id": mid,
                        "edited_at": now_str,
                    },
                )
            except Exception:
                pass

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
                wids = find_matched_by_message(cid, int(mid))
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
                    mark_done_deleted(wid)
                    insert_watch_event(
                        wid,
                        "deleted",
                        {
                            "watch_id": wid,
                            "channel_id": cid,
                            "message_id": int(mid),
                        },
                    )
                    log.info("deleted: wid=%s cid=%s mid=%s -> done", wid, cid, mid)
                except Exception:
                    _pylog.exception("deleted: mark_done_deleted failed (wid=%s)", wid)

                if SHEETS_OK and gsheets_buffer:
                    try:
                        gsheets_buffer.record_deleted(wid)
                    except Exception:
                        _pylog.exception("gsheets_buffer.record_deleted failed (wid=%s)", wid)


# --- Setup -------------------------------------------------------------------


def setup(client=None, control_peer=None, monitor_buffer=None, **_):
    active_channels = set(list_active_channels())
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

    # _attach_listener_for_client("MAIN", MAIN_CLIENT)
    # log.info("posts_watch_listener: attached listener to MAIN client")

    loop = asyncio.get_event_loop()

    if config.WATCH_VIEWS_ENABLED:
        loop.create_task(_views_worker(), name="posts_watch_views")
        log.info("posts_watch_listener: views worker scheduled")

    loop.create_task(_pending_expire_worker(), name="posts_watch_expire_pending")
    log.info("posts_watch_listener: pending-expire worker scheduled")
