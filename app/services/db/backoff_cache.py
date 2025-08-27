# app/services/db/backoff_cache.py
from __future__ import annotations
from typing import Optional

from .base import _conn, ensure_tables, now_ts

def backoff_set(channel_id: int, seconds: int) -> None:
    ensure_tables()
    until_ts = now_ts() + max(0, seconds)
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
    ensure_tables()
    with _conn() as c:
        cur = c.execute("SELECT until_ts FROM backoff_cache WHERE channel_id=?", (channel_id,))
        row = cur.fetchone()
        if not row:
            return None
        until_ts = int(row[0])
        if until_ts <= now_ts():
            return None
        return until_ts