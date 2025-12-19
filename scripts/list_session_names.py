# scripts/list_session_names.py
import os
import asyncio
from telethon import TelegramClient

API_ID = int(os.getenv("TG_API_ID", "23138928"))
API_HASH = os.getenv("TG_API_HASH", "969a05668d0fd9bff53937329f2c0dd3")

SESSIONS = [
    "tg_session",
    "tg_session_2",
    "tg_session_3",
    "tg_session_4",
    "tg_session_5",
]

async def check_session(sess_name: str):
    sess_path = f"{sess_name}.session"
    try:
        async with TelegramClient(sess_path, API_ID, API_HASH) as client:
            me = await client.get_me()
            fn = me.first_name or ""
            ln = me.last_name or ""
            uname = me.username or ""
            print(f"{sess_name}: {fn} {ln}".strip(), f"(username: @{uname})" if uname else "")
    except Exception as e:
        print(f"{sess_name}: FAILED ({e})")

async def main():
    for s in SESSIONS:
        await check_session(s)

if __name__ == "__main__":
    asyncio.run(main())
