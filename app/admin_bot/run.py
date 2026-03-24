from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramNetworkError

from app.admin_bot.config import ADMIN_BOT_TOKEN
from app.admin_bot.db.session import (
    Base,
    engine,
    migrate_admins_nullable,
    migrate_post_template_media,
    migrate_reply_flags,
)
from app.admin_bot.bot import router


async def run_admin_bot():
    """
    Запуск окремого admin-бота всередині основного процесу.
    Очікує, що logging уже налаштований головним застосунком.
    """
    if not ADMIN_BOT_TOKEN:
        raise RuntimeError("ADMIN_BOT_TOKEN env is required for admin bot")

    log = logging.getLogger("admin_bot.run")
    migrate_admins_nullable()
    Base.metadata.create_all(bind=engine)
    migrate_reply_flags()
    migrate_post_template_media()

    bot = Bot(token=ADMIN_BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    log.info("Admin bot starting polling…")
    while True:
        try:
            await dp.start_polling(bot, handle_signals=False)
            break
        except TelegramNetworkError as e:
            log.warning("Admin bot polling network error: %s; retrying in 5s", e)
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Admin bot polling crashed")
            raise
