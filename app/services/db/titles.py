# app/services/db/titles.py
from __future__ import annotations
from typing import Optional

from .base import _conn, ensure_tables

def channel_title_put(channel_id: int, title: str) -> None:
    if not title:
        return
    ensure_tables()
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
    ensure_tables()
    with _conn() as c:
        cur = c.execute("SELECT title FROM channel_titles WHERE channel_id=?", (channel_id,))
        row = cur.fetchone()
        return row[0] if row else None

def url_title_put(url: str, title: str) -> None:
    if not title:
        return
    ensure_tables()
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
    ensure_tables()
    with _conn() as c:
        cur = c.execute("SELECT title FROM url_titles WHERE url=?", (url,))
        row = cur.fetchone()
        return row[0] if row else None