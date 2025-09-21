import sqlite3
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

DB_PATH = Path("./seed_posts.sqlite3")

DDL = r"""
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=3000;

CREATE TABLE IF NOT EXISTS seed_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    peer_id TEXT NOT NULL,
    text TEXT,
    message_id INTEGER,
    post_at INTEGER,      -- unix ts, коли постимо
    delete_at INTEGER,    -- unix ts, коли видаляємо (NULL — не видаляти)
    status TEXT NOT NULL, -- pending|posted|deleted|failed
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_seed_posts_status_postat
ON seed_posts(status, post_at);

CREATE INDEX IF NOT EXISTS idx_seed_posts_status_deleteat
ON seed_posts(status, delete_at);
"""

def _conn():
    cn = sqlite3.connect(str(DB_PATH))
    cn.row_factory = sqlite3.Row
    return cn

def init():
    cn = _conn()
    with cn:
        cn.executescript(DDL)
    cn.close()

def schedule_post(peer_id: str, text: str, post_at: int, delete_at: Optional[int]) -> int:
    now = int(time.time())
    cn = _conn()
    with cn:
        cur = cn.execute(
            "INSERT INTO seed_posts (peer_id, text, post_at, delete_at, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
            (peer_id, text, int(post_at), int(delete_at) if delete_at else None, now)
        )
        post_id = cur.lastrowid
    cn.close()
    return int(post_id)

def due_to_post(limit: int = 50) -> List[Dict[str, Any]]:
    now = int(time.time())
    cn = _conn()
    cur = cn.execute(
        "SELECT * FROM seed_posts WHERE status='pending' AND post_at<=? ORDER BY post_at ASC LIMIT ?",
        (now, int(limit))
    )
    rows = [dict(r) for r in cur.fetchall()]
    cn.close()
    return rows

def mark_posted(row_id: int, message_id: int):
    cn = _conn()
    with cn:
        cn.execute(
            "UPDATE seed_posts SET status='posted', message_id=? WHERE id=?",
            (int(message_id), int(row_id))
        )
    cn.close()

def due_to_delete(limit: int = 50) -> List[Dict[str, Any]]:
    now = int(time.time())
    cn = _conn()
    cur = cn.execute(
        "SELECT * FROM seed_posts WHERE status='posted' AND delete_at IS NOT NULL AND delete_at<=? ORDER BY delete_at ASC LIMIT ?",
        (now, int(limit))
    )
    rows = [dict(r) for r in cur.fetchall()]
    cn.close()
    return rows

def mark_deleted(row_id: int):
    cn = _conn()
    with cn:
        cn.execute("UPDATE seed_posts SET status='deleted' WHERE id=?", (int(row_id),))
    cn.close()

def mark_failed(row_id: int):
    cn = _conn()
    with cn:
        cn.execute("UPDATE seed_posts SET status='failed' WHERE id=?", (int(row_id),))
    cn.close()

def list_recent(n: int = 20) -> List[Dict[str, Any]]:
    cn = _conn()
    cur = cn.execute("SELECT * FROM seed_posts ORDER BY id DESC LIMIT ?", (int(n),))
    rows = [dict(r) for r in cur.fetchall()]
    cn.close()
    return rows

def cancel_post(row_id: int) -> bool:
    cn = _conn()
    with cn:
        cur = cn.execute("UPDATE seed_posts SET status='failed' WHERE id=? AND status='pending'", (int(row_id),))
        ok = cur.rowcount > 0
    cn.close()
    return ok