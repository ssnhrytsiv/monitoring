from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from admin_bot.config import ADMIN_BOT_TOKEN


async def main() -> None:
    if not ADMIN_BOT_TOKEN:
        raise RuntimeError("ADMIN_BOT_TOKEN env is required for admin bot")

    bot = Bot(token=ADMIN_BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())

    # TODO: додати хендлери CRUD адмінів/каналів

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
