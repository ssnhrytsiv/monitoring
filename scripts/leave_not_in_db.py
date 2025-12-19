"""
Вихід з усіх каналів/супергруп, яких немає в таблиці `channels` БД.

Env:
  DB_PATH        — шлях до post_watchdog.sqlite3 (def. post_watchdog.sqlite3)
  TG_API_ID      — Telegram api_id (обов'язково)
  TG_API_HASH    — Telegram api_hash (обов'язково)
  SESSION_NAME   — ім'я сесії без .session (def. tg_session)
  LEAVE_DELAY_SEC — пауза між leave-запитами (def. 1.0)
"""

import os
import asyncio
import sqlite3
from telethon import TelegramClient
from telethon.tl.types import Channel

DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")
SESSION_NAME = os.getenv("SESSION_NAME", "tg_session")
LEAVE_DELAY = float(os.getenv("LEAVE_DELAY_SEC", "1.0"))


def load_known_channel_ids_for_session(account: str) -> set[int]:
    """
    Повертає множину channel_id, які ми вважаємо «відомими»:
      - усі id з таблиці channels;
      - усі id з membership для заданого account.
    Це зменшує випадки, коли канал є в membership, але ще не в channels.
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    ids: set[int] = set()
    try:
        cur.execute("SELECT id FROM channels")
        ids.update(int(r[0]) for r in cur.fetchall() if r and r[0] is not None)
    except Exception:
        pass
    try:
        cur.execute("SELECT channel_id FROM membership WHERE account=?", (account,))
        ids.update(int(r[0]) for r in cur.fetchall() if r and r[0] is not None)
    except Exception:
        pass
    con.close()
    return ids


async def main():
    if not API_ID or not API_HASH:
        raise SystemExit("Set TG_API_ID / TG_API_HASH env vars first")

    used = load_known_channel_ids_for_session(SESSION_NAME)
    print(f"DB: {DB_PATH}, known channels for {SESSION_NAME}={len(used)}")

    session_path = f"{SESSION_NAME}.session"
    print(f"Session: {session_path}")

    to_leave: list[tuple[int, str]] = []
    async with TelegramClient(session_path, API_ID, API_HASH) as client:
        async for dlg in client.iter_dialogs():
            ent = dlg.entity
            if isinstance(ent, Channel):
                cid = int(getattr(ent, "id", 0) or 0)
                if cid and cid not in used:
                    title = getattr(ent, "title", "") or ""
                    to_leave.append((cid, title))

        print(f"Found {len(to_leave)} channels/supergroups not in DB:")
        for cid, title in to_leave:
            t = f" — {title}" if title else ""
            print(f"  {cid}{t}")

        if not to_leave:
            print("Nothing to do.")
            return

        confirm = input("Type YES to leave these channels: ").strip()
        if confirm != "YES":
            print("Cancelled by user.")
            return

        print("Proceeding to leave...")
        for cid, title in to_leave:
            try:
                await client.delete_dialog(cid)  # для каналів/чатів це leave
                print(f"Left channel_id={cid} ({title or 'no title'})")
                await asyncio.sleep(LEAVE_DELAY)
            except Exception as e:
                print(f"Failed to leave channel_id={cid}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
