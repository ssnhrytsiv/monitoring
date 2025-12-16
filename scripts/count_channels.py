from telethon import TelegramClient
from telethon.tl.types import Channel
import os

# Використовуємо ті ж креденшали, що й у проекті
API_ID = int(os.getenv("TG_API_ID", "23138928"))          # заміни 123456 на свій
API_HASH = os.getenv("TG_API_HASH", "969a05668d0fd9bff53937329f2c0dd3")    # заміни на свій

# Ім'я сесії, яку хочеш перевірити
# Орієнтуйся на файли tg_session.session, tg_session_2.session і т.п. у корені
SESSION = "tg_session_4"   # за потреби зміни на tg_session_2, tg_session_3 тощо


async def main():
    channels = 0
    supergroups = 0

    async for dialog in client.iter_dialogs():
        ent = dialog.entity
        if isinstance(ent, Channel):
            if getattr(ent, "megagroup", False):
                supergroups += 1
            else:
                channels += 1

    total = channels + supergroups
    print(f"Канали: {channels}")
    print(f"Супергрупи: {supergroups}")
    print(f"Разом каналів+супергруп: {total}")


if __name__ == "__main__":
    client = TelegramClient(SESSION, API_ID, API_HASH)
    client.start()
    with client:
        client.loop.run_until_complete(main())