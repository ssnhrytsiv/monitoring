"""
Підтягує актуальні назви каналів з Telegram та оновлює таблицю `channels`
для записів, у яких назва порожня або виглядає як випадковий інвайт-хеш.

Використання:
  API_ID=... API_HASH=... SESSION=tg_session python3 -m scripts.refresh_channel_titles_from_tg

Береться основна сесія (SESSION або за замовчуванням tg_session) і для кожного
кандидата пробує отримати entity за username або link/raw_url з таблиці links.
"""

import asyncio
import os
import re
import sqlite3
from typing import List, Optional, Tuple

from telethon import TelegramClient, errors
from telethon.network.connection import ConnectionTcpAbridged
from telethon.tl import types

DB_PATH = os.getenv("DB_PATH") or os.getenv("CHANNEL_DB_PATH") or "post_watchdog.sqlite3"
SESSION = os.getenv("SESSION") or os.getenv("SESSION_NAME") or "tg_session"
API_ID = int(os.getenv("API_ID", "0") or "0")
API_HASH = os.getenv("API_HASH", "")

PLAIN_HASH_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")
INVITE_RE = re.compile(r"(?:https?://)?t\.me/\+([A-Za-z0-9_-]{8,})")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _link_candidates(conn: sqlite3.Connection, channel_id: int) -> List[str]:
    cur = conn.cursor()
    cur.execute(
        "SELECT raw_url FROM links WHERE channel_id=? ORDER BY id DESC LIMIT 5",
        (channel_id,),
    )
    return [r["raw_url"] for r in cur.fetchall() if r["raw_url"]]


def _invite_from_links(links: List[str]) -> Optional[str]:
    for lnk in links:
        m = INVITE_RE.search(lnk)
        if m:
            return m.group(1)
    return None


def _load_candidates(conn: sqlite3.Connection) -> List[Tuple[int, Optional[str], Optional[str], List[str]]]:
    """
    Повертає список каналів, де назва відсутня або схожа на хеш.
    Кожен елемент: (channel_id, username, title, links[])
    """
    cur = conn.cursor()
    cur.execute("SELECT channel_id, username, title FROM channels")
    rows = cur.fetchall()
    out = []
    for r in rows:
        title = (r["title"] or "").strip()
        if not title or PLAIN_HASH_RE.match(title):
            links = _link_candidates(conn, r["channel_id"])
            out.append((r["channel_id"], r["username"], title, links))
    return out


def _update_channel(
    conn: sqlite3.Connection,
    *,
    channel_id: int,
    title: Optional[str],
    username: Optional[str],
    invite_hash: Optional[str],
) -> None:
    now = "strftime('%Y-%m-%d %H:%M:%S','now')"
    cur = conn.cursor()
    cur.execute(
        f"""
        UPDATE channels
        SET title = COALESCE(?, title),
            username = COALESCE(?, username),
            updated_at = {now}
        WHERE channel_id = ?
        """,
        (title, username, channel_id),
    )
    if invite_hash:
        cur.execute(
            """
            INSERT INTO invite_map (invite_hash, channel_id, title, updated_at)
            VALUES (?, ?, COALESCE(?, title), strftime('%s','now'))
            ON CONFLICT(invite_hash) DO UPDATE SET
                channel_id=excluded.channel_id,
                title=COALESCE(excluded.title, invite_map.title),
                updated_at=excluded.updated_at
            """,
            (invite_hash, channel_id, title),
        )
    conn.commit()


async def _fetch_title(client: TelegramClient, key: str) -> Tuple[Optional[str], Optional[str]]:
    """
    key: username (@foo / https://t.me/foo) або інвайт.
    Повертає (title, username).
    """
    try:
        ent = await client.get_entity(key)
    except errors.FloodWaitError as e:
        raise RuntimeError(f"FloodWait {e.seconds}s on {key}") from e
    except errors.UsernameInvalidError:
        return None, None
    except Exception as e:
        raise RuntimeError(f"get_entity failed for {key}: {e}") from e

    if isinstance(ent, (types.Channel, types.Chat)):
        title = getattr(ent, "title", None) or ""
        uname = getattr(ent, "username", None)
        return title, uname
    return None, None


async def main() -> None:
    if not API_ID or not API_HASH:
        raise SystemExit("Вкажи API_ID/API_HASH у .env")
    conn = _connect()
    candidates = _load_candidates(conn)
    if not candidates:
        print("Немає каналів з порожніми назвами.")
        return

    client = TelegramClient(SESSION, API_ID, API_HASH, connection=ConnectionTcpAbridged)
    await client.start()
    updated = 0
    for cid, uname, title, links in candidates:
        key = None
        if uname:
            key = f"https://t.me/{uname}"
        elif links:
            key = links[0]
        if not key:
            print(f"[skip] channel_id={cid}: немає username/links")
            continue
        try:
            new_title, new_uname = await _fetch_title(client, key)
        except Exception as e:
            print(f"[err ] channel_id={cid} key={key}: {e}")
            continue
        if not new_title and not new_uname:
            print(f"[skip] channel_id={cid} key={key}: entity without title/username")
            continue
        inv_hash = _invite_from_links(links)
        _update_channel(
            conn,
            channel_id=cid,
            title=new_title or None,
            username=new_uname or uname,
            invite_hash=inv_hash,
        )
        updated += 1
        print(f"[ok  ] channel_id={cid}: title='{new_title}' username='{new_uname or uname}'")
    await client.disconnect()
    print(f"Готово: оновлено {updated} каналів.")


if __name__ == "__main__":
    asyncio.run(main())
