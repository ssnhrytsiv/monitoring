from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app.notificator_bot.config import NOTIFIER_BOT_TOKEN, NOTIFIER_POLL_INTERVAL_SEC, NOTIFIER_TARGET_IDS
from app.notificator_bot.service import send_notifications
from app.notificator_bot.models import ensure_tables


log = logging.getLogger("notificator.run")


async def _worker(bot: Bot):
    ensure_tables()
    while True:
        try:
            await send_notifications(bot, debounce_sec=60)
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

    asyncio.create_task(_worker(bot), name="notifier_worker")
    log.info("Notifier bot started (interval=%ss)", NOTIFIER_POLL_INTERVAL_SEC)
    await dp.start_polling(bot)
