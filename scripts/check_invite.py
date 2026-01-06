#!/usr/bin/env python3
"""
Quick helper: check an invite hash using an existing session without re-login.

Usage:
  API_ID=... API_HASH=... SESSION_NAME=tg_session.session python scripts/check_invite.py <invite-url-or-hash>
"""
import asyncio
import os
import sys
from telethon import TelegramClient
from telethon.tl.functions.messages import CheckChatInviteRequest


def _extract_hash(val: str) -> str:
    s = (val or "").strip()
    s = s.replace("\u200b", "").replace("\u200e", "").replace("\u200f", "")
    for prefix in ("https://t.me/+", "http://t.me/+", "t.me/+", "https://t.me/joinchat/", "http://t.me/joinchat/", "t.me/joinchat/"):
        if s.startswith(prefix):
            return s[len(prefix) :].strip()
    return s.lstrip("+")


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/check_invite.py <invite-url-or-hash>")
        sys.exit(1)

    invite_hash = _extract_hash(sys.argv[1])
    api_id = int(os.getenv("API_ID", "0") or "0")
    api_hash = os.getenv("API_HASH", "")
    session_name = os.getenv("SESSION_NAME", "tg_session.session")

    if not api_id or not api_hash:
        print("API_ID/API_HASH must be set via environment.")
        sys.exit(1)

    async with TelegramClient(session_name, api_id, api_hash) as client:
        res = await client(CheckChatInviteRequest(invite_hash))
        print(res.stringify())


if __name__ == "__main__":
    asyncio.run(main())
