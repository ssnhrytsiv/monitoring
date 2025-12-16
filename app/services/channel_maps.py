# app/services/channel_maps.py
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.services.time_utils import msk_timestamp

try:
    # зазвичай одна БД використовується й іншими сервісами
    from app import settings as _S
    DEFAULT_DB = getattr(_S, "DB_FILE", "post_watchdog.sqlite3")
except Exception:
    DEFAULT_DB = "post_watchdog.sqlite3"

_DB_PATH = Path(DEFAULT_DB)
_CONN_OPTS = dict(check_same_thread=False, isolation_level=None)  # autocommit

# ------------------------------
# DDL
# ------------------------------
DDL = r"""
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=3000;

CREATE TABLE IF NOT EXISTS channels (
    channel_id      INTEGER PRIMARY KEY,
    title           TEXT,
    owner_id        INTEGER,          -- логічний «овнер» (користувач/адмін), якщо виставлено
    updated_at      INTEGER           -- MSK unix ts
);

-- url унікальний: може бути інвайт (+hash) або @username/https тощо
CREATE TABLE IF NOT EXISTS links (
    url        TEXT PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    kind       TEXT,                  -- 'private'/'public'/etc
    owner_id   INTEGER,
    first_seen INTEGER,               -- MSK ts
    last_seen  INTEGER,               -- MSK ts
    FOREIGN KEY(channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
);

-- статус підписки по кожній сесії (alias)
CREATE TABLE IF NOT EXISTS subscriptions (
    channel_id    INTEGER NOT NULL,
    alias         TEXT    NOT NULL,   -- ім'я сесії (tg_session, tg_session_2, …)
    joined        INTEGER NOT NULL DEFAULT 0,
    joined_at     INTEGER,            -- MSK ts (коли стало joined=1)
    last_error    TEXT,
    last_error_at INTEGER,            -- MSK ts
    PRIMARY KEY (channel_id, alias),
    FOREIGN KEY(channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
);

-- індекси для пошуку
CREATE INDEX IF NOT EXISTS idx_links_channel_id ON links(channel_id);
CREATE INDEX IF NOT EXISTS idx_subs_channel ON subscriptions(channel_id);
"""


# ------------------------------
# Low-level helpers (async)
# ------------------------------
def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), **_CONN_OPTS)
    conn.row_factory = sqlite3.Row
    return conn


async def _execute(sql: str, params: tuple = ()) -> None:
    def _inner():
        with _get_conn() as c:
            c.execute(sql, params)
    await asyncio.to_thread(_inner)


async def _executemany(sql: str, seq_params: list[tuple]) -> None:
    def _inner():
        with _get_conn() as c:
            c.executemany(sql, seq_params)
    await asyncio.to_thread(_inner)


