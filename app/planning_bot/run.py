import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage

from app.planning_bot.config import PLANNING_BOT_TOKEN
from app.planning_bot.handlers import router


async def start_planning_bot():
    if not PLANNING_BOT_TOKEN:
        raise RuntimeError("PLANNING_BOT_TOKEN env is required for planning_bot")

    log = logging.getLogger("app.planning_bot.run")
    bot = Bot(token=PLANNING_BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    while True:
        try:
            await dp.start_polling(bot, handle_signals=False)
            break
        except TelegramUnauthorizedError:
            log.error("planning_bot unauthorized: invalid or revoked PLANNING_BOT_TOKEN; bot stopped")
            return
        except TelegramNetworkError as e:
            log.warning("planning_bot polling network error: %s; retrying in 5s", e)
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("planning_bot polling crashed")
            raise
