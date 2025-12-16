from __future__ import annotations

import os
import sqlite3
import threading
import logging
import json
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo
from app.services import channel_db
from app.services.membership_db import get_any_session_for_channel

log = logging.getLogger("services.posts_watch_result_db")

__all__ = [
    "init",
    "create_watch",
    "mark_matched",
    "mark_done_views",
    "mark_done_deleted",
    "mark_expired",
    "mark_unmatched_after_edit",
    "cancel_watch",
    "get_pending_by_channel",
    "list_active_channels",
    "list_due_coverage",
    "list_due_pending_expire",
    "find_active_duplicate",
    "get_watch_source_url",
    "get_watch_created_by",
    "get_watch_created_via",
    "insert_watch_event",
    "fetch_unsent_events",
    "mark_event_sent",
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

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def _now() -> str:
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
    global _conn
    if _conn is not None:
        return

    log.debug("[posts_watch_result_db.init] Using DB: %s", _DB_PATH)
    _conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL;")
    _conn.execute("PRAGMA synchronous=NORMAL;")
    _conn.execute("PRAGMA foreign_keys=OFF;")

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
            status TEXT,
            matched_message_id BIGINT,
            matched_at TEXT,
            coverage_check_at TEXT,
            final_views INTEGER,
            deleted_at TEXT,
            created_at TEXT,
            updated_at TEXT,
            matched_session TEXT,
            source_url TEXT,
            created_by BIGINT,
            created_via TEXT
        )
        """
    )

    if not _has_column(_conn, "watch_posts", "source_url"):
        _conn.execute("ALTER TABLE watch_posts ADD COLUMN source_url TEXT")

    if not _has_column(_conn, "watch_posts", "created_by"):
        _conn.execute("ALTER TABLE watch_posts ADD COLUMN created_by BIGINT")

    if not _has_column(_conn, "watch_posts", "created_via"):
        _conn.execute("ALTER TABLE watch_posts ADD COLUMN created_via TEXT")

    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watch_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            watch_id BIGINT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT,
            created_at TEXT NOT NULL,
            sent_to BIGINT,
            sent_at TEXT
        )
        """
    )

    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_channel ON watch_posts(channel_id)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_status ON watch_posts(status)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_covcheck ON watch_posts(coverage_check_at)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_matched_session ON watch_posts(matched_session)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_created_by ON watch_posts(created_by)")

    _conn.execute("CREATE INDEX IF NOT EXISTS idx_we_sent_at ON watch_events(sent_at)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_we_unsent ON watch_events(sent_at, id)")

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
    pass


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
    created_by: Optional[int] = None,
    created_via: Optional[str] = None,
) -> int:
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
                    source_url,
                    created_by,
                    created_via
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    channel_id, template_id,
                    expected_text_hash, expected_text_norm_len, expected_links_json,
                    expected_media_fingerprint,
                    time_window_start, time_window_end,
                    "pending", now, now,
                    source_url,
                    created_by,
                    created_via,
                ),
            )
            conn.commit()
            wid = int(cur.lastrowid)
        except sqlite3.IntegrityError as e:
            raise DuplicateWatchError(
                f"Duplicate active watch for channel={channel_id}, template={template_id}"
            ) from e

    log.info(
        "[posts_watch_result_db.create_watch] watch_id=%s channel_id=%s status=pending source_url=%s created_by=%s created_via=%s",
        wid, channel_id, source_url, created_by, created_via,
    )
    return wid


def get_watch_source_url(watch_id: int) -> Optional[str]:
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


def get_watch_created_by(watch_id: int) -> Optional[int]:
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            "SELECT created_by FROM watch_posts WHERE id=? LIMIT 1",
            (watch_id,),
        )
        row = cur.fetchone()
    if not row or row[0] is None:
        return None
    try:
        return int(row[0])
    except Exception:
        return None


