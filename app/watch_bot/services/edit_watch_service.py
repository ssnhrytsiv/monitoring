from typing import Optional
import logging
from datetime import datetime, timedelta
import os

from telethon.tl.types import Message as TgMessage  # тип пересланого поста
from app.DAL.watch_posts_operations import (
    get_watch_channel_id,
    get_watch_source_url,
    manual_mark_matched,
    set_watch_status_pending,
    update_watch_time_window,
    update_watch_source_url,
)
from app.services.account_pool import is_already_subscribed
from app.utils.time_utils import MOSCOW_TIME_FORMAT, moscow_now
from app import config

log = logging.getLogger("active_watches.edit_service")

SHEETS_OK = False
try:
    from app.sheet_bot.services import gsheets_buffer

    SHEETS_OK = True
except Exception:
    gsheets_buffer = None  # type: ignore


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
    now_msq = moscow_now()
    return (now_msq + timedelta(hours=hrs)).strftime(MOSCOW_TIME_FORMAT)


from aiogram.types import Message as AiogramMessage
from app.DAL.watch_posts_operations import (
    get_watch_channel_id,
    get_watch_source_url,
    manual_mark_matched,
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

    # 3) coverage_at
    coverage_at = _calc_coverage_at()

    # 4) session/source_url → DAO виконає force_mark_matched + подію
    source_url = get_watch_source_url(wid)
    ok = manual_mark_matched(
        watch_id=wid,
        channel_id=cid,
        message_id=mid,
        coverage_check_at=coverage_at,
        matched_session=None,
        source_url=source_url,
        is_manual=True,
    )
    if not ok:
        log.warning("manual_match: manual_mark_matched failed (wid=%s, mid=%s)", wid, mid)
        return False

    if SHEETS_OK and gsheets_buffer:
        try:
            gsheets_buffer.record_matched(wid)
        except Exception:
            log.exception("manual_match: gsheets_buffer.record_matched failed (wid=%s)", wid)

    log.info(
        "manual_match: wid=%s cid=%s mid=%s (pending/expired -> matched)",
        wid,
        cid,
        mid,
    )
    return True
