# app/services/link_queue.py
from __future__ import annotations

import os
import sqlite3
import time
import random
import sqlite3
import logging
log = logging.getLogger("services.link_queue")
from typing import List, Optional, Tuple, Dict, Any


DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")

# ----------------- low-level -----------------
def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA busy_timeout=3000;")
    return c

def _has_table(c: sqlite3.Connection, name: str) -> bool:
    cur = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None

def _has_column(c: sqlite3.Connection, table: str, col: str) -> bool:
    cur = c.execute(f"PRAGMA table_info({table});")
    return any(r[1] == col for r in cur.fetchall())

def _ensure_schema() -> None:
    with _conn() as c:
        # 1) створюємо таблицю, якщо її немає
        if not _has_table(c, "link_queue"):
            c.execute("""
                CREATE TABLE link_queue (
                  id            INTEGER PRIMARY KEY AUTOINCREMENT,
                  url           TEXT NOT NULL,
                  state         TEXT NOT NULL,            -- queued | processing | done | failed
                  tries         INTEGER NOT NULL DEFAULT 0,
                  added_ts      INTEGER NOT NULL,
                  next_try_ts   INTEGER NOT NULL,
                  last_error    TEXT,
                  batch_id      TEXT,                     -- опційний тег партії/сеансу
                  origin_chat   INTEGER,                  -- звідки прийшло (для повідомлень)
                  origin_msg    INTEGER
                );
            """)
        # 2) додаємо відсутні колонки (міграція)
        if not _has_column(c, "link_queue", "reason"):
            c.execute("ALTER TABLE link_queue ADD COLUMN reason TEXT;")
        if not _has_column(c, "link_queue", "channel_id"):
            c.execute("ALTER TABLE link_queue ADD COLUMN channel_id INTEGER;")

        # 3) індекси — створюємо тільки після наявності колонок
        c.execute("CREATE INDEX IF NOT EXISTS idx_lq_state_next ON link_queue(state, next_try_ts);")
        # reason існує — тепер індекс можна
        c.execute("CREATE INDEX IF NOT EXISTS idx_lq_reason ON link_queue(reason);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_lq_channel ON link_queue(channel_id);")
        # унікальний індекс по активним станам
        c.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_lq_url_active
              ON link_queue(url)
              WHERE state IN ('queued','processing');
        """)

def init(db_path: Optional[str] = None) -> None:
    """
    Ініціалізація БД/таблиць. Міграційно-безпечна.
    """
    global DB_PATH
    if db_path:
        DB_PATH = db_path
    _ensure_schema()

# ----------------- helpers -----------------
def _now() -> int:
    return int(time.time())

def _jitter(sec: int | float, frac: float = 0.15) -> int:
    """Додає невеликий джиттер ±frac*sec, щоб не стріляти залпом."""
    sec = float(max(0.0, sec))
    if sec == 0:
        return 0
    delta = sec * frac
    return int(sec + random.uniform(-delta, +delta))

# ----------------- public API -----------------
def enqueue(
    urls: List[str],
    batch_id: Optional[str],
    origin_chat: Optional[int],
    origin_msg: Optional[int],
    *,
    delay_sec: int = 0,
    reason: Optional[str] = None,
    channel_id: Optional[int] = None,
) -> int:
    """
    Додає у чергу нові URL (яких немає у стані queued/processing).
    Повертає кількість доданих.
    """
    if not urls:
        return 0
    now = _now()
    added = 0
    delay = max(0, int(delay_sec))
    with _conn() as c:
        for u in urls:
            try:
                c.execute(
                    """
                    INSERT INTO link_queue(
                      url, state, tries, added_ts, next_try_ts, last_error,
                      batch_id, origin_chat, origin_msg, reason, channel_id
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        u, "queued", 0, now, now + delay, None,
                        batch_id, origin_chat, origin_msg, reason, channel_id,
                    ),
                )
                added += 1
            except sqlite3.IntegrityError:
                # вже є активний запис для цього url — пропускаємо
                pass
    return added

