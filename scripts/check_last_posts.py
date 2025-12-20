import asyncio
import argparse
import os
from typing import Iterable

from telethon import TelegramClient
from telethon.tl.types import PeerChannel
from dotenv import load_dotenv

# Підтягнути .env / .env.local
load_dotenv()
load_dotenv(".env.local", override=True)

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")


async def fetch_last_post(client: TelegramClient, ident: str | int):
    try:
        entity = await client.get_entity(ident)
    except Exception:
        # Якщо це числовий channel_id без access_hash — пробуємо через PeerChannel
        try:
            entity = await client.get_entity(PeerChannel(int(ident)))
        except Exception as e:
            return {"id": ident, "error": f"get_entity failed: {e}"}

    try:
        msg = (await client.get_messages(entity, limit=1))[0]
    except Exception as e:
        return {"id": ident, "title": getattr(entity, "title", None), "error": f"get_messages failed: {e}"}

    return {
        "id": ident,
        "title": getattr(entity, "title", None),
        "username": getattr(entity, "username", None),
        "msg_id": msg.id,
        "date": msg.date.isoformat() if msg.date else None,
        "views": getattr(msg, "views", None),
        "forwards": getattr(msg, "forwards", None),
    }


async def main(session: str, channels: Iterable[str | int]):
    client = TelegramClient(session, API_ID, API_HASH)
    await client.start()
    results = []
    for ch in channels:
        res = await fetch_last_post(client, ch)
        results.append(res)
    await client.disconnect()

    for r in results:
        if r.get("error"):
            print(f"{r['id']}: ERROR {r['error']}")
        else:
            uname = f" (@{r['username']})" if r.get("username") else ""
            print(
                f"{r['id']}: {r.get('title')}{uname} "
                f"last_msg={r.get('msg_id')} date={r.get('date')} "
                f"views={r.get('views')} forwards={r.get('forwards')}"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Показати останній пост і перегляди для заданих каналів."
    )
    parser.add_argument(
        "--session",
        default=os.getenv("SESSION_NAME", "tg_session"),
        help="Назва .session файлу (без розширення). За замовчуванням SESSION_NAME або tg_session.",
    )
    parser.add_argument(
        "channels",
        nargs="+",
        help="Список каналів: username/посилання або числовий channel_id (можна 1636596284).",
    )
    args = parser.parse_args()

    asyncio.run(main(args.session, args.channels))
