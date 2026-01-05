from __future__ import annotations

import asyncio
import logging
from aiogram.exceptions import TelegramRetryAfter, TelegramServerError

log = logging.getLogger("admin_bot.subscription_report")


async def answer_with_retry(msg, text: str, attempts: int = 3, **kwargs):
    """
    Send a message with basic handling of Telegram flood/server errors.
    """
    chat_id = getattr(getattr(msg, "chat", None), "id", None)
    for attempt in range(attempts):
        try:
            return await msg.answer(text, **kwargs)
        except TelegramRetryAfter as e:
            delay = max(1, int(getattr(e, "retry_after", 0)) or 1)
            log.warning(
                "subscription.answer flood_wait chat_id=%s delay=%ss attempt=%s/%s",
                chat_id,
                delay,
                attempt + 1,
                attempts,
            )
            if attempt + 1 >= attempts:
                log.error("subscription.answer aborted after flood_wait chat_id=%s", chat_id)
                return None
            await asyncio.sleep(delay + 0.5)
        except TelegramServerError as e:
            if attempt + 1 >= attempts:
                raise
            log.warning("subscription.answer server_error chat_id=%s err=%s", chat_id, e)
            await asyncio.sleep(1)
    return None


__all__ = ["answer_with_retry"]
