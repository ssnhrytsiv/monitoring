"""
Forward a manually sent Telegram message to a bot from a chosen session.

Usage:
  API_ID=... API_HASH=... python -m scripts.test_bot_watch_forward --bot t.me/SaleautoMarketbot --session tg_session.session

Flow:
  - Runs Telethon with the given session.
  - Waits for your next message in "Saved Messages" (or any chat you set via --from-chat).
  - Forwards that message to the target bot and exits.
"""
import argparse
import asyncio
import os
import sys

from telethon import TelegramClient, events
from telethon.tl.types import PeerChannel, PeerChat, PeerUser

from app.utils.tg_links import extract_bot_username


def _resolve_peer(raw: str):
    if raw == "me":
        return "me"
    if raw.isdigit():
        val = int(raw)
        if val > 0:
            return PeerUser(val)
        if val < 0:
            # Telethon uses negative ids for chats/channels in Peer* wrappers; accept as-is
            return PeerChannel(-val)
    return raw


async def main():
    parser = argparse.ArgumentParser(description="Forward manually typed message to a bot for bot-watch testing.")
    parser.add_argument("--bot", required=True, help="Bot link/username (t.me/... or @username)")
    parser.add_argument("--session", default=os.getenv("SESSION") or "tg_session.session", help="Session file/name")
    parser.add_argument(
        "--from-chat",
        default="me",
        help='Source chat to listen for a message. Default: "me" (Saved Messages). Can be @username or numeric id.',
    )
    args = parser.parse_args()

    api_id = int(os.getenv("API_ID", "0"))
    api_hash = os.getenv("API_HASH", "")
    if not api_id or not api_hash:
        raise SystemExit("Set API_ID and API_HASH env variables.")

    username = extract_bot_username(args.bot)
    if not username:
        raise SystemExit("Invalid bot username/link.")

    src = _resolve_peer(args.from_chat)
    session_name = args.session

    print(f"[i] Waiting for your next message in '{args.from_chat}' to forward to @{username}")

    client = TelegramClient(session_name, api_id, api_hash)

    @client.on(events.NewMessage(chats=src))
    async def handler(ev: events.NewMessage.Event):
        try:
            await client.forward_messages(username, ev.message)
            me = await client.get_me()
            print(f"[ok] Forwarded from {args.from_chat} as {getattr(me, 'username', None) or me.first_name}")
        finally:
            await client.disconnect()

    async with client:
        await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
