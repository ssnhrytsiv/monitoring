"""
Проста БД для відстеження відповіді ботів на очікувані повідомлення.
"""
import os
import sqlite3
import time
from typing import List, Optional, Dict, Tuple

DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA busy_timeout=3000;")
    return c


def init(db_path: Optional[str] = None):
    global DB_PATH
    if db_path:
        DB_PATH = db_path
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_watch (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                expected_html TEXT,
                expected_norm TEXT,
                status TEXT,
                session TEXT,
                message_id INTEGER,
                matched_session TEXT,
                time_window_end TEXT,
                created_at INTEGER,
                updated_at INTEGER
            )
            """
        )
        # Міграція: додаємо time_window_end, якщо немає
        cur = c.execute("PRAGMA table_info(bot_watch)")
        cols = {r[1] for r in cur.fetchall()}
        if "time_window_end" not in cols:
            c.execute("ALTER TABLE bot_watch ADD COLUMN time_window_end TEXT")

        c.execute("CREATE INDEX IF NOT EXISTS idx_bot_watch_user ON bot_watch(username)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bot_watch_status ON bot_watch(status)")
        c.commit()


def add_watch(username: str, expected_html: str, session: Optional[str] = None, time_window_end: Optional[str] = None) -> int:
    now = int(time.time())
    # нормалізуємо і одразу кладемо normalized у expected_norm
    try:
        from app.utils.html_normalize import normalize_html_full
        expected_norm = normalize_html_full(expected_html)
    except Exception:
        expected_norm = expected_html
    with _conn() as c:
        cur = c.execute(
            """
            INSERT INTO bot_watch (username, expected_html, expected_norm, status, session, time_window_end, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (username, expected_html, expected_norm, "pending", session, time_window_end, now, now),
        )
        c.commit()
        return int(cur.lastrowid)


def list_pending_for_username(username: str) -> List[Dict]:
    with _conn() as c:
        cur = c.execute(
            """
            SELECT id, username, expected_html, expected_norm, session, time_window_end
            FROM bot_watch
            WHERE username = ?
              AND status = 'pending'
              AND (time_window_end IS NULL OR time_window_end = '' OR time_window_end >= datetime('now'))
            """,
            (username,),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "username": r[1],
            "expected_html": r[2],
            "expected_norm": r[3],
            "session": r[4],
            "time_window_end": r[5],
        }
        for r in rows
    ]


def mark_matched(wid: int, message_id: int, session: Optional[str]) -> None:
    now = int(time.time())
    with _conn() as c:
        c.execute(
            """
            UPDATE bot_watch
            SET status='matched', message_id=?, matched_session=?, updated_at=?
            WHERE id=?
            """,
            (message_id, session, now, wid),
        )
        c.commit()


def mark_done(wid: int) -> None:
    now = int(time.time())
    with _conn() as c:
        c.execute(
            "UPDATE bot_watch SET status='done', updated_at=? WHERE id=?",
            (now, wid),
        )
        c.commit()


def clear_pending_for_username(username: str) -> None:
    now = int(time.time())
    with _conn() as c:
        c.execute(
            "UPDATE bot_watch SET status='done', updated_at=? WHERE username=? AND status='pending'",
            (now, username),
        )
        c.commit()
