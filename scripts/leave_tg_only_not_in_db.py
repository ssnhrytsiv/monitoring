#!/usr/bin/env python3
"""
Відписує сесії від каналів/супергруп, які є в підписках Telegram,
але відсутні в БД (membership зі статусами joined/already/requested).

Особливості:
  - за замовчуванням пропускає tg_session_3 (його не чіпаємо);
  - затримка 3 секунди між leave;
  - можна запустити у dry-run режимі (--dry-run), тоді лише виведе список.

Необхідні змінні оточення:
  API_ID, API_HASH, DB_PATH (def. post_watchdog.sqlite3), ACCOUNTS/SESSION_NAME.
"""
import argparse
import asyncio
import glob
import os
import sqlite3
from typing import List, Set, Tuple

from telethon import TelegramClient
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.types import Channel

# Статуси, які вважаємо "є в БД"
FINAL = ("joined", "already", "requested")


def load_env() -> None:
    """Підвантажує .env без залежностей, якщо є."""
    try:
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        pass


def collect_sessions(skip: Set[str]) -> List[str]:
    """Збирає імена сесій з ACCOUNTS/SESSION_NAME і .session файлів."""
    sessions: Set[str] = set()
    acc_env = os.getenv("ACCOUNTS", "")
    for part in acc_env.split(","):
        part = part.strip()
        if part:
            sessions.add(part)
    main_sess = os.getenv("SESSION_NAME") or os.getenv("SESSION")
    if main_sess:
        sessions.add(main_sess)
    for path in glob.glob("*.session"):
        sessions.add(os.path.basename(path).replace(".session", ""))
    return sorted(s for s in sessions if s and s not in skip)


def db_channels_for(account: str, conn: sqlite3.Connection) -> Set[int]:
    cur = conn.cursor()
    cur.execute(
        f"SELECT channel_id FROM membership WHERE account=? AND status IN ({','.join('?'*len(FINAL))})",
        (account, *FINAL),
    )
    return {int(r[0]) for r in cur.fetchall() if r and r[0] is not None}


async def tg_channels_full(sess: str, api_id: int, api_hash: str) -> List[Tuple[int, str, str, object]]:
    """Повертає список (cid, username, title, entity) для каналів/супергруп сесії."""
    out: List[Tuple[int, str, str, object]] = []
    client = TelegramClient(sess, api_id, api_hash)
    await client.start()
    async for dlg in client.iter_dialogs():
        ent = dlg.entity
        if isinstance(ent, Channel):
            cid = int(getattr(ent, "id", 0) or 0)
            uname = (getattr(ent, "username", None) or "").lower()
            title = getattr(ent, "title", None) or ""
            out.append((cid, uname, title, ent))
    await client.disconnect()
    return out


async def leave_extras_for_session(
    sess: str,
    api_id: int,
    api_hash: str,
    db_ids: Set[int],
    delay_sec: float,
    dry_run: bool,
) -> List[int]:
    """
    Відписує від каналів, яких немає в db_ids.
    Повертає список channel_id, від яких відписались/мали відписатись.
    """
    left: List[int] = []
    client = TelegramClient(sess, api_id, api_hash)
    await client.start()
    # Будуємо мапу id -> entity, щоб робити LeaveChannelRequest на конкретний об'єкт.
    targets: List[Tuple[int, object]] = []
    async for dlg in client.iter_dialogs():
        ent = dlg.entity
        if isinstance(ent, Channel):
            cid = int(getattr(ent, "id", 0) or 0)
            if cid and cid not in db_ids:
                targets.append((cid, ent))

    for cid, ent in targets:
        left.append(cid)
        if dry_run:
            continue
        try:
            await client(LeaveChannelRequest(ent))
        except Exception as e:
            print(f"[{sess}] leave failed cid={cid}: {e}")
        await asyncio.sleep(delay_sec)

    await client.disconnect()
    return left


async def main():
    load_env()
    parser = argparse.ArgumentParser(description="Leave channels present in TG but absent in DB")
    parser.add_argument("--skip", nargs="*", default=["tg_session_3"], help="Сесії, які пропускаємо")
    parser.add_argument("--delay", type=float, default=3.0, help="Затримка між leave, сек")
    parser.add_argument("--dry-run", action="store_true", help="Тільки показати, без відписки")
    args = parser.parse_args()

    api_id = int(os.getenv("API_ID") or os.getenv("TG_API_ID") or 0)
    api_hash = os.getenv("API_HASH") or os.getenv("TG_API_HASH") or ""
    if not api_id or not api_hash:
        raise SystemExit("API_ID/API_HASH not set")

    db_path = os.getenv("DB_PATH", "post_watchdog.sqlite3")
    conn = sqlite3.connect(db_path)

    sessions = collect_sessions(set(args.skip))
    if not sessions:
        raise SystemExit("No sessions to process (all skipped?)")

    for sess in sessions:
        db_ids = db_channels_for(sess, conn)
        print(f"\n=== {sess} ===")
        try:
            tg_full = await tg_channels_full(sess, api_id, api_hash)
        except Exception as e:
            print(f"  telegram fetch failed: {e}")
            continue

        tg_only = [(cid, uname, title, ent) for cid, uname, title, ent in tg_full if cid not in db_ids]
        print(f"  TG-only channels: {len(tg_only)}")
        for cid, uname, title, _ in tg_only[:20]:
            print(f"    {cid}\t{uname or '-'}\t{title}")
        if len(tg_only) > 20:
            print("    ...")

        if args.dry_run or not tg_only:
            continue

        # Відписуємо
        client = TelegramClient(sess, api_id, api_hash)
        await client.start()
        for cid, _, _, ent in tg_only:
            try:
                await client(LeaveChannelRequest(ent))
                print(f"    left {cid}")
            except Exception as e:
                print(f"    leave failed {cid}: {e}")
            await asyncio.sleep(args.delay)
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