def get_watch_created_via(watch_id: int) -> Optional[str]:
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            "SELECT created_via FROM watch_posts WHERE id=? LIMIT 1",
            (watch_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return str(row[0]) if row[0] else None


def insert_watch_event(watch_id: int, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    conn = _ensure_conn()
    now = _now()
    try:
        payload_json = json.dumps(payload or {}, ensure_ascii=False)
    except Exception:
        payload_json = "{}"
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO watch_events (watch_id, event_type, payload_json, created_at)
            VALUES (?,?,?,?)
            """,
            (
                int(watch_id),
                str(event_type),
                payload_json,
                now,
            ),
        )
        conn.commit()


def fetch_unsent_events(limit: int = 100) -> List[Tuple[int, int, str, str, str]]:
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, watch_id, event_type, payload_json, created_at
            FROM watch_events
            WHERE sent_at IS NULL
            ORDER BY id ASC
            LIMIT ?
            """,
            (int(limit),),
        )
        rows = cur.fetchall()
    return [
        (int(r[0]), int(r[1]), str(r[2]), str(r[3] or ""), str(r[4] or ""))
        for r in rows
    ]


def mark_event_sent(event_id: int, sent_to: int) -> None:
    conn = _ensure_conn()
    now = _now()
    with _lock:
        conn.execute(
            """
            UPDATE watch_events
            SET sent_to=?, sent_at=?
            WHERE id=? AND sent_at IS NULL
            """,
            (int(sent_to), now, int(event_id)),
        )
        conn.commit()


def mark_matched(
    watch_id: int,
    message_id: int,
    coverage_check_at: Optional[str],
    matched_session: Optional[str] = None,
) -> None:
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
    conn = _ensure_conn()
    now = _now()
    with _lock:
        conn.execute(
            "UPDATE watch_posts SET status='expired', updated_at=? WHERE id=? AND status='pending'",
            (now, watch_id),
        )
        conn.commit()
    log.info("[posts_watch_result_db.mark_expired] watch_id=%s status=expired", watch_id)


def mark_unmatched_after_edit(watch_id: int) -> None:
    conn = _ensure_conn()
    now = _now()
    with _lock:
        conn.execute(
            """
            UPDATE watch_posts
            SET status=CASE WHEN status='matched' THEN 'expired' ELSE status END,
                coverage_check_at=NULL,
                updated_at=?
            WHERE id=? AND status IN ('matched','done')
            """,
            (now, watch_id),
        )
        conn.commit()
    log.info("[posts_watch_result_db.mark_unmatched_after_edit] watch_id=%s edited->unmatched", watch_id)


def cancel_watch(watch_id: int) -> None:
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

def force_mark_matched(
    watch_id: int,
    message_id: int,
    coverage_check_at: Optional[str],
    matched_session: Optional[str] = None,
) -> None:
    """
    Примусово ставить вотч у matched як з pending, так і з expired.
    Використовується для ручного матчу через бота.
    """
    conn = _ensure_conn()
    now = _now()
    with _lock:
        conn.execute(
            """
            UPDATE watch_posts
            SET matched_message_id=?, matched_at=?, coverage_check_at=?,
                matched_session=?, status='matched', updated_at=?
            WHERE id=? AND status IN ('pending','expired')
            """,
            (message_id, now, coverage_check_at, matched_session, now, watch_id),
        )
        conn.commit()
    log.info(
        "[posts_watch_result_db.force_mark_matched] watch_id=%s msg_id=%s status=matched (from pending/expired) cov_at=%s session=%s",
        watch_id, message_id, coverage_check_at, matched_session,
    )

def get_watch_channel_id(watch_id: int) -> Optional[int]:
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            "SELECT channel_id FROM watch_posts WHERE id=? LIMIT 1",
            (watch_id,),
        )
        row = cur.fetchone()
    if not row or row[0] is None:
        return None
    try:
        return int(row[0])
    except Exception:
        return None

def get_session_for_source_url(source_url: str) -> Optional[str]:
    """
    Знаходить сесію, яка вже працювала з каналом для цього source_url:
      source_url -> channel_id (channel_db.links) -> account (membership.account).
    """
    if not source_url:
        return None
    try:
        cid = channel_db.get_channel_id_by_url(source_url)
    except Exception:
        cid = None
    if not cid:
        return None
    try:
        return get_any_session_for_channel(cid)
    except Exception:
        return None


def list_due_pending_expire(now_ts: Optional[str] = None) -> List[int]:
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
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=OFF;")
    return conn