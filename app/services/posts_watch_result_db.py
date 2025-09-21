from __future__ import annotations

import os
import sqlite3
import threading
import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo

log = logging.getLogger("services.posts_watch_result_db")

__all__ = [
    "init",
    "create_watch",
    "mark_matched",
    "mark_done_views",
    "mark_done_deleted",
    "mark_expired",
    "cancel_watch",
    "get_pending_by_channel",
    "list_active_channels",
    "list_due_coverage",
    "list_due_pending_expire",
    "find_active_duplicate",
    "raw_connection",
    "DuplicateWatchError",
]

_DB_PATH = (
    os.environ.get("POSTS_WATCH_RESULT_DB_PATH")
    or os.environ.get("DB_PATH")
    or "posts_watch_result.sqlite3"
)

_conn: Optional[sqlite3.Connection] = None
_lock = threading.Lock()

MOSCOW_TZ = ZoneInfo("Europe/Moscow")  # єдина TZ для всіх полів часу


def _now() -> str:
    # YYYY-MM-DD HH:MM:SS у Europe/Moscow
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _ensure_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        raise RuntimeError("posts_watch_result_db not initialized; call init() first")
    return _conn


def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == col for row in cur.fetchall())


def init() -> None:
    """Ініціалізує SQLite (ідемпотентно) + виконує просту міграцію."""
    global _conn
    if _conn is not None:
        return

    log.debug("[posts_watch_result_db.init] Using DB: %s", _DB_PATH)
    _conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL;")
    _conn.execute("PRAGMA synchronous=NORMAL;")
    _conn.execute("PRAGMA foreign_keys=OFF;")

    # Базова схема
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watch_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id BIGINT NOT NULL,
            template_id BIGINT,
            expected_text_hash TEXT,
            expected_text_norm_len INTEGER,
            expected_links_json TEXT,
            expected_media_fingerprint TEXT,
            time_window_start TEXT,
            time_window_end TEXT,
            status TEXT, -- pending | matched | done | expired | cancelled
            matched_message_id BIGINT,
            matched_at TEXT,
            coverage_check_at TEXT,
            final_views INTEGER,
            deleted_at TEXT,
            created_at TEXT,
            updated_at TEXT,
            matched_session TEXT,
            source_url TEXT
        )
        """
    )

    # Міграція: якщо старі інсталяції без source_url — додаємо
    if not _has_column(_conn, "watch_posts", "source_url"):
        _conn.execute("ALTER TABLE watch_posts ADD COLUMN source_url TEXT")

    # Індекси
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_channel ON watch_posts(channel_id)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_status ON watch_posts(status)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_covcheck ON watch_posts(coverage_check_at)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_matched_session ON watch_posts(matched_session)")

    # Унікальний частковий індекс на активні (pending|matched) — захист від дублів
    _conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_active_watch
        ON watch_posts(channel_id, template_id, expected_text_hash)
        WHERE status IN ('pending','matched')
        """
    )

    _conn.commit()
    log.debug("[posts_watch_result_db.init] DDL applied")


class DuplicateWatchError(RuntimeError):
    """Спроба створити дубль активного моніторингу."""


def create_watch(
    channel_id: int,
    template_id: Optional[int],
    expected_text_hash: Optional[str],
    expected_text_norm_len: Optional[int],
    expected_links_json: Optional[str],
    expected_media_fingerprint: Optional[str],
    time_window_start: Optional[str],
    time_window_end: Optional[str],
    source_url: Optional[str] = None,
) -> int:
    """Створює нову задачу моніторингу: статус 'pending'."""
    conn = _ensure_conn()
    now = _now()
    with _lock:
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO watch_posts (
                    channel_id, template_id,
                    expected_text_hash, expected_text_norm_len, expected_links_json,
                    expected_media_fingerprint,
                    time_window_start, time_window_end,
                    status,
                    created_at, updated_at,
                    source_url
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    channel_id, template_id,
                    expected_text_hash, expected_text_norm_len, expected_links_json,
                    expected_media_fingerprint,
                    time_window_start, time_window_end,
                    "pending", now, now,
                    source_url,
                ),
            )
            conn.commit()
            wid = int(cur.lastrowid)
        except sqlite3.IntegrityError as e:
            raise DuplicateWatchError(
                f"Duplicate active watch for channel={channel_id}, template={template_id}"
            ) from e

    log.info(
        "[posts_watch_result_db.create_watch] watch_id=%s channel_id=%s status=pending source_url=%s",
        wid, channel_id, source_url,
    )
    return wid


