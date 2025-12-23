#!/usr/bin/env python
"""
Login to Telegram with provided API_ID/API_HASH and save the session file
named after the account id (e.g. 123456789.session).

Usage:
    python scripts/create_session_by_id.py --session my_temp_name
    # after login, the file will be renamed to <account_id>.session

Environment:
    API_ID / API_HASH (or TG_API_ID / TG_API_HASH) must be set
    .env/.env.local are loaded automatically if present.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient


def load_env() -> tuple[int, str]:
    load_dotenv()
    load_dotenv(".env.local", override=True)
    api_id = int(os.getenv("API_ID") or os.getenv("TG_API_ID") or "0")
    api_hash = os.getenv("API_HASH") or os.getenv("TG_API_HASH") or ""
    if not api_id or not api_hash:
        print("API_ID/API_HASH must be set via env (API_ID/API_HASH or TG_API_ID/TG_API_HASH).", file=sys.stderr)
        sys.exit(1)
    return api_id, api_hash


def normalize_session(name: str) -> str:
    s = name.strip()
    if s.endswith(".session"):
        s = s[: -len(".session")]
    # only allow safe chars
    s = re.sub(r"[^A-Za-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_") or "session"
    return s


async def main(session_name: str) -> None:
    api_id, api_hash = load_env()
    sess = normalize_session(session_name)
    src = f"{sess}.session"

    # Логін (Telethon сам спитає код)
    async with TelegramClient(sess, api_id, api_hash) as client:
        me = await client.get_me()
        account_id = getattr(me, "id", None)
        if not account_id:
            print("Cannot obtain account id after login.", file=sys.stderr)
            sys.exit(1)
        target = Path(f"{account_id}.session")

    # Після виходу файл не зайнятий — можна перейменувати
    src_path = Path(src)
    if not src_path.exists():
        print(f"Session file not found after login: {src}", file=sys.stderr)
        sys.exit(1)
    if target.exists():
        print(f"Target session file already exists: {target}", file=sys.stderr)
        sys.exit(1)

    src_path.replace(target)
    for suffix in ("-journal", "-wal"):
        j = Path(src + suffix)
        if j.exists():
            try:
                j.unlink()
            except Exception:
                pass

    print(f"Saved session as: {target.name}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Create a Telethon session and name it after account id.")
    parser.add_argument(
        "--session",
        default=os.getenv("SESSION_NAME", "tg_session"),
        help="Temporary session filename (with/without .session); will be renamed to <account_id>.session after login.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.session))
