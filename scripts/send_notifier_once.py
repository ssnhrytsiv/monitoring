#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from app.notificator_bot.config import NOTIFIER_BOT_TOKEN, NOTIFIER_TARGET_IDS
from app.notificator_bot.service import send_notifications


def _parse_command_line_arguments() -> argparse.Namespace:
    command_line_parser = argparse.ArgumentParser(
        description="Send one notifier batch from current unsent watch events.",
    )
    command_line_parser.add_argument(
        "--debounce-seconds",
        type=int,
        default=1,
        help="Debounce seconds before final send.",
    )
    return command_line_parser.parse_args()


async def _send_once(debounce_seconds: int) -> None:
    if not NOTIFIER_BOT_TOKEN:
        raise SystemExit("NOTIFIER_BOT_TOKEN is empty.")
    if not NOTIFIER_TARGET_IDS:
        raise SystemExit("NOTIFIER_TARGET_IDS is empty.")

    bot = Bot(
        token=NOTIFIER_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    try:
        await send_notifications(bot, debounce_sec=max(1, int(debounce_seconds)))
    finally:
        await bot.session.close()


def main() -> None:
    command_line_arguments = _parse_command_line_arguments()
    asyncio.run(_send_once(command_line_arguments.debounce_seconds))
    print("Notifier batch sent.")


if __name__ == "__main__":
    main()
