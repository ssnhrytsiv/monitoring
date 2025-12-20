#!/usr/bin/env python
"""
Rename an existing session file to the account's human name (no re-login).

It opens an already-authorised session, reads your profile (first/last/username),
sanitises it to a safe filename, and renames the .session file accordingly.

Usage:
    python scripts/create_named_session.py --session tg_session_5

Environment:
    API_ID / API_HASH (or TG_API_ID / TG_API_HASH) must be set.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from dotenv import load_dotenv
from telethon import TelegramClient

# For existing sessions, we only read profile and rename; no sign-in.


def get_api() -> tuple[int, str]:
    # Підхоплюємо .env/.env.local так само, як у прод-коді
    load_dotenv()
    load_dotenv(".env.local", override=True)

    api_id = int(
        os.getenv("API_ID")
        or os.getenv("TG_API_ID")
        or "0"
    )
    api_hash = os.getenv("API_HASH") or os.getenv("TG_API_HASH") or ""
    if not api_id or not api_hash:
        print("API_ID/API_HASH must be set via env (API_ID/API_HASH or TG_API_ID/TG_API_HASH).", file=sys.stderr)
        sys.exit(1)
    return api_id, api_hash


def safe_name(text: str) -> str:
    """Convert profile name/username to a filesystem-safe session filename."""
    clean = re.sub(r"[^A-Za-z0-9_]+", "_", text.strip())
    clean = re.sub(r"_+", "_", clean).strip("_")  # звести підрядки "_" та обрізати краї
    return clean or "session"


def normalize_session_arg(arg: str) -> str:
    """Accepts name with/without .session suffix and returns basename without suffix."""
    s = arg.strip()
    if s.endswith(".session"):
        s = s[: -len(".session")]
    return s


async def main(session: str) -> None:
    api_id, api_hash = get_api()
    session = normalize_session_arg(session)
    src = f"{session}.session"
    if not os.path.exists(src):
        print(f"Session file not found: {src}", file=sys.stderr)
        sys.exit(1)

    async with TelegramClient(session, api_id, api_hash) as client:
        if not await client.is_user_authorized():
            print(f"Session {src} is not authorised; login first.", file=sys.stderr)
            sys.exit(1)
        me = await client.get_me()
        account_id = getattr(me, "id", None)
        if not account_id:
            print("Cannot read account id from profile; aborting rename.", file=sys.stderr)
            sys.exit(1)
        filename = f"{safe_name(str(account_id))}.session"

    if filename == os.path.basename(src):
        print(f"Session already named: {filename}")
        return

    dst = os.path.join(os.path.dirname(src), filename)
    if os.path.exists(dst):
        print(f"Target session file already exists: {dst}", file=sys.stderr)
        sys.exit(1)

    os.replace(src, dst)
    journal = f"{src}-journal"
    if os.path.exists(journal):
        os.remove(journal)
    wal = f"{src}-wal"
    if os.path.exists(wal):
        os.remove(wal)

    print(f"Renamed session to: {dst}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Rename existing Telethon session file to human-readable account name.")
    parser.add_argument(
        "--session",
        default=os.getenv("SESSION_NAME", "tg_session"),
        help="Session filename (with or without .session) (default: env SESSION_NAME or tg_session)",
    )
    args = parser.parse_args()
    asyncio.run(main(normalize_session_arg(args.session)))
