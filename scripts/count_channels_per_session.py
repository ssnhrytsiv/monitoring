import asyncio
import os
from typing import Set, Dict

from telethon import TelegramClient
from telethon.tl.types import Channel

# Налаштуй під себе
BASE_DIR = "/Users/nazarhrytsiv/Downloads/tg_monitor_package_v13_full"

API_ID = int(os.getenv("TG_API_ID", "123456"))        # заміни на свій або вистав через env
API_HASH = os.getenv("TG_API_HASH", "your_api_hash")  # заміни на свій або вистав через env

# Імена session-файлів БЕЗ .session
SESSIONS = [
    "tg_session",
    "tg_session_2",
    "tg_session_3",
    "tg_session_4",
    "tg_session_5",
]


async def collect_for_session(session_name: str) -> Set[int]:
    session_path = os.path.join(BASE_DIR, f"{session_name}.session")
    print(f"\n[{session_name}] session_path={session_path}")

    client = TelegramClient(session_path, API_ID, API_HASH)

    try:
        await client.start()
    except Exception as e:
        print(f"[{session_name}] НЕ вдалося стартувати клієнт: {e}")
        return set()

    channels: Set[int] = set()
    async with client:
        async for dialog in client.iter_dialogs():
            ent = dialog.entity
            if isinstance(ent, Channel):
                channels.add(ent.id)

    print(f"[{session_name}] каналів/супергруп: {len(channels)}")
    return channels


async def main():
    totals: Dict[str, int] = {}

    for sess in SESSIONS:
        chs = await collect_for_session(sess)
        totals[sess] = len(chs)

    print("\nПідсумок по сесіях:")
    for sess, cnt in totals.items():
        print(f"  {sess}: {cnt} каналів/супергруп")

if __name__ == "__main__":
    asyncio.run(main())
