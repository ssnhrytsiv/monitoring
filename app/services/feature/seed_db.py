"""Simple SQLite-backed storage for generated seed channels.
Used by seed_creator and for CLI reporting.
"""
import sqlite3
import time
from typing import List, Optional, Dict, Any
from pathlib import Path

DB_PATH = Path("./seed_channels.sqlite3")

DDL = r"""
CREATE TABLE IF NOT EXISTS seed_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    peer_id TEXT,
    title TEXT,
    kind TEXT,
    username TEXT,
    invite_link TEXT,
    created_at INTEGER,
    notes TEXT
);
"""


def _get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init():
    conn = _get_conn()
    with conn:
        conn.executescript(DDL)
    conn.close()


def record_channel(peer_id: str, title: str, kind: str, username: Optional[str], invite_link: Optional[str], notes: Optional[str] = None):
    ts = int(time.time())
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT INTO seed_channels (peer_id, title, kind, username, invite_link, created_at, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(peer_id), title, kind, username, invite_link, ts, notes or ""),
        )
    conn.close()


def last_created(n: int = 10) -> List[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.execute("SELECT * FROM seed_channels ORDER BY id DESC LIMIT ?", (n,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def find_by_username(username: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.execute("SELECT * FROM seed_channels WHERE username = ? LIMIT 1", (username,))
    r = cur.fetchone()
    conn.close()
    return dict(r) if r else None