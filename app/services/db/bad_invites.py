from __future__ import annotations

import time
from typing import Optional, Tuple

from .core import _conn, _ensure_tables, _has_table, _has_column

def _ensure_bad_invites_table() -> None:
    _ensure_tables()
    with _conn() as c:
        # створюємо таблицю, якщо немає
        c.execute("""
            CREATE TABLE IF NOT EXISTS bad_invites (
                invite TEXT PRIMARY KEY,
                until  INTEGER NOT NULL,
                reason TEXT
            )
        """)
        # м’які міграції
        if not _has_column(c, "bad_invites", "reason"):
            c.execute("ALTER TABLE bad_invites ADD COLUMN reason TEXT;");


def mark_bad(invite_hash: str, ttl_seconds: int = 43200, reason: str = "") -> None:
    """
    Позначає інвайт як "поганий" на ttl_seconds (за замовч. 12 год).
    """
    if not invite_hash:
        return
    _ensure_bad_invites_table()
    until = int(time.time()) + max(60, int(ttl_seconds))
    with _conn() as c:
        c.execute(
            "INSERT INTO bad_invites(invite, until, reason) VALUES (?, ?, ?) "
            "ON CONFLICT(invite) DO UPDATE SET until=excluded.until, reason=excluded.reason",
            (invite_hash, until, reason or None),
        )


def is_bad(invite_hash: str) -> Tuple[bool, Optional[int], Optional[str]]:
    """
    Повертає (True/False, remaining_sec|None, reason|None).
    True — якщо запис ще не протух.
    """
    if not invite_hash:
        return False, None, None
    _ensure_bad_invites_table()
    now = int(time.time())
    with _conn() as c:
        cur = c.execute("SELECT until, reason FROM bad_invites WHERE invite=?", (invite_hash,))
        row = cur.fetchone()
        if not row:
            return False, None, None
        until, reason = int(row[0]), row[1]
        if until <= now:
            # просте авто-очищення протухлих
            c.execute("DELETE FROM bad_invites WHERE invite=?", (invite_hash,))
            return False, None, None
        return True, until - now, reason


def cleanup_expired() -> int:
    """
    Видаляє протухлі записи, повертає кількість видалених.
    """
    _ensure_bad_invites_table()
    now = int(time.time())
    with _conn() as c:
        cur = c.execute("DELETE FROM bad_invites WHERE until<=?", (now,))
        return cur.rowcount or 0
