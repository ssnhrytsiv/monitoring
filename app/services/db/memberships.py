# app/services/db/memberships.py
from __future__ import annotations
from typing import Optional

from .base import _conn, ensure_tables, now_ts

def upsert_membership(acc: str, channel_id: int, status: str) -> None:
    ensure_tables()
    now = now_ts()
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
    ensure_tables()
    with _conn() as c:
        cur = c.execute(
            "SELECT status FROM memberships WHERE acc=? AND channel_id=?",
            (acc, channel_id),
        )
        row = cur.fetchone()
        return row[0] if row else None

def any_final_for_channel(channel_id: int) -> Optional[str]:
    """
    Фінальні: joined, already, requested, invalid, private.
    """
    ensure_tables()
    finals = ("joined", "already", "requested", "invalid", "private")
    placeholders = ",".join(["?"] * len(finals))
    with _conn() as c:
        cur = c.execute(
            f"""
            SELECT status
            FROM memberships
            WHERE channel_id=? AND status IN ({placeholders})
            LIMIT 1
            """,
            (channel_id, *finals),
        )
        row = cur.fetchone()
        return row[0] if row else None