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
                created_at INTEGER,
                updated_at INTEGER
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_bot_watch_user ON bot_watch(username)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bot_watch_status ON bot_watch(status)")
        c.commit()


def add_watch(username: str, expected_html: str, session: Optional[str] = None) -> int:
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
            INSERT INTO bot_watch (username, expected_html, expected_norm, status, session, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (username, expected_html, expected_norm, "pending", session, now, now),
        )
        c.commit()
        return int(cur.lastrowid)


def list_pending_for_username(username: str) -> List[Dict]:
    with _conn() as c:
        cur = c.execute(
            """
            SELECT id, username, expected_html, expected_norm, session
            FROM bot_watch
            WHERE username = ? AND status = 'pending'
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
