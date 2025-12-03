from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Optional, List, Tuple, Any, Dict

__all__ = [
    "init",
    "upsert_channel",
    "add_link",
    "get_channels_by_owner",
    "find_channel",
    "recent_links",
    "recent_channels",
    "search_channels_by_username",
    "prune_orphan_links",
    "raw_connection",
    "set_invite_owner",
    "get_invite_owner",
]

_DB_PATH = (
    os.environ.get("CHANNEL_DB_PATH")
    or os.environ.get("DB_PATH")
    or "channel_meta.sqlite3"
)

_conn: Optional[sqlite3.Connection] = None
_lock = threading.Lock()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _ensure_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        raise RuntimeError("channel_db not initialized; call init() first")
    return _conn


def init() -> None:
    global _conn
    if _conn is not None:
        return
    _conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL;")
    _conn.execute("PRAGMA synchronous=NORMAL;")
    _conn.execute("PRAGMA foreign_keys=OFF;")

    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id BIGINT UNIQUE,
            username TEXT,
            title TEXT,
            owner_display TEXT,
            owner_username TEXT,
            last_status TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id BIGINT,
            raw_url TEXT,
            kind TEXT,
            batch_msg_id BIGINT,
            owner_display TEXT,
            owner_username TEXT,
            added_at TEXT
        )
        """
    )

    # нова таблиця для мапи invite → owner
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS invite_owners (
            invite_hash TEXT PRIMARY KEY,
            owner_display TEXT,
            owner_username TEXT,
            created_at TEXT
        )
        """
    )

    _conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_channels_channel_id ON channels(channel_id)"
    )
    _conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_channels_owner_usr ON channels(owner_username)"
    )
    _conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_channels_owner_disp ON channels(owner_display)"
    )
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_links_channel ON links(channel_id)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_links_owner_usr ON links(owner_username)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_links_owner_disp ON links(owner_display)")

    _conn.commit()


def upsert_channel(
    channel_id: Optional[int],
    username: Optional[str],
    title: Optional[str],
    owner_display: Optional[str],
    owner_username: Optional[str],
    last_status: Optional[str],
) -> None:
    if channel_id is None:
        return
    conn = _ensure_conn()
    now = _now()
    with _lock:
        cur = conn.cursor()
        cur.execute("SELECT id FROM channels WHERE channel_id=?", (channel_id,))
        row = cur.fetchone()
        if row:
            cur.execute(
                """
                UPDATE channels
                SET username = COALESCE(?, username),
                    title = COALESCE(?, title),
                    owner_display = COALESCE(?, owner_display),
                    owner_username = COALESCE(?, owner_username),
                    last_status = COALESCE(?, last_status),
                    updated_at = ?
                WHERE channel_id = ?
                """,
                (username, title, owner_display, owner_username, last_status, now, channel_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO channels (
                    channel_id, username, title,
                    owner_display, owner_username,
                    last_status, created_at, updated_at
                )
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    channel_id,
                    username,
                    title,
                    owner_display,
                    owner_username,
                    last_status,
                    now,
                    now,
                ),
            )
        conn.commit()


def add_link(
    channel_id: Optional[int],
    raw_url: str,
    kind: Optional[str],
    batch_msg_id: Optional[int],
    owner_display: Optional[str],
    owner_username: Optional[str],
) -> None:
    if not raw_url:
        return
    conn = _ensure_conn()
    now = _now()
    with _lock:
        conn.execute(
            """
            INSERT INTO links (
                channel_id, raw_url, kind, batch_msg_id,
                owner_display, owner_username, added_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (channel_id, raw_url, kind, batch_msg_id, owner_display, owner_username, now),
        )
        conn.commit()


def get_channel_id_by_url(raw_url: str) -> Optional[int]:
    """
    Повертає channel_id для даного raw_url, якщо він колись зʼявлявся в links
    з ненульовим channel_id.
    """
    if not raw_url:
        return None
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT channel_id
            FROM links
            WHERE raw_url = ? AND channel_id IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (raw_url,),
        )
        row = cur.fetchone()
    if not row:
        return None
    try:
        return int(row[0])
    except Exception:
        return None


def get_channels_by_owner(owner: str, limit: int = 50) -> List[Tuple]:
    clean = owner.lstrip("@").lower()
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT channel_id, username, title, last_status,
                   owner_display, owner_username, updated_at
            FROM channels
            WHERE owner_username = ? OR owner_display = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (clean, owner, limit),
        )
        return cur.fetchall()


def find_channel(channel_id: int) -> Optional[Dict[str, Any]]:
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT channel_id, username, title, owner_display, owner_username,
                   last_status, created_at, updated_at
            FROM channels WHERE channel_id=?
            """,
            (channel_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "channel_id": row[0],
        "username": row[1],
        "title": row[2],
        "owner_display": row[3],
        "owner_username": row[4],
        "last_status": row[5],
        "created_at": row[6],
        "updated_at": row[7],
    }


def recent_links(limit: int = 30) -> List[Tuple]:
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT raw_url, channel_id, kind, owner_display, owner_username, added_at
            FROM links
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()


def recent_channels(limit: int = 30) -> List[Tuple]:
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT channel_id, username, title, last_status, owner_display,
                   owner_username, updated_at
            FROM channels
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()


def search_channels_by_username(substring: str, limit: int = 30) -> List[Tuple]:
    if not substring:
        return []
    pattern = f"%{substring.lower()}%"
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT channel_id, username, title, last_status, owner_display,
                   owner_username, updated_at
            FROM channels
            WHERE LOWER(username) LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (pattern, limit),
        )
        return cur.fetchall()


def prune_orphan_links(max_without_channel: int = 10000) -> int:
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM links WHERE channel_id IS NULL")
        cnt = cur.fetchone()[0] or 0
        if cnt <= max_without_channel:
            return 0
        excess = cnt - max_without_channel
        cur.execute(
            """
            DELETE FROM links
            WHERE id IN (
                SELECT id FROM links
                WHERE channel_id IS NULL
                ORDER BY id ASC
                LIMIT ?
            )
            """,
            (excess,),
        )
        deleted = cur.rowcount
        conn.commit()
        return deleted


def raw_connection() -> sqlite3.Connection:
    return _ensure_conn()


def set_invite_owner(invite_hash: str, owner_display: Optional[str], owner_username: Optional[str]) -> None:
    if not invite_hash:
        return
    conn = _ensure_conn()
    now = _now()
    with _lock:
        conn.execute(
            """
            INSERT INTO invite_owners (invite_hash, owner_display, owner_username, created_at)
            VALUES (?,?,?,?)
            ON CONFLICT(invite_hash) DO UPDATE SET
                owner_display=excluded.owner_display,
                owner_username=excluded.owner_username
            """,
            (invite_hash, owner_display, owner_username, now),
        )
        conn.commit()


def get_invite_owner(invite_hash: str) -> Optional[Dict[str, Any]]:
    if not invite_hash:
        return None
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            "SELECT invite_hash, owner_display, owner_username, created_at FROM invite_owners WHERE invite_hash=?",
            (invite_hash,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "invite_hash": row[0],
        "owner_display": row[1],
        "owner_username": row[2],
        "created_at": row[3],
    }