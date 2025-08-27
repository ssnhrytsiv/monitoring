# app/services/membership_db_backup.py
from __future__ import annotations

import os
import sqlite3
import time
from typing import Optional, Tuple

DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")


# ---------- low-level ----------
def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _has_column(c: sqlite3.Connection, table: str, column: str) -> bool:
    cur = c.execute(f"PRAGMA table_info({table});")
    return any(row[1] == column for row in cur.fetchall())


def _ensure_tables() -> None:
    with _conn() as c:
        # memberships
        c.execute("""
        CREATE TABLE IF NOT EXISTS memberships (
            acc         TEXT    NOT NULL,
            channel_id  INTEGER NOT NULL,
            status      TEXT    NOT NULL,
            updated_at  INTEGER NOT NULL,
            PRIMARY KEY (acc, channel_id)
        );
        """)

        # url_cache
        c.execute("""
        CREATE TABLE IF NOT EXISTS url_cache (
            url        TEXT PRIMARY KEY,
            status     TEXT,
            updated_at INTEGER,
            ts         INTEGER
        );
        """)
        if not _has_column(c, "url_cache", "updated_at"):
            c.execute("ALTER TABLE url_cache ADD COLUMN updated_at INTEGER;")
        if not _has_column(c, "url_cache", "ts"):
            c.execute("ALTER TABLE url_cache ADD COLUMN ts INTEGER;")

        # channel_titles
        c.execute("""
        CREATE TABLE IF NOT EXISTS channel_titles (
            channel_id  INTEGER PRIMARY KEY,
            title       TEXT
        );
        """)

        # url_titles
        c.execute("""
        CREATE TABLE IF NOT EXISTS url_titles (
            url   TEXT PRIMARY KEY,
            title TEXT
        );
        """)

        # invite_map
        c.execute("""
        CREATE TABLE IF NOT EXISTS invite_map (
            invite     TEXT PRIMARY KEY,
            channel_id INTEGER,
            title      TEXT,
            updated_at INTEGER
        );
        """)
        if not _has_column(c, "invite_map", "updated_at"):
            c.execute("ALTER TABLE invite_map ADD COLUMN updated_at INTEGER;")

        # url_channel_map
        c.execute("""
        CREATE TABLE IF NOT EXISTS url_channel_map (
            url        TEXT PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            updated_at INTEGER
        );
        """)

        # backoff_cache
        c.execute("""
        CREATE TABLE IF NOT EXISTS backoff_cache (
            channel_id INTEGER PRIMARY KEY,
            until_ts   INTEGER NOT NULL
        );
        """)


# ---------- memberships ----------
def upsert_membership(acc: str, channel_id: int, status: str) -> None:
    _ensure_tables()
    now = int(time.time())
    with _conn() as c:
        c.execute(
            """
            INSERT INTO memberships(acc, channel_id, status, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(acc, channel_id) DO UPDATE SET
                status=excluded.status,
                updated_at=excluded.updated_at
            """,
            (acc, channel_id, status, now),
        )


def get_membership(acc: str, channel_id: int) -> Optional[str]:
    _ensure_tables()
    with _conn() as c:
        cur = c.execute(
            "SELECT status FROM memberships WHERE acc=? AND channel_id=?",
            (acc, channel_id),
        )
        row = cur.fetchone()
        return row[0] if row else None


def any_final_for_channel(channel_id: int) -> Optional[str]:
    finals = ("joined", "already", "requested", "invalid", "private")
    _ensure_tables()
    with _conn() as c:
        cur = c.execute(
            f"""
            SELECT status
            FROM memberships
            WHERE channel_id=? AND status IN ({",".join("?"*len(finals))})
            LIMIT 1
            """,
            (channel_id, *finals),
        )
        row = cur.fetchone()
        return row[0] if row else None


