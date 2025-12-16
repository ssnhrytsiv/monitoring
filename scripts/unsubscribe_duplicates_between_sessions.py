import os
import asyncio
from typing import Set, Dict

from telethon import TelegramClient
from telethon.tl.types import Channel
from telethon.errors import RPCError

# === НАЛАШТУВАННЯ ===

BASE_DIR = "/Users/nazarhrytsiv/Downloads/tg_monitor_package_v13_full"

API_ID = int(os.getenv("TG_API_ID", "23138928"))        # заміни або вистав через env
API_HASH = os.getenv("TG_API_HASH", "969a05668d0fd9bff53937329f2c0dd3")  # заміни або вистав через env

# Перша (primary) сесія – з неї НІЧОГО не чіпаємо
PRIMARY_SESSION = "tg_session_4"

# Друга сесія, з якої будемо відписуватись, якщо знайдемо дубль підписок
SECONDARY_SESSION = "tg_session_5"

# Затримка між leave-запитами, сек
LEAVE_DELAY_SEC = 6.0


def get_session_path(session_name: str) -> str:
    return os.path.join(BASE_DIR, f"{session_name}.session")


async def collect_channels(session_name: str) -> Dict[int, str]:
    """
    Повертає мапу: channel_id -> title для заданої Telegram-сесії.
    Враховуються тільки обʼєкти типу Channel (канали/супергрупи).
    """
    session_path = get_session_path(session_name)
    print(f"\n[{session_name}] session_path={session_path}")

    client = TelegramClient(session_path, API_ID, API_HASH)
    channels: Dict[int, str] = {}

    try:
        await client.start()
    except Exception as e:
        print(f"[{session_name}] НЕ вдалося стартувати клієнт: {e}")
        return channels

    async with client:
        async for dialog in client.iter_dialogs():
            ent = dialog.entity
            if isinstance(ent, Channel):
                channels[ent.id] = getattr(ent, "title", "") or dialog.name

    print(f"[{session_name}] знайдено каналів/супергруп: {len(channels)}")
    return channels


async def leave_channels(session_name: str, channel_ids: Set[int]):
    """
    Виходить (delete_dialog) зі списку channel_ids для заданої сесії.
    """
    if not channel_ids:
        print(f"\n[{session_name}] Немає каналів для відписки.")
        return

    session_path = get_session_path(session_name)
    print(
        f"\n[{session_name}] відписуємось від {len(channel_ids)} каналів, "
        f"session_path={session_path}, LEAVE_DELAY_SEC={LEAVE_DELAY_SEC}"
    )

    client = TelegramClient(session_path, API_ID, API_HASH)

    try:
        await client.start()
    except Exception as e:
        print(f"[{session_name}] НЕ вдалося стартувати клієнт: {e}")
        return

    async with client:
        for cid in sorted(channel_ids):
            try:
                await client.delete_dialog(cid)
                print(f"[{session_name}] left channel_id={cid}")
                await asyncio.sleep(LEAVE_DELAY_SEC)
            except RPCError as e:
                print(f"[{session_name}] RPCError на channel_id={cid}: {e}")
            except Exception as e:
                print(f"[{session_name}] unexpected error на channel_id={cid}: {e}")


async def main():
    print(f"BASE_DIR = {BASE_DIR}")
    print(f"PRIMARY_SESSION = {PRIMARY_SESSION}")
    print(f"SECONDARY_SESSION = {SECONDARY_SESSION}")
    print(f"LEAVE_DELAY_SEC = {LEAVE_DELAY_SEC}")

    # 1. Збираємо канали для обох сесій
    primary_channels = await collect_channels(PRIMARY_SESSION)
    secondary_channels = await collect_channels(SECONDARY_SESSION)

    if not primary_channels:
        print("\n❌ У primary-сесії не знайдено каналів або не вдалося підʼєднатись.")
        return
    if not secondary_channels:
        print("\n❌ У secondary-сесії не знайдено каналів або не вдалося підʼєднатись.")
        return

    # 2. Знаходимо перетин за channel_id
    primary_ids = set(primary_channels.keys())
    secondary_ids = set(secondary_channels.keys())

    common_ids = primary_ids & secondary_ids

    print(f"\nУ primary:   {len(primary_ids)} каналів")
    print(f"У secondary: {len(secondary_ids)} каналів")
    print(f"Перетин (спільні підписки): {len(common_ids)} каналів")

    if not common_ids:
        print("\nСпільних підписок немає – нічого відписувати.")
        return

    # Трохи роздрукуємо, що саме перетинається (до 30 штук, щоб не засмічувати лог)
    print("\nПриклади спільних каналів (до 30):")
    for cid in list(common_ids)[:30]:
        title1 = primary_channels.get(cid, "")
        title2 = secondary_channels.get(cid, "")
        title = title1 or title2 or ""
        print(f"  channel_id={cid} title='{title}'")

    # 3. Питаємо підтвердження
    print(
        f"\nПЛАН: відписати сесію '{SECONDARY_SESSION}' від {len(common_ids)} "
        f"каналів, які вже є в '{PRIMARY_SESSION}'."
    )
    confirm = input("Щоб ПРОДОВЖИТИ і реально вийти з каналів, набери 'YES': ")
    if confirm != "YES":
        print("Скасовано користувачем.")
        return

    # 4. Відписуємось від цих каналів для SECONDARY_SESSION
    await leave_channels(SECONDARY_SESSION, common_ids)

    print("\nГотово. Перетин підписок між сесіями оброблено.")


if __name__ == "__main__":
    asyncio.run(main())