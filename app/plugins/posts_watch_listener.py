from __future__ import annotations

import asyncio
import logging
import os
import json
from datetime import datetime, timedelta
from typing import Callable, Optional, Dict, Tuple, Any
from zoneinfo import ZoneInfo

from telethon import events
from telethon.tl.types import Message, Channel, Chat

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
    raw_connection,  # ⬅️ потрібен для читання owner із БД (залишаю як було)
)
from app.services.html_match import exact_html_equal
from app.services.account_pool import iter_pool_clients, session_name
from app import config

try:
    from app.services.post_watch_db import list_templates_full
except Exception:
    list_templates_full = None  # type: ignore

# ⬇️ нова інтеграція з Google Sheets через буфер
SHEETS_OK = False
try:
    from app.services import gsheets_buffer
    SHEETS_OK = True
except Exception:
    gsheets_buffer = None  # type: ignore

log = get_logger("plugin.posts_watch_listener")
_pylog = logging.getLogger("plugin.posts_watch_listener")

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
COVERAGE_POLL_TICK_SEC = 30

# --- Глобальна дідуплікація видалень між усіма лістенерами (процес-wide) ---
_GLOBAL_DELETED_SEEN: Dict[int, float] = {}   # wid -> monotonic_ts, спільний для всіх сесій
GLOBAL_DELETED_TTL = 180.0  # секунди; протягом цього часу повторні delete того ж wid ігноруються

def _now_monotonic() -> float:
    # один спільний монотонний таймер для всього модуля
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
log.info("posts_watch_listener: HTML renderer = %s", _HTML_RENDER_SRC)


_TEMPLATE_TITLE_CACHE: Dict[int, Optional[str]] = {}
def _get_template_title(tid: Optional[int]) -> Optional[str]:
    if not tid or tid <= 0:
        return None
    if tid in _TEMPLATE_TITLE_CACHE:
        return _TEMPLATE_TITLE_CACHE[tid]
    title: Optional[str] = None
    try:
        if list_templates_full:
            rows = list_templates_full(limit=500)
            for r in rows:
                if r[0] == tid:
                    title = (r[5] if len(r) > 5 else None) or None
                    break
    except Exception:
        _pylog.exception("template title lookup failed (tid=%s)", tid)
    _TEMPLATE_TITLE_CACHE[tid] = title
    return title


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


# (залишаю як було; може згодитися для інших місць)
def _db_get_owner_for_channel(channel_id: int) -> Tuple[Optional[str], Optional[str]]:
    """
    Очікує таблицю channels_meta(channel_id, owner_display, owner_link) — залишено без змін.
    """
    try:
        conn = raw_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT owner_display, owner_link FROM channels_meta WHERE channel_id = ? LIMIT 1",
            (int(channel_id),),
        )
        row = cur.fetchone()
        if not row:
            return None, None
        od, ol = row[0], row[1]
        return (str(od) if od else None, str(ol) if ol else None)
    except Exception:
        _pylog.exception("_db_get_owner_for_channel failed (cid=%s)", channel_id)
        return None, None


def _sheet_date_from_time_window_start(tws: Optional[str]) -> str:
    if tws:
        try:
            dt = datetime.strptime(tws, "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")


def _resolve_channel_title(entity: Optional[Channel | Chat]) -> Optional[str]:
    try:
        if entity and getattr(entity, "title", None):
            return str(entity.title)
    except Exception:
        pass
    return None


def _links_text_from_json(links_json: Optional[str]) -> str:
    try:
        if not links_json:
            return ""
        arr = json.loads(links_json)
        if isinstance(arr, list):
            return "\n".join(str(x) for x in arr if x)
    except Exception:
        pass
    return ""