# ---------- url_cache ----------
def url_put(url: str, status: str) -> None:
    _ensure_tables()
    now = int(time.time())
    with _conn() as c:
        c.execute(
            """
            INSERT INTO url_cache(url, status, updated_at, ts)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                status=excluded.status,
                updated_at=excluded.updated_at,
                ts=excluded.ts
            """,
            (url, status, now, now),
        )


def url_get(url: str) -> Optional[str]:
    _ensure_tables()
    with _conn() as c:
        cur = c.execute("SELECT status FROM url_cache WHERE url=?", (url,))
        row = cur.fetchone()
        return row[0] if row else None


# ---------- url_channel_map ----------
def url_channel_put(url: str, channel_id: int) -> None:
    _ensure_tables()
    now = int(time.time())
    with _conn() as c:
        c.execute(
            """
            INSERT INTO url_channel_map(url, channel_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                channel_id=excluded.channel_id,
                updated_at=excluded.updated_at
            """,
            (url, channel_id, now),
        )


def url_channel_get(url: str) -> Optional[int]:
    _ensure_tables()
    with _conn() as c:
        cur = c.execute("SELECT channel_id FROM url_channel_map WHERE url=?", (url,))
        row = cur.fetchone()
        return row[0] if row else None


# ---------- channel_titles ----------
def channel_title_put(channel_id: int, title: str) -> None:
    if not title:
        return
    _ensure_tables()
    with _conn() as c:
        c.execute(
            """
            INSERT INTO channel_titles(channel_id, title)
            VALUES (?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                title=excluded.title
            """,
            (channel_id, title),
        )


def channel_title_get(channel_id: int) -> Optional[str]:
    _ensure_tables()
    with _conn() as c:
        cur = c.execute("SELECT title FROM channel_titles WHERE channel_id=?", (channel_id,))
        row = cur.fetchone()
        return row[0] if row else None


# ---------- url_titles ----------
def url_title_put(url: str, title: str) -> None:
    if not title:
        return
    _ensure_tables()
    with _conn() as c:
        c.execute(
            """
            INSERT INTO url_titles(url, title)
            VALUES (?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title=excluded.title
            """,
            (url, title),
        )


def url_title_get(url: str) -> Optional[str]:
    _ensure_tables()
    with _conn() as c:
        cur = c.execute("SELECT title FROM url_titles WHERE url=?", (url,))
        row = cur.fetchone()
        return row[0] if row else None


# ---------- invite_map ----------
def map_invite_set(invite: str, channel_id: Optional[int], title: Optional[str] = None) -> None:
    _ensure_tables()
    now = int(time.time())
    with _conn() as c:
        c.execute(
            """
            INSERT INTO invite_map(invite, channel_id, title, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(invite) DO UPDATE SET
                channel_id=excluded.channel_id,
                title=COALESCE(excluded.title, invite_map.title),
                updated_at=excluded.updated_at
            """,
            (invite, channel_id, title, now),
        )


def map_invite_get(invite: str) -> Tuple[Optional[int], Optional[str]]:
    _ensure_tables()
    with _conn() as c:
        cur = c.execute("SELECT channel_id, title FROM invite_map WHERE invite=?", (invite,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)


# ---------- backoff_cache ----------
def backoff_set(channel_id: int, seconds: int) -> None:
    _ensure_tables()
    until_ts = int(time.time()) + max(0, seconds)
    with _conn() as c:
        c.execute(
            """
            INSERT INTO backoff_cache(channel_id, until_ts)
            VALUES (?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                until_ts=excluded.until_ts
            """,
            (channel_id, until_ts),
        )


def backoff_get(channel_id: int) -> Optional[int]:
    _ensure_tables()
    with _conn() as c:
        cur = c.execute("SELECT until_ts FROM backoff_cache WHERE channel_id=?", (channel_id,))
        row = cur.fetchone()
        if not row:
            return None
        until_ts = row[0]
        if until_ts <= int(time.time()):
            return None
        return until_ts