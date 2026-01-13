import logging
from typing import Tuple, Optional

from telethon import errors
from telethon.tl.functions.contacts import UnblockRequest

from app.utils.throttle import throttle_bot
from app.utils.link_parser import extract_bot_username
from app.DAL import SessionLocal
from app.DAL import bot_links_operations as blo
from app.services.account_pool import session_name

log = logging.getLogger("subscription.subscription_for_bot")


def _upsert_bot_link(**kwargs) -> None:
    db = SessionLocal()
    try:
        blo.upsert_bot_link(db, **kwargs)
    finally:
        db.close()


async def ensure_bot_started(
    client,
    url: str,
    *,
    owner_display: Optional[str] = None,
    owner_username: Optional[str] = None,
    batch_id: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
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
        _upsert_bot_link(
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
        _upsert_bot_link(
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
        _upsert_bot_link(
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
        _upsert_bot_link(
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


__all__ = ["ensure_bot_started"]
