# app/services/db/url_cache.py
from __future__ import annotations

import time
from typing import Optional

from app.services.db.core import _ensure_tables, _conn, _has_column


def url_put(url: str, status: str) -> None:
    """
    Кешує статус для конкретного URL.
    Підтримує старі БД, де могла бути колонка ts (NOT NULL).
    """
    _ensure_tables()
    now = int(time.time())
    with _conn() as c:
        has_ts = _has_column(c, "url_cache", "ts")
        if has_ts:
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
        else:
            c.execute(
                """
                INSERT INTO url_cache(url, status, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (url, status, now),
            )


def url_get(url: str) -> Optional[str]:
    """
    Повертає закешований статус для URL або None.
    """
    _ensure_tables()
    with _conn() as c:
        cur = c.execute("SELECT status FROM url_cache WHERE url=?", (url,))
        row = cur.fetchone()
        return row[0] if row else None