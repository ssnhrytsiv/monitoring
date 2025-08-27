# app/services/db/base.py
from __future__ import annotations

import os
import sqlite3
import time

DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def _has_column(c: sqlite3.Connection, table: str, column: str) -> bool:
    cur = c.execute(f"PRAGMA table_info({table});")
    return any(row[1] == column for row in cur.fetchall())

def ensure_tables() -> None:
    """Створення таблиць + міграції колонок (ідемпотентно)."""
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

        # invite_map (в старих БД могло не бути title/updated_at)
        c.execute("""
        CREATE TABLE IF NOT EXISTS invite_map (
            invite     TEXT PRIMARY KEY,
            channel_id INTEGER
        );
        """)
        if not _has_column(c, "invite_map", "title"):
            c.execute("ALTER TABLE invite_map ADD COLUMN title TEXT;")
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

# корисне зараз: time.now() як int
def now_ts() -> int:
    return int(time.time())