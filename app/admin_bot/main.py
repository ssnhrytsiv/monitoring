from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from app.admin_bot.config import ADMIN_BOT_TOKEN
from app.db.session import Base, engine
from app.admin_bot.bot import router
import logging


async def main() -> None:
    if not ADMIN_BOT_TOKEN:
        raise RuntimeError("ADMIN_BOT_TOKEN env is required for admin bot")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    log = logging.getLogger("admin_bot.main")

    # Створюємо нові таблиці admin-бота, не чіпаючи існуючі
    Base.metadata.create_all(bind=engine)

    bot = Bot(token=ADMIN_BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(router)

    log.info("Admin bot starting polling…")
    await dp.start_polling(bot)
    log.info("Admin bot polling finished")


if __name__ == "__main__":
    asyncio.run(main())