async def _views_worker():
    if not config.WATCH_VIEWS_ENABLED:
        log.info("posts_watch_listener: views disabled; worker not started")
        return

    log.info("posts_watch_listener: views worker started (tick=%ss)", COVERAGE_POLL_TICK_SEC)
    while True:
        try:
            slots = iter_pool_clients()
            pool_map = {session_name(s.client): s.client for s in slots}

            due = list_due_coverage()
            if due:
                log.debug("views: due rows=%s", len(due))

            for watch_id, channel_id, msg_id, matched_session in due:
                cli = MAIN_CLIENT if not matched_session or matched_session == "MAIN" else pool_map.get(matched_session)
                if cli is None:
                    cli = MAIN_CLIENT
                try:
                    msg: Message | None = await cli.get_messages(entity=channel_id, ids=msg_id)
                except Exception as e:
                    _pylog.exception(
                        "views: get_messages failed (wid=%s cid=%s mid=%s session=%s): %s",
                        watch_id, channel_id, msg_id, matched_session, e
                    )
                    msg = None

                if msg is None:
                    log.debug("views: msg not fetched (wid=%s) — skip until next tick", watch_id)
                    continue

                views = int(getattr(msg, "views", 0) or 0)
                try:
                    mark_done_views(watch_id, views)
                    log.info("views: views=%s -> done (wid=%s cid=%s mid=%s session=%s)",
                             views, watch_id, channel_id, msg_id, matched_session)
                except Exception:
                    _pylog.exception("views: mark_done_views failed (wid=%s)", watch_id)

                # ⬇️ оновлення у Google Sheets через буфер (коалесинг, 30s флаш)
                if SHEETS_OK and gsheets_buffer:
                    try:
                        gsheets_buffer.record_views(watch_id, views)
                    except Exception:
                        _pylog.exception("gsheets_buffer.record_views failed (wid=%s)", watch_id)

        except asyncio.CancelledError:
            log.warning("views worker cancelled")
            break
        except Exception:
            _pylog.exception("views: tick failed")

        await asyncio.sleep(COVERAGE_POLL_TICK_SEC)


async def _pending_expire_worker():
    log.info("posts_watch_listener: pending-expire worker started (tick=%ss)", COVERAGE_POLL_TICK_SEC)
    while True:
        try:
            due_ids = list_due_pending_expire()
            for wid in due_ids:
                try:
                    mark_expired(wid)
                    log.info("expire: wid=%s -> expired (pending window elapsed)", wid)
                except Exception:
                    _pylog.exception("expire: mark_expired failed (wid=%s)", wid)
        except asyncio.CancelledError:
            log.warning("pending-expire worker cancelled")
            break
        except Exception:
            _pylog.exception("expire: tick failed")
        await asyncio.sleep(COVERAGE_POLL_TICK_SEC)


