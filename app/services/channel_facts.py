# app/services/channel_facts.py
"""
Lightweight sidecar storage for channel facts (owner bind, title, links, first/last seen).
No migration of the main DB: uses a small dedicated SQLite file (channels_meta.sqlite3).

Public API:
 - init()
 - upsert_channel_facts(channel_id, *, owner_id, owner_username, owner_display, channel_title, seen_link)
 - get_channel_owner(channel_id) -> dict|None
 - note_owner_conflict(channel_id, incoming_owner, source_link)
 - add_link(channel_id, link)
"""

from __future__ import annotations
import sqlite3
import time
from pathlib import Path
from typing import Optional, Dict, Any

DB_PATH = Path("./channels_meta.sqlite3")

DDL = r"""
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=3000;

CREATE TABLE IF NOT EXISTS channels (
  channel_id     INTEGER PRIMARY KEY,
  owner_id       TEXT,
  owner_username TEXT,
  owner_display  TEXT,
  channel_title  TEXT,
  first_seen_at  INTEGER,
  first_seen_link TEXT,
  last_seen_at   INTEGER
);

CREATE TABLE IF NOT EXISTS channel_links (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id INTEGER NOT NULL,
  link       TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  UNIQUE(channel_id, link)
);

CREATE TABLE IF NOT EXISTS owner_conflicts (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id   INTEGER NOT NULL,
  existing_owner TEXT,
  incoming_owner TEXT,
  source_link  TEXT,
  created_at   INTEGER NOT NULL
);
"""


def _conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init():
    conn = _conn()
    with conn:
        conn.executescript(DDL)
    conn.close()


def _owner_to_str(owner_id: Optional[Any], owner_username: Optional[str], owner_display: Optional[str]) -> str:
    if owner_username:
        return f"@{owner_username}"
    if owner_display:
        return owner_display
    if owner_id is not None:
        return str(owner_id)
    return ""


def upsert_channel_facts(
    channel_id: int,
    *,
    owner_id: Optional[Any] = None,
    owner_username: Optional[str] = None,
    owner_display: Optional[str] = None,
    channel_title: Optional[str] = None,
    seen_link: Optional[str] = None,
) -> None:
    """
    - If channel not exists => insert; first call binds owner (if provided).
    - If exists => owner stays unchanged; we only update title/last_seen.
    - Always records `seen_link` into channel_links (deduped).
    """
    ts = int(time.time())
    conn = _conn()
    with conn:
        # read existing
        cur = conn.execute("SELECT * FROM channels WHERE channel_id=?", (int(channel_id),))
        row = cur.fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO channels
                   (channel_id, owner_id, owner_username, owner_display, channel_title, first_seen_at, first_seen_link, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(channel_id),
                    str(owner_id) if owner_id is not None else None,
                    owner_username,
                    owner_display,
                    channel_title,
                    ts,
                    seen_link,
                    ts,
                ),
            )
        else:
            # keep existing owner_*; update title/last_seen
            new_title = channel_title if channel_title else row["channel_title"]
            conn.execute(
                "UPDATE channels SET channel_title=?, last_seen_at=? WHERE channel_id=?",
                (new_title, ts, int(channel_id)),
            )

        if seen_link:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO channel_links (channel_id, link, created_at) VALUES (?, ?, ?)",
                    (int(channel_id), seen_link, ts),
                )
            except Exception:
                # ignore link insert errors
                pass
    conn.close()


def add_link(channel_id: int, link: str) -> None:
    ts = int(time.time())
    conn = _conn()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO channel_links (channel_id, link, created_at) VALUES (?, ?, ?)",
            (int(channel_id), link, ts),
        )
        conn.execute("UPDATE channels SET last_seen_at=? WHERE channel_id=?", (ts, int(channel_id)))
    conn.close()


def get_channel_owner(channel_id: int) -> Optional[Dict[str, Any]]:
    conn = _conn()
    cur = conn.execute("SELECT owner_id, owner_username, owner_display FROM channels WHERE channel_id=?", (int(channel_id),))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


def note_owner_conflict(channel_id: int, incoming_owner: str, source_link: Optional[str]) -> None:
    conn = _conn()
    with conn:
        cur = conn.execute("SELECT owner_id, owner_username, owner_display FROM channels WHERE channel_id=?", (int(channel_id),))
        row = cur.fetchone()
        existing = ""
        if row:
            existing = _owner_to_str(row["owner_id"], row["owner_username"], row["owner_display"])
        ts = int(time.time())
        conn.execute(
            "INSERT INTO owner_conflicts (channel_id, existing_owner, incoming_owner, source_link, created_at) VALUES (?,?,?,?,?)",
            (int(channel_id), existing, incoming_owner, source_link or "", ts),
        )
    conn.close()