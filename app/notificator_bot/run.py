from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties

from app.notificator_bot.config import NOTIFIER_BOT_TOKEN, NOTIFIER_POLL_INTERVAL_SEC, NOTIFIER_TARGET_IDS
from app.notificator_bot.service import send_notifications
from app.notificator_bot.models import ensure_tables
from app.notificator_bot.handlers import (
    NOTIFICATION_MANAGE_CALLBACK_PREFIX,
    NOTIFICATION_PAGE_CALLBACK_PREFIX,
    NOTIFICATION_PAGE_NOOP_CALLBACK_DATA,
    NOTIFICATION_PREVIEW_CALLBACK_PREFIX,
    inline_handler,
    notification_manage_handler,
    notification_page_noop_handler,
    notification_page_navigation_handler,
    notification_preview_handler,
)


log = logging.getLogger("notificator.run")


async def _worker(bot: Bot):
    ensure_tables()
    while True:
        try:
            await send_notifications(bot, debounce_sec=30)
        except asyncio.CancelledError:
            log.info("notifier worker cancelled")
            raise
        except Exception:
            log.exception("notifier tick failed")
        await asyncio.sleep(max(1, NOTIFIER_POLL_INTERVAL_SEC))


async def start_notificator_bot():
    if not NOTIFIER_BOT_TOKEN:
        log.error("NOTIFIER_BOT_TOKEN is not set; notifier will not start")
        return

    log.info("Notifier config: targets=%s interval=%s", NOTIFIER_TARGET_IDS, NOTIFIER_POLL_INTERVAL_SEC)

    bot = Bot(token=NOTIFIER_BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.inline_query.register(inline_handler)
    dp.callback_query.register(
        notification_page_navigation_handler,
        F.data.startswith(f"{NOTIFICATION_PAGE_CALLBACK_PREFIX}:"),
    )
    dp.callback_query.register(
        notification_page_noop_handler,
        F.data == NOTIFICATION_PAGE_NOOP_CALLBACK_DATA,
    )
    dp.callback_query.register(
        notification_manage_handler,
        F.data.startswith(f"{NOTIFICATION_MANAGE_CALLBACK_PREFIX}:"),
    )
    dp.callback_query.register(
        notification_preview_handler,
        F.data.startswith(f"{NOTIFICATION_PREVIEW_CALLBACK_PREFIX}:"),
    )

    worker_task = asyncio.create_task(_worker(bot), name="notifier_worker")
    log.info("Notifier bot started (interval=%ss)", NOTIFIER_POLL_INTERVAL_SEC)
    try:
        await dp.start_polling(bot, handle_signals=False)
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
