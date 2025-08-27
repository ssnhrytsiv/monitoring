# app/tools/queue_cleanup.py
from __future__ import annotations
from typing import List, Tuple
import sqlite3
import os

DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA busy_timeout=3000;")
    return c

def list_pending(limit: int = 2000) -> List[Tuple[int, str, str, int]]:
    """Повертає (id, url, state, tries) для queued|processing."""
    with _conn() as c:
        cur = c.execute(
            """SELECT id, url, state, tries
               FROM link_queue
               WHERE state IN ('queued','processing')
               ORDER BY id ASC
               LIMIT ?""",
            (limit,),
        )
        return [(int(r[0]), r[1], r[2], int(r[3])) for r in cur.fetchall()]

def count_pending() -> int:
    with _conn() as c:
        cur = c.execute(
            "SELECT COUNT(*) FROM link_queue WHERE state IN ('queued','processing')"
        )
        return int(cur.fetchone()[0])

def clear_pending(dry_run: bool = False) -> int:
    """Видаляє queued|processing. Повертає кількість записів."""
    with _conn() as c:
        if dry_run:
            cur = c.execute(
                "SELECT COUNT(*) FROM link_queue WHERE state IN ('queued','processing')"
            )
            return int(cur.fetchone()[0])
        cur = c.execute(
            "DELETE FROM link_queue WHERE state IN ('queued','processing')"
        )
        return cur.rowcount or 0

def clear_failed_older_than(days: int = 7) -> int:
    """Опційно: чистить старі failed/done (за next_try_ts), якщо потрібно."""
    if days <= 0:
        return 0
    with _conn() as c:
        cur = c.execute(
            """
            DELETE FROM link_queue
            WHERE state IN ('done','failed')
              AND next_try_ts < CAST(strftime('%s','now') AS INTEGER) - ?
            """,
            (int(days*86400),),
        )
        return cur.rowcount or 0