async def _fetchone(sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    def _inner():
        with _get_conn() as c:
            cur = c.execute(sql, params)
            return cur.fetchone()
    return await asyncio.to_thread(_inner)


async def _fetchall(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    def _inner():
        with _get_conn() as c:
            cur = c.execute(sql, params)
            return cur.fetchall()
    return await asyncio.to_thread(_inner)


# ------------------------------
# Public API
# ------------------------------
async def init(db_path: Optional[str] = None) -> None:
    """
    Ініціалізація схеми (idempotent). Виклич раз під час старту.
    """
    global _DB_PATH
    if db_path:
        _DB_PATH = Path(db_path)

    def _inner():
        with _get_conn() as c:
            c.executescript(DDL)
    await asyncio.to_thread(_inner)


# ---- channels ---------------------------------------------------------------
async def upsert_channel_core(channel_id: int, title: Optional[str], owner_id: Optional[int]) -> None:
    """
    Оновлює/створює базовий запис про канал. updated_at — у Europe/Moscow.
    None-поля не затирають існуючі значення.
    """
    ts = msk_timestamp()
    await _execute(
        """
        INSERT INTO channels (channel_id, title, owner_id, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET
            title     = COALESCE(excluded.title, channels.title),
            owner_id  = COALESCE(excluded.owner_id, channels.owner_id),
            updated_at= excluded.updated_at
        """,
        (int(channel_id), title, owner_id, ts),
    )


async def get_channel(channel_id: int) -> Optional[Dict[str, Any]]:
    row = await _fetchone("SELECT * FROM channels WHERE channel_id = ?", (int(channel_id),))
    return dict(row) if row else None


async def set_channel_owner(channel_id: int, owner_id: Optional[int]) -> None:
    ts = msk_timestamp()
    await _execute(
        "UPDATE channels SET owner_id = ?, updated_at = ? WHERE channel_id = ?",
        (owner_id, ts, int(channel_id)),
    )


# ---- links ------------------------------------------------------------------
async def record_seen_invite(channel_id: int, url: str, kind: str, owner_id: Optional[int]) -> None:
    """
    Регіструє появу лінка (інвайт/username) для каналу.
    first_seen/last_seen — у Europe/Moscow.
    """
    ts = msk_timestamp()
    # гарантуємо, що канал існує (без перезапису title/owner_id якщо None)
    await upsert_channel_core(channel_id=int(channel_id), title=None, owner_id=None)

    await _execute(
        """
        INSERT INTO links (url, channel_id, kind, owner_id, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            channel_id = excluded.channel_id,
            kind       = excluded.kind,
            owner_id   = COALESCE(excluded.owner_id, links.owner_id),
            last_seen  = excluded.last_seen
        """,
        (str(url), int(channel_id), str(kind), owner_id, ts, ts),
    )


async def get_link(url: str) -> Optional[Dict[str, Any]]:
    row = await _fetchone("SELECT * FROM links WHERE url = ?", (str(url),))
    return dict(row) if row else None


async def iter_links_by_channel(channel_id: int) -> list[Dict[str, Any]]:
    rows = await _fetchall(
        "SELECT * FROM links WHERE channel_id = ? ORDER BY last_seen DESC",
        (int(channel_id),),
    )
    return [dict(r) for r in rows]


# ---- subscriptions -----------------------------------------------------------
async def upsert_subscription_joined(channel_id: int, ok: bool, alias: str, err: Optional[str]) -> None:
    """
    Фіксує результат спроби підписки конкретної сесії:
      - ok=True  -> joined=1, joined_at=ts (MSK), last_error/reset
      - ok=False -> joined=0, last_error=err, last_error_at=ts (MSK)
    """
    ts = msk_timestamp()
    if ok:
        await _execute(
            """
            INSERT INTO subscriptions (channel_id, alias, joined, joined_at, last_error, last_error_at)
            VALUES (?, ?, 1, ?, NULL, NULL)
            ON CONFLICT(channel_id, alias) DO UPDATE SET
                joined      = 1,
                joined_at   = excluded.joined_at,
                last_error  = NULL,
                last_error_at = NULL
            """,
            (int(channel_id), str(alias), ts),
        )
    else:
        await _execute(
            """
            INSERT INTO subscriptions (channel_id, alias, joined, joined_at, last_error, last_error_at)
            VALUES (?, ?, 0, NULL, ?, ?)
            ON CONFLICT(channel_id, alias) DO UPDATE SET
                joined        = 0,
                last_error    = excluded.last_error,
                last_error_at = excluded.last_error_at
            """,
            (int(channel_id), str(alias), (err or "")[:500], ts),
        )


async def get_subscription(channel_id: int) -> Optional[Tuple[int, int, str, Optional[int], Optional[str], Optional[int]]]:
    """
    Повертає будь-який запис по каналу (як правило, перший за пріоритетом).
    Формат: (channel_id, joined, alias, joined_at, last_error, last_error_at)
    Якщо треба конкретний alias — зроби окрему функцію.
    """
    row = await _fetchone(
        """
        SELECT channel_id, joined, alias, joined_at, last_error, last_error_at
        FROM subscriptions
        WHERE channel_id = ?
        ORDER BY joined DESC, joined_at DESC NULLS LAST, alias ASC
        LIMIT 1
        """,
        (int(channel_id),),
    )
    if not row:
        return None
    return (row["channel_id"], row["joined"], row["alias"], row["joined_at"], row["last_error"], row["last_error_at"])


async def get_subscription_by_alias(channel_id: int, alias: str) -> Optional[Dict[str, Any]]:
    row = await _fetchone(
        "SELECT * FROM subscriptions WHERE channel_id = ? AND alias = ?",
        (int(channel_id), str(alias)),
    )
    return dict(row) if row else None