def get_watch_source_url(watch_id: int) -> Optional[str]:
    """Повертає source_url для конкретного watch_id, якщо є."""
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            "SELECT source_url FROM watch_posts WHERE id=? LIMIT 1",
            (watch_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return str(row[0]) if row[0] else None

def mark_matched(
    watch_id: int,
    message_id: int,
    coverage_check_at: Optional[str],
    matched_session: Optional[str] = None,
) -> None:
    """
    Знайшли пост: фіксуємо message_id, matched_at, coverage_check_at (може бути NULL),
    статус 'matched', і сесію пошуку.
    """
    conn = _ensure_conn()
    now = _now()
    with _lock:
        conn.execute(
            """
            UPDATE watch_posts
            SET matched_message_id=?, matched_at=?, coverage_check_at=?,
                matched_session=?, status='matched', updated_at=?
            WHERE id=? AND status='pending'
            """,
            (message_id, now, coverage_check_at, matched_session, now, watch_id),
        )
        conn.commit()
    log.info(
        "[posts_watch_result_db.mark_matched] watch_id=%s msg_id=%s status=matched cov_at=%s session=%s",
        watch_id, message_id, coverage_check_at, matched_session,
    )


def mark_done_views(watch_id: int, final_views: Optional[int]) -> None:
    """Через coverage_check_at (коли views увімкнено): зчитали views, статус 'done'."""
    conn = _ensure_conn()
    now = _now()
    with _lock:
        conn.execute(
            """
            UPDATE watch_posts
            SET final_views=?, status='done', updated_at=?
            WHERE id=? AND status='matched'
            """,
            (final_views, now, watch_id),
        )
        conn.commit()
    log.info("[posts_watch_result_db.mark_done_views] watch_id=%s final_views=%s status=done", watch_id, final_views)


def mark_done_deleted(watch_id: int) -> None:
    """Пост зник/видалений: статус 'done', фіксуємо deleted_at."""
    conn = _ensure_conn()
    now = _now()
    with _lock:
        conn.execute(
            """
            UPDATE watch_posts
            SET deleted_at=COALESCE(deleted_at, ?), status='done', updated_at=?
            WHERE id=? AND status IN ('matched','done')
            """,
            (now, now, watch_id),
        )
        conn.commit()
    log.info("[posts_watch_result_db.mark_done_deleted] watch_id=%s deleted status=done", watch_id)


def find_matched_by_message(channel_id: int, message_id: int) -> list[int]:
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id
            FROM watch_posts
            WHERE status IN ('matched','done') AND channel_id=? AND matched_message_id=?
            """,
            (channel_id, message_id),
        )
        rows = cur.fetchall()
    return [int(r[0]) for r in rows]


def mark_expired(watch_id: int) -> None:
    """Вікно очікування минуло, а пост не знайшли."""
    conn = _ensure_conn()
    now = _now()
    with _lock:
        conn.execute(
            "UPDATE watch_posts SET status='expired', updated_at=? WHERE id=? AND status='pending'",
            (now, watch_id),
        )
        conn.commit()
    log.info("[posts_watch_result_db.mark_expired] watch_id=%s status=expired", watch_id)


def cancel_watch(watch_id: int) -> None:
    """Ручне скасування задачі."""
    conn = _ensure_conn()
    now = _now()
    with _lock:
        conn.execute(
            "UPDATE watch_posts SET status='cancelled', updated_at=? WHERE id=? AND status IN ('pending','matched')",
            (now, watch_id),
        )
        conn.commit()
    log.info("[posts_watch_result_db.cancel_watch] watch_id=%s status=cancelled", watch_id)


def get_pending_by_channel(channel_id: int) -> List[Dict[str, Any]]:
    """Усі pending-задачі для каналу (для матчингу у слухачі)."""
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, template_id,
                   expected_text_hash, expected_text_norm_len, expected_links_json,
                   expected_media_fingerprint,
                   time_window_start, time_window_end
            FROM watch_posts
            WHERE channel_id=? AND status='pending'
            """,
            (channel_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "template_id": r[1],
            "expected_text_hash": r[2],
            "expected_text_norm_len": r[3],
            "expected_links_json": r[4],
            "expected_media_fingerprint": r[5],
            "time_window_start": r[6],
            "time_window_end": r[7],
        }
        for r in rows
    ]


def list_active_channels() -> List[int]:
    """Канали, де є незавершені задачі (pending або matched)."""
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT channel_id
            FROM watch_posts
            WHERE status IN ('pending','matched')
            """
        )
        rows = cur.fetchall()
    return [int(r[0]) for r in rows]


def list_due_coverage(now_ts: Optional[str] = None) -> List[Tuple[int, int, int, Optional[str]]]:
    """
    Список matched-задач, у яких пора перевіряти охоплення (views).
    Повертає: (watch_id, channel_id, matched_message_id, matched_session)
    """
    conn = _ensure_conn()
    if not now_ts:
        now_ts = _now()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, channel_id, matched_message_id, matched_session
            FROM watch_posts
            WHERE status='matched' AND coverage_check_at <= ?
            """,
            (now_ts,),
        )
        rows = cur.fetchall()
    out: List[Tuple[int, int, int, Optional[str]]] = []
    for wid, cid, mid, sess in rows:
        if mid is None:
            continue
        out.append((int(wid), int(cid), int(mid), (sess if sess is not None else None)))
    return out


def list_due_pending_expire(now_ts: Optional[str] = None) -> List[int]:
    """
    Список pending-задач, у яких минув дедлайн пошуку (time_window_end).
    Повертає: [watch_id, ...]
    """
    conn = _ensure_conn()
    if not now_ts:
        now_ts = _now()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id
            FROM watch_posts
            WHERE status='pending'
              AND time_window_end IS NOT NULL
              AND time_window_end <> ''
              AND time_window_end <= ?
            """,
            (now_ts,),
        )
        rows = cur.fetchall()
    return [int(r[0]) for r in rows]


def find_active_duplicate(
    channel_id: int,
    template_id: Optional[int],
    expected_text_hash: Optional[str],
) -> Optional[Dict[str, Any]]:
    """
    Шукає активний (pending|matched) дубль моніторингу по ключу:
    (channel_id, template_id, expected_text_hash).
    """
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, status, created_at, time_window_end, matched_message_id
            FROM watch_posts
            WHERE channel_id=? AND template_id IS ?
              AND expected_text_hash IS ?
              AND status IN ('pending','matched')
            ORDER BY id DESC
            LIMIT 1
            """,
            (channel_id, template_id, expected_text_hash),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": int(row[0]),
        "status": str(row[1]),
        "created_at": row[2],
        "time_window_end": row[3],
        "matched_message_id": row[4],
    }


def raw_connection() -> sqlite3.Connection:
    return _ensure_conn()