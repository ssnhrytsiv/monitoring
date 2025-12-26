import logging
from typing import Tuple, Optional

from telethon import errors

from app.utils.throttle import throttle_bot
from app.utils.tg_links import extract_bot_username
from app.services import channel_db

log = logging.getLogger("services.bot_actions")


async def ensure_bot_started(client, url: str, *, owner_display: Optional[str] = None, owner_username: Optional[str] = None, batch_id: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """
    Надсилає /start боту. Повертає (status, username).
    status:
      - bot_started
      - bot_flood_wait_<sec>
      - bot_invalid / bot_error
    """
    username = extract_bot_username(url)
    if not username:
        return "bot_invalid", None

    await throttle_bot()
    try:
        await client.send_message(username, "/start")
        channel_db.upsert_bot_link(
            username=username,
            raw_url=url,
            status="bot_started",
            session=None,
            owner_display=owner_display,
            owner_username=owner_username,
            batch_id=batch_id,
            error=None,
        )
        log.info("bot_actions: sent /start to %s", username)
        return "bot_started", username
    except errors.FloodWaitError as e:
        channel_db.upsert_bot_link(
            username=username,
            raw_url=url,
            status=f"bot_flood_wait_{e.seconds}",
            session=None,
            owner_display=owner_display,
            owner_username=owner_username,
            batch_id=batch_id,
            error=str(e),
        )
        log.warning("bot_actions: flood wait %ss on %s", e.seconds, username)
        return f"bot_flood_wait_{e.seconds}", username
    except errors.UsernameNotOccupiedError:
        channel_db.upsert_bot_link(
            username=username,
            raw_url=url,
            status="bot_invalid",
            session=None,
            owner_display=owner_display,
            owner_username=owner_username,
            batch_id=batch_id,
            error="username_not_found",
        )
        return "bot_invalid", username
    except Exception as e:
        channel_db.upsert_bot_link(
            username=username,
            raw_url=url,
            status="bot_error",
            session=None,
            owner_display=owner_display,
            owner_username=owner_username,
            batch_id=batch_id,
            error=str(e),
        )
        log.exception("bot_actions: send_message failed for %s", username)
        return "bot_error", username
