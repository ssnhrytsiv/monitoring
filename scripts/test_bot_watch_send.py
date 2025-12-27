"""
Utility to send a test message to a bot from a chosen session.

Usage:
  API_ID=... API_HASH=... python -m scripts.test_bot_watch_send --bot t.me/SaleautoMarketbot --session tg_session.session --text "Your message"
  API_ID=... API_HASH=... python -m scripts.test_bot_watch_send --bot @MyBot --session tg_session.session --file ./payload.txt
"""
import argparse
import asyncio
import os
import sys
from typing import Optional

from telethon import TelegramClient

from app.utils.tg_links import extract_bot_username


def _read_text(file_path: Optional[str], text: Optional[str]) -> str:
    if text:
        return text
    if file_path:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    raise SystemExit("Provide --text or --file")


async def main():
    parser = argparse.ArgumentParser(description="Send a message to bot from a session (for bot-watch testing).")
    parser.add_argument("--bot", required=True, help="Bot link/username (t.me/... or @username)")
    parser.add_argument("--session", default=os.getenv("SESSION") or "tg_session.session", help="Session file/name")
    parser.add_argument("--text", help="Message text to send")
    parser.add_argument("--file", dest="file_path", help="Path to file with message content")
    args = parser.parse_args()

    api_id = int(os.getenv("API_ID", "0"))
    api_hash = os.getenv("API_HASH", "")
    if not api_id or not api_hash:
        raise SystemExit("Set API_ID and API_HASH env variables.")

    username = extract_bot_username(args.bot)
    if not username:
        raise SystemExit("Invalid bot username/link.")

    msg_text = _read_text(args.file_path, args.text)
    session_name = args.session

    print(f"[i] Sending from session={session_name} to @{username}")

    async with TelegramClient(session_name, api_id, api_hash) as client:
        await client.send_message(username, msg_text)
        me = await client.get_me()
        print(f"[ok] Sent as {getattr(me, 'username', None) or me.first_name}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
