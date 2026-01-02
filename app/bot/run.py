import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramNetworkError

from app.bot.handlers import router  # центральний router
from app.config import BOT_TOKEN

async def run_bot():
    token = BOT_TOKEN
    if not token:
        raise RuntimeError("BOT_TOKEN env is required")

    log = logging.getLogger("app.bot.run")
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())

    # Підключаємо один кореневий router, який усередині вже містить усі підроутери
    dp.include_router(router)

    while True:
        try:
            await dp.start_polling(bot)
            break
        except TelegramNetworkError as e:
            log.warning("Bot UI polling network error: %s; retrying in 5s", e)
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Bot UI polling crashed")
            raise
