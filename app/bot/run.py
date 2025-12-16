import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import router  # центральний router
from app.bot.notifier import notifier_loop


async def run_bot():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN env is required")

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())

    # Підключаємо один кореневий router, який усередині вже містить усі підроутери
    dp.include_router(router)

    asyncio.create_task(notifier_loop(bot), name="bot_notifier")

    await dp.start_polling(bot)