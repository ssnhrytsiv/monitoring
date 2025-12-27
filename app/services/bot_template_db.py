"""
Сховище шаблонів для bot-watch, аналогічне post_template (режим exact/fuzzy, title, links).
"""
import os
import sqlite3
import time
from typing import Optional, Dict, Any, List, Tuple

DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA busy_timeout=3000;")
    return c


def _column_exists(c: sqlite3.Connection, table: str, column: str) -> bool:
    cur = c.execute(f"PRAGMA table_info({table})")
    for row in cur.fetchall():
        if row[1] == column:
            return True
    return False


def init(db_path: Optional[str] = None) -> None:
    """Створює / мігрує таблицю bot_template."""
    global DB_PATH
    if db_path:
        DB_PATH = db_path
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_template (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                mode TEXT NOT NULL,
                threshold REAL NOT NULL,
                created_at INTEGER NOT NULL,
                title TEXT,
                links TEXT
            )
            """
        )
        # Міграції на випадок старої схеми
        if not _column_exists(c, "bot_template", "mode"):
            c.execute("ALTER TABLE bot_template ADD COLUMN mode TEXT")
        if not _column_exists(c, "bot_template", "threshold"):
            c.execute("ALTER TABLE bot_template ADD COLUMN threshold REAL")
        if not _column_exists(c, "bot_template", "title"):
            c.execute("ALTER TABLE bot_template ADD COLUMN title TEXT")
        if not _column_exists(c, "bot_template", "links"):
            c.execute("ALTER TABLE bot_template ADD COLUMN links TEXT")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bot_template_created ON bot_template(created_at DESC)")
        c.commit()


def add_template(
    text: str,
    mode: str = "exact",
    threshold: float = 1.0,
    title: Optional[str] = None,
    links: Optional[str] = None,
) -> int:
    if not text:
        raise ValueError("text is empty")
    if mode not in ("exact", "fuzzy"):
        mode = "exact"
    if mode == "exact":
        threshold = 1.0
    else:
        try:
            threshold = float(threshold)
        except Exception:
            threshold = 0.7
        threshold = max(0.0, min(1.0, threshold))

    with _conn() as c:
        cur = c.execute(
            "INSERT INTO bot_template(text, mode, threshold, created_at, title, links) VALUES (?,?,?,?,?,?)",
            (text, mode, float(threshold), int(time.time()), title, links),
        )
        c.commit()
        return int(cur.lastrowid)


def get_template(tid: int) -> Optional[Dict[str, Any]]:
    with _conn() as c:
        cur = c.execute(
            "SELECT id, text, mode, threshold, created_at, title, links FROM bot_template WHERE id = ?",
            (int(tid),),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": int(row[0]),
            "text": row[1],
            "mode": row[2],
            "threshold": float(row[3]),
            "created_at": int(row[4]),
            "title": row[5],
            "links": row[6],
        }


def list_templates(limit: int = 50) -> List[Tuple[int, str, str, float, int, Optional[str], Optional[str]]]:
    with _conn() as c:
        cur = c.execute(
            "SELECT id, text, mode, threshold, created_at, title, links FROM bot_template ORDER BY id DESC LIMIT ?",
            (int(limit),),
        )
        out: List[Tuple[int, str, str, float, int, Optional[str], Optional[str]]] = []
        for r in cur.fetchall():
            out.append(
                (
                    int(r[0]),
                    r[1],
                    r[2],
                    float(r[3]),
                    int(r[4]),
                    r[5],
                    r[6],
                )
            )
        return out
