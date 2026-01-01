"""
Простий бот-ретранслятор: усе, що прилітає боту, копіює у вказаний чат.

Запуск:
  FORWARD_BOT_TOKEN=... FORWARD_TARGET_CHAT_ID=... python -m scripts.forward_bot
"""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.client.default import DefaultBotProperties

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("forward_bot")

# Токен і цільовий чат беремо з env, щоб не тримати секрети в коді
BOT_TOKEN = os.getenv("FORWARD_BOT_TOKEN")
TARGET_CHAT_ID = int(os.getenv("FORWARD_TARGET_CHAT_ID", "8497144108"))


async def on_any_message(message: types.Message):
    try:
        await message.copy_to(chat_id=TARGET_CHAT_ID, allow_sending_without_reply=True, parse_mode=ParseMode.HTML)
        log.info("Forwarded msg %s from %s to %s", message.message_id, message.from_user.id if message.from_user else None, TARGET_CHAT_ID)
    except TelegramAPIError as e:
        log.error("Failed to forward msg %s: %s", message.message_id, e)


async def start_forward_bot():
    if not BOT_TOKEN:
        log.error("Env FORWARD_BOT_TOKEN is not set; cannot start forward bot")
        return

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.register(on_any_message)

    log.info("Relay bot started, forwarding to chat_id=%s", TARGET_CHAT_ID)
    await dp.start_polling(bot)


def main():
    asyncio.run(start_forward_bot())


if __name__ == "__main__":
    main()
