# app/services/db/url_channel_map.py
from __future__ import annotations
from typing import Optional

from .base import _conn, ensure_tables, now_ts

def url_channel_put(url: str, channel_id: int) -> None:
    ensure_tables()
    now = now_ts()
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
    ensure_tables()
    with _conn() as c:
        cur = c.execute("SELECT channel_id FROM url_channel_map WHERE url=?", (url,))
        row = cur.fetchone()
        return row[0] if row else None