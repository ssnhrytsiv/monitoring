# app/services/monitor_links_bridge.py
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional

from aiogram import Bot

log = logging.getLogger("monitor_links_bridge")

# control_msg_id -> {"user_chat_id": int, "bot_msg_id": int, "active": bool}
_BATCHES: Dict[int, Dict[str, int]] = {}

# user_chat_id -> bool (чи є зараз активний батч)
_USER_LOCKS: Dict[int, bool] = {}

_BOT: Optional[Bot] = None


async def _ensure_bot() -> Optional[Bot]:
    """
    Лінивий створювач Bot за BOT_TOKEN.
    Викликається з update_progress, щоб не плодити ботів.
    """
    global _BOT
    if _BOT is not None:
        return _BOT

    import os

    token = os.getenv("BOT_TOKEN")
    if not token:
        log.error("monitor_links_bridge: BOT_TOKEN is not set in env; cannot mirror progress to bot")
        return None

    try:
        _BOT = Bot(token=token)
        log.info("monitor_links_bridge: Bot instance created")
    except Exception as e:
        log.exception("monitor_links_bridge: failed to create Bot: %r", e)
        _BOT = None

    return _BOT


def register_batch(control_msg_id: int, user_chat_id: int, bot_msg_id: int) -> None:
    """
    Реєструємо звʼязку:
      - повідомлення в CONTROL чаті (control_msg_id),
      - повідомлення в боті (bot_msg_id),
      - користувача (user_chat_id).

    Викликається з bot-хендлера, коли:
      1) ми переслали повідомлення з посиланнями в CONTROL чат,
      2) відправили користувачу статус "почалась обробка".
    """
    try:
        control_msg_id = int(control_msg_id)
        user_chat_id = int(user_chat_id)
        bot_msg_id = int(bot_msg_id)
    except Exception:
        log.error(
            "monitor_links_bridge.register_batch: invalid ids control=%r user=%r bot=%r",
            control_msg_id,
            user_chat_id,
            bot_msg_id,
        )
        return

    _BATCHES[control_msg_id] = {
        "user_chat_id": user_chat_id,
        "bot_msg_id": bot_msg_id,
        "active": True,
    }
    _USER_LOCKS[user_chat_id] = True

    log.info(
        "monitor_links_bridge.register_batch: registered batch control_msg_id=%d "
        "user_chat_id=%d bot_msg_id=%d",
        control_msg_id,
        user_chat_id,
        bot_msg_id,
    )


def is_user_locked(user_chat_id: int) -> bool:
    """
    Повертає True, якщо у цього юзера вже є активний батч (йде підписка).
    Використовуємо в bot-хендлері, щоб не запускати другий пакет.
    """
    try:
        user_chat_id = int(user_chat_id)
    except Exception:
        return False

    locked = bool(_USER_LOCKS.get(user_chat_id))
    log.debug(
        "monitor_links_bridge.is_user_locked: user_chat_id=%d locked=%s",
        user_chat_id,
        locked,
    )
    return locked


async def update_progress(control_msg_id: int, text: str) -> None:
    """
    Дзеркалить прогрес із CONTROL повідомлення в бот-повідомлення.
    Викликається з join_scheduler / monitor_links, коли вони оновлюють статус у CONTROL чаті.
    """
    try:
        control_msg_id = int(control_msg_id)
    except Exception:
        log.error("monitor_links_bridge.update_progress: invalid control_msg_id=%r", control_msg_id)
        return

    batch = _BATCHES.get(control_msg_id)
    if not batch:
        log.debug(
            "monitor_links_bridge.update_progress: no batch found for control_msg_id=%d",
            control_msg_id,
        )
        return

    user_chat_id = batch.get("user_chat_id")
    bot_msg_id = batch.get("bot_msg_id")

    if not user_chat_id or not bot_msg_id:
        log.error(
            "monitor_links_bridge.update_progress: broken batch for control_msg_id=%d: %r",
            control_msg_id,
            batch,
        )
        return

    bot = await _ensure_bot()
    if not bot:
        log.error(
            "monitor_links_bridge.update_progress: Bot is not available; "
            "cannot mirror progress for control_msg_id=%d",
            control_msg_id,
        )
        return

    # невелика затримка, щоб не спамити edit'ами
    await asyncio.sleep(0.3)

    try:
        await bot.edit_message_text(
            chat_id=user_chat_id,
            message_id=bot_msg_id,
            text=text,
            parse_mode="HTML",
        )
        log.debug(
            "monitor_links_bridge.update_progress: mirrored to bot user_chat_id=%d bot_msg_id=%d",
            user_chat_id,
            bot_msg_id,
        )
    except Exception as e:
        log.exception(
            "monitor_links_bridge.update_progress: edit_message_text failed for "
            "user_chat_id=%d bot_msg_id=%d: %r",
            user_chat_id,
            bot_msg_id,
            e,
        )


def finish_batch(control_msg_id: int) -> None:
    """
    Позначає батч як завершений:
      - прибирає active,
      - знімає lock з юзера.
    Викликається з join_scheduler, коли всі канали оброблені.
    """
    try:
        control_msg_id = int(control_msg_id)
    except Exception:
        log.error("monitor_links_bridge.finish_batch: invalid control_msg_id=%r", control_msg_id)
        return

    batch = _BATCHES.pop(control_msg_id, None)
    if not batch:
        log.debug("monitor_links_bridge.finish_batch: no batch for control_msg_id=%d", control_msg_id)
        return

    user_chat_id = batch.get("user_chat_id")
    if user_chat_id is not None:
        _USER_LOCKS.pop(user_chat_id, None)

    log.info(
        "monitor_links_bridge.finish_batch: finished batch control_msg_id=%d user_chat_id=%r",
        control_msg_id,
        user_chat_id,
    )