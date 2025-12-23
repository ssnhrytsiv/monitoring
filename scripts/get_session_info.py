#!/usr/bin/env python
"""
Print basic info (id/username/name) for an existing, authorised Telethon session.
Does NOT prompt for login; if the session is not authorised, it will just say so.

Usage:
    python scripts/get_session_info.py --session tg_session_5
"""

from __future__ import annotations

import argparse
import asyncio
import os

from dotenv import load_dotenv
from telethon import TelegramClient


def load_api() -> tuple[int, str]:
    load_dotenv()
    load_dotenv(".env.local", override=True)
    api_id = int(os.getenv("API_ID") or os.getenv("TG_API_ID") or "0")
    api_hash = os.getenv("API_HASH") or os.getenv("TG_API_HASH") or ""
    if not api_id or not api_hash:
        raise SystemExit("API_ID/API_HASH must be set in env (.env/.env.local).")
    return api_id, api_hash


async def main(session_name: str) -> None:
    api_id, api_hash = load_api()
    async with TelegramClient(session_name, api_id, api_hash) as client:
        if not await client.is_user_authorized():
            print(f"{session_name}: not authorised (no code requested; login first).")
            return
        me = await client.get_me()
        print(
            f"{session_name}: id={me.id} username=@{me.username} "
            f"name={me.first_name} {me.last_name}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Show account info for an existing session (no login).")
    parser.add_argument(
        "--session",
        default=os.getenv("SESSION_NAME", "tg_session"),
        help="Session filename without .session (default: env SESSION_NAME or tg_session)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.session))