def fetch_due(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Повертає список записів, що «дозріли» до обробки.
    Формат елемента: {
      id, url, tries, origin_chat, origin_msg, reason, channel_id, next_try_ts
    }
    """
    now = _now()
    with _conn() as c:
        cur = c.execute(
            """
            SELECT id, url, tries, origin_chat, origin_msg, reason, channel_id, next_try_ts
            FROM link_queue
            WHERE state='queued' AND next_try_ts<=?
            ORDER BY added_ts ASC
            LIMIT ?
            """,
            (now, limit),
        )
        rows = cur.fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": int(r[0]),
                    "url": r[1],
                    "tries": int(r[2]),
                    "origin_chat": r[3],
                    "origin_msg": r[4],
                    "reason": r[5],
                    "channel_id": r[6],
                    "next_try_ts": int(r[7]),
                }
            )
        return out

def mark_processing(item_id: int) -> None:
    with _conn() as c:
        c.execute("UPDATE link_queue SET state='processing' WHERE id=?", (item_id,))

def mark_done(item_id: int) -> None:
    with _conn() as c:
        c.execute("UPDATE link_queue SET state='done', last_error=NULL WHERE id=?", (item_id,))

def mark_failed_final(item_id: int, error: str) -> None:
    """Фінально провалити (без повторної постановки у чергу)."""
    with _conn() as c:
        c.execute(
            "UPDATE link_queue SET state='failed', last_error=? WHERE id=?",
            (error[:500], item_id),
        )

def reschedule(
    item_id: int,
    backoff_sec: int,
    *,
    reason: Optional[str] = None,
    jitter: bool = True,
    max_retries: int = 5,
) -> None:
    """
    Перевиставляє запис у стан queued з інкрементом tries та новим next_try_ts.
    Якщо досягнуто max_retries — переводить у failed.
    """
    now = _now()
    with _conn() as c:
        cur = c.execute("SELECT tries FROM link_queue WHERE id=?", (item_id,)).fetchone()
        tries = int(cur[0]) if cur else 0
        tries += 1

        if tries >= max_retries:
            c.execute(
                "UPDATE link_queue SET state='failed', tries=?, last_error=? WHERE id=?",
                (tries, f"max_retries({max_retries})", item_id),
            )
            return

        delay = max(5, int(backoff_sec))
        if jitter:
            delay = _jitter(delay)

        c.execute(
            """
            UPDATE link_queue
            SET state='queued',
                tries=?,
                reason=COALESCE(?, reason),
                next_try_ts=?,
                last_error=NULL
            WHERE id=?
            """,
            (tries, reason, now + delay, item_id),
        )

def mark_failed(item_id: int, error: str, backoff_sec: int, max_retries: int = 5) -> None:
    """
    Сумісний з попереднім інтерфейс: провал із відкладенням.
    Якщо tries >= max_retries — переводимо у final failed.
    """
    now = _now()
    with _conn() as c:
        cur = c.execute("SELECT tries FROM link_queue WHERE id=?", (item_id,)).fetchone()
        tries = int(cur[0]) if cur else 0
        tries += 1
        if tries >= max_retries:
            c.execute(
                "UPDATE link_queue SET state='failed', tries=?, last_error=? WHERE id=?",
                (tries, error[:500], item_id),
            )
        else:
            delay = max(5, int(backoff_sec))
            c.execute(
                """
                UPDATE link_queue
                SET state='queued', tries=?, last_error=?, next_try_ts=?
                WHERE id=?
                """,
                (tries, error[:500], now + delay, item_id),
            )

# --------------- maintenance (необов'язково) ---------------
def purge_finished_older_than(days: int = 7) -> int:
    """
    Видаляє старі done/failed записи, повертає к-сть видалених.
    """
    if days <= 0:
        return 0
    cutoff = _now() - int(days * 86400)
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM link_queue WHERE state IN ('done','failed') AND next_try_ts < ?",
            (cutoff,),
        )
        return cur.rowcount or 0

def list_active(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Повертає активні записи (queued + processing), відсортовані за next_try_ts.
    Поля: url, state, next_try_ts, tries, reason, id
    """
    with _conn() as c:
        cur = c.execute(
            """
            SELECT id, url, state, next_try_ts, tries, reason
            FROM link_queue
            WHERE state IN ('queued','processing')
            ORDER BY next_try_ts ASC, id ASC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append({
                "id": int(r[0]),
                "url": r[1],
                "state": r[2],
                "next_try_ts": int(r[3]),
                "tries": int(r[4]),
                "reason": r[5],
            })
        return out

def count_active() -> Tuple[int, int, int]:
    """
    Повертає (queued_count, processing_count, total_active)
    """
    with _conn() as c:
        q = c.execute("SELECT COUNT(*) FROM link_queue WHERE state='queued'").fetchone()[0]
        p = c.execute("SELECT COUNT(*) FROM link_queue WHERE state='processing'").fetchone()[0]
        return int(q), int(p), int(q) + int(p)

def clear_all() -> int:
    """
    Повне логічне очищення черги:
    - знімаємо всі активні айтеми;
    - переводимо їх у фінальний стан, щоб воркер їх більше не чіпав.
    """
    try:
        items = list_active(limit=100_000)
    except Exception:
        items = []

    removed = 0
    for it in items:
        try:
            mark_failed_final(it["id"], reason="cleared_by_user")
            removed += 1
        except Exception:
            try:
                mark_done(it["id"])
                removed += 1
            except Exception:
                pass
    log.warning("link_queue: logically cleared, deactivated %d items", removed)
    return removed