def _attach_listener_for_client(tag: str, cli) -> None:
    # Локальний кеш для дідуплікації повторних deleted-подій

    @cli.on(events.NewMessage())
    async def _on_new_message(ev: events.NewMessage.Event):
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

        try:
            pending = get_pending_by_channel(cid)
        except Exception:
            _pylog.exception("listen: get_pending_by_channel failed (cid=%s)", cid)
            return

        if not pending:
            log.debug("listen: [%s] new msg cid=%s mid=%s bytes=%s (no pending)",
                      tag, cid, mid, len((getattr(m, 'message', '') or "")))
            return

        try:
            msg_html = _HTML_RENDER(m) if _HTML_RENDER else (getattr(m, "message", "") or "")
        except Exception:
            _pylog.exception("listen: HTML render failed (cid=%s mid=%s)", cid, mid)
            msg_html = (getattr(m, "message", "") or "") \
                .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        log.debug("listen: [%s] new msg cid=%s mid=%s msg_html_len=%s pending=%s",
                  tag, cid, mid, len(msg_html or ""), len(pending))

        matched_any = False

        try:
            for row in pending:
                wid = int(row["id"])
                expected_html = row.get("expected_text_hash")
                if not expected_html:
                    log.warning("listen: wid=%s has empty expected_html — skip", wid)
                    continue

                try:
                    ok = exact_html_equal(msg_html, expected_html)
                except Exception:
                    _pylog.exception("listen: exact_html_equal failed (wid=%s cid=%s mid=%s)", wid, cid, mid)
                    ok = False

                if ok:
                    coverage_at = _calc_coverage_at()
                    matched_session = tag
                    try:
                        mark_matched(wid, mid, coverage_at, matched_session=matched_session)
                        matched_any = True
                        log.info("listen: [%s] MATCH wid=%s cid=%s mid=%s cov_at=%s session=%s",
                                 tag, wid, cid, mid, coverage_at, matched_session)
                    except Exception:
                        _pylog.exception("listen: mark_matched failed (wid=%s cid=%s mid=%s)", wid, cid, mid)
                        continue

                    # ⬇️ Google Sheets (коалесинг у буфері)
                    if SHEETS_OK and gsheets_buffer:
                        try:
                            gsheets_buffer.record_matched(wid)
                        except Exception:
                            _pylog.exception("gsheets_buffer.record_matched failed (wid=%s)", wid)

                else:
                    log.debug(
                        "listen: [%s] no-match wid=%s cid=%s mid=%s (lens: msg=%s vs tpl=%s)\n"
                        "  msg[:160]=%r\n  tpl[:160]=%r",
                        tag, wid, cid, mid,
                        len(msg_html or ""), len(expected_html or ""),
                        (msg_html or "")[:160], (expected_html or "")[:160]
                    )

        finally:
            # Нічого не флашимо вручну — це робить фоновий флашер кожні ~30с (або за порогом)
            pass

        if not matched_any:
            log.debug("listen: [%s] ended with no matches (cid=%s mid=%s)", tag, cid, mid)

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
            log.debug("deleted: cannot resolve cid (raw chat_id=%s)", getattr(ev, "chat_id", None))
            return

        for mid in (ev.deleted_ids or []):
            try:
                wids = find_matched_by_message(cid, int(mid))
            except Exception:
                _pylog.exception("deleted: DB lookup failed (cid=%s mid=%s)", cid, mid)
                continue

            if not wids:
                log.debug("deleted: no matched rows for cid=%s mid=%s", cid, mid)
                continue

            now_m = _now_monotonic()

            for wid in wids:
                # 🔒 Глобальна дідупка між усіма лістенерами (процес-wide)
                last = _GLOBAL_DELETED_SEEN.get(wid)
                if last is not None and (now_m - last) < GLOBAL_DELETED_TTL:
                    log.debug("deleted: wid=%s skipped (global dedup within %.0fs)", wid, GLOBAL_DELETED_TTL)
                    continue
                _GLOBAL_DELETED_SEEN[wid] = now_m  # тільки перший робить БД+Sheets

                try:
                    mark_done_deleted(wid)
                    log.info("deleted: wid=%s -> done (cid=%s mid=%s)", wid, cid, mid)
                except Exception:
                    _pylog.exception("deleted: mark_done_deleted failed (wid=%s cid=%s mid=%s)", wid, cid, mid)

                if SHEETS_OK and gsheets_buffer:
                    try:
                        gsheets_buffer.record_deleted(wid)
                    except Exception:
                        _pylog.exception("gsheets_buffer.record_deleted failed (wid=%s)", wid)


def setup(client=None, control_peer=None, monitor_buffer=None, **_):
    active_channels = set(list_active_channels())
    if not active_channels:
        log.info("posts_watch_listener: no active channels at load (listens to all and filters by DB)")
    else:
        log.info("posts_watch_listener: active channels at load: %s", len(active_channels))

    # Запускаємо фоновий флашер буфера (коалесинг і батчі кожні ~30с)
    if SHEETS_OK and gsheets_buffer:
        try:
            gsheets_buffer.set_flush_interval(15)  # за ТЗ — частіше ніж година; 15с, якщо є що флашити
            gsheets_buffer.start_flusher()
            log.info("posts_watch_listener: gsheets_buffer flusher started")
        except Exception:
            _pylog.exception("failed to start gsheets_buffer flusher")

    slots = iter_pool_clients()
    for s in slots:
        try:
            tag = session_name(s.client)
            _attach_listener_for_client(tag, s.client)
            log.info("posts_watch_listener: attached listener to pool client: %s", tag)
        except Exception:
            _pylog.exception("attach failed for pool client: %s", getattr(s, "name", "?"))

    _attach_listener_for_client("MAIN", MAIN_CLIENT)
    log.info("posts_watch_listener: attached listener to MAIN client")

    loop = asyncio.get_event_loop()

    if config.WATCH_VIEWS_ENABLED:
        loop.create_task(_views_worker(), name="posts_watch_views")
        log.info("posts_watch_listener: views worker scheduled")
    else:
        log.info("posts_watch_listener: views disabled; no views worker started")

    loop.create_task(_pending_expire_worker(), name="posts_watch_expire_pending")
    log.info("posts_watch_listener: pending-expire worker scheduled")