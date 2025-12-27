import logging
from typing import Tuple, Optional

from telethon import errors
from telethon.tl.functions.contacts import UnblockRequest

from app.utils.throttle import throttle_bot
from app.utils.tg_links import extract_bot_username
from app.services import channel_db
from app.services.account_pool import session_name

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
    sess = None
    try:
        sess = session_name(client)
    except Exception:
        sess = None
    try:
        # на всякий випадок розблокуємо, якщо бот був у блок-листі
        try:
            await client(UnblockRequest(username))
        except Exception as e:
            log.debug("bot_actions: unblock failed for %s (session=%s): %s", username, sess or "-", e)
        log.info("bot_actions: sending /start to %s (session=%s, batch=%s)", username, sess or "-", batch_id)
        await client.send_message(username, "/start")
        channel_db.upsert_bot_link(
            username=username,
            raw_url=url,
            status="bot_started",
            session=sess,
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
