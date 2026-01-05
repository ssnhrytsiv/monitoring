import os
from typing import Optional
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telethon.tl.types import Message as TgMessage  # тип пересланого поста

from app.notificator_bot.db.posts_watch_result_db import (
    raw_connection,
    insert_watch_event,
    get_watch_source_url,
    force_mark_matched,  # НОВА функція, потрібно додати в posts_watch_result_db.py
)
from app.services.time_utils import msk_now
from app.services.account_pool import is_already_subscribed
from app import config

log = logging.getLogger("active_watches.edit_service")

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

SHEETS_OK = False
try:
    from app.sheet_bot.services import gsheets_buffer

    SHEETS_OK = True
except Exception:
    gsheets_buffer = None  # type: ignore


def set_watch_status_pending(wid: int) -> bool:
    """
    Встановлює статус watch_posts.id = wid у 'pending'.
    Повертає True при успіху, False при помилці.
    """
    conn = raw_connection()
    cur = conn.cursor()
    now = msk_now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        cur.execute(
            """
            UPDATE watch_posts
            SET status='pending', updated_at=?
            WHERE id = ?
            """,
            (now, wid),
        )
        conn.commit()
        try:
            insert_watch_event(wid, "set_pending", {"via": "bot_edit"})
        except Exception:
            pass
        return True
    except Exception as e:
        log.exception("set_watch_status_pending failed for wid=%s: %s", wid, e)
        return False


def update_watch_time_window(
    wid: int,
    tw_start: str,
    tw_end: str,
) -> bool:
    """
    Оновлює time_window_start/time_window_end для watch_posts.id = wid.
    tw_start, tw_end – рядки 'YYYY-MM-DD HH:MM:SS'.
    """
    conn = raw_connection()
    cur = conn.cursor()
    now = msk_now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        cur.execute(
            """
            UPDATE watch_posts
            SET time_window_start = ?, time_window_end = ?, updated_at = ?
            WHERE id = ?
            """,
            (tw_start, tw_end, now, wid),
        )
        conn.commit()
    except Exception as e:
        log.exception("update_watch_time_window failed for wid=%s: %s", wid, e)
        return False

    try:
        insert_watch_event(
            wid,
            "time_window_updated",
            {"tw_start": tw_start, "tw_end": tw_end},
        )
    except Exception:
        pass

    return True


def update_watch_source_url(wid: int, url: str) -> bool:
    """
    Оновлює source_url для watch_posts.id = wid.
    """
    conn = raw_connection()
    cur = conn.cursor()
    now = msk_now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        cur.execute(
            """
            UPDATE watch_posts
            SET source_url = ?, updated_at = ?
            WHERE id = ?
            """,
            (url, now, wid),
        )
        conn.commit()
    except Exception as e:
        log.exception("update_watch_source_url failed for wid=%s: %s", wid, e)
        return False

    try:
        insert_watch_event(
            wid,
            "source_updated",
            {"url": url},
        )
    except Exception:
        pass

    return True


def _read_default_coverage_hours() -> float:
    """
    Читаємо ті ж налаштування, що й posts_watch_listener._read_default_coverage_hours.
    Якщо щось піде не так – fallback 24 години.
    """
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
    """
    Аналог _calc_coverage_at з posts_watch_listener.
    """
    if not config.WATCH_VIEWS_ENABLED:
        return None
    hrs = hours_after if hours_after is not None else DEFAULT_COVERAGE_HOURS
    now_msq = datetime.now(MOSCOW_TZ)
    return (now_msq + timedelta(hours=hrs)).strftime("%Y-%m-%d %H:%M:%S")


from aiogram.types import Message as AiogramMessage
from app.notificator_bot.db.posts_watch_result_db import (
    raw_connection,
    insert_watch_event,
    get_watch_source_url,
    get_watch_channel_id,
    force_mark_matched,
    get_session_for_source_url,  # новий хелпер
)
async def manual_match_watch_from_message(wid: int, msg: AiogramMessage) -> bool:
    # 1) channel_id з БД
    cid = get_watch_channel_id(wid)
    if not cid:
        log.warning("manual_match: no channel_id in DB for wid=%s", wid)
        return False

    # 2) message_id з форварду
    mid = msg.forward_from_message_id
    if not mid:
        # fallback: якщо бот сидить у самому каналі і бачить native-пост
        mid = msg.message_id

    if not mid:
        log.warning("manual_match: cannot resolve message_id from msg (wid=%s)", wid)
        return False

    # 3) source_url -> session через історичний мапінг (links + membership)
    source_url = get_watch_source_url(wid)
    matched_session: Optional[str] = None
    if source_url:
        try:
            matched_session = get_session_for_source_url(source_url)
        except Exception as e:
            log.exception(
                "manual_match: get_session_for_source_url failed (wid=%s, url=%s): %s",
                wid,
                source_url,
                e,
            )

    if not matched_session:
        matched_session = "MAIN"

    # 4) coverage_at
    coverage_at = _calc_coverage_at()

    # 5) force_mark_matched (pending/expired -> matched)
    try:
        force_mark_matched(wid, mid, coverage_at, matched_session=matched_session)
    except Exception as e:
        log.exception("manual_match: force_mark_matched failed (wid=%s, mid=%s): %s", wid, mid, e)
        return False

    # 6) подія matched + Excel
    try:
        insert_watch_event(
            wid,
            "matched",
            {
                "watch_id": wid,
                "channel_id": cid,
                "message_id": mid,
                "session": matched_session,
                "manual": True,
            },
        )
    except Exception:
        pass

    if SHEETS_OK and gsheets_buffer:
        try:
            gsheets_buffer.record_matched(wid)
        except Exception:
            log.exception("manual_match: gsheets_buffer.record_matched failed (wid=%s)", wid)

    log.info(
        "manual_match: wid=%s cid=%s mid=%s session=%s (pending/expired -> matched)",
        wid,
        cid,
        mid,
        matched_session,
    )
    return True
