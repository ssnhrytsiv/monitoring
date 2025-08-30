import os
import sqlite3
import time
from typing import Optional, List, Tuple, Any

DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")

DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS post_template (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  text       TEXT    NOT NULL,
  mode       TEXT    NOT NULL,   -- 'exact' | 'fuzzy'
  threshold  REAL    NOT NULL,   -- 1.0 для exact; 0..1 для fuzzy
  created_at INTEGER NOT NULL
);
"""

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

def init(db_path: Optional[str] = None):
    """Створює / мігрує таблиці для зразків постів."""
    global DB_PATH
    if db_path:
        DB_PATH = db_path
    with _conn() as c:
        c.executescript(DDL)
        # Міграції (додаємо нові колонки якщо їх нема)
        # title: назва поста; links: JSON масив усіх посилань у пості
        if not _column_exists(c, "post_template", "title"):
            try:
                c.execute("ALTER TABLE post_template ADD COLUMN title TEXT")
            except Exception:
                pass
        if not _column_exists(c, "post_template", "links"):
            try:
                c.execute("ALTER TABLE post_template ADD COLUMN links TEXT")
            except Exception:
                pass

def add_template(
    text: str,
    mode: str = "exact",
    threshold: float = 1.0,
    title: Optional[str] = None,
    links: Optional[str] = None
) -> int:
    """
    Додає зразок поста.
    text     - HTML текст
    title    - коротка назва (може бути None)
    links    - JSON (рядок) зі списком посилань (може бути None)
    """
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
        # Перевіряємо чи є колонки (на випадок виклику до init)
        has_title = _column_exists(c, "post_template", "title")
        has_links = _column_exists(c, "post_template", "links")

        if has_title and has_links:
            cur = c.execute(
                "INSERT INTO post_template(text,mode,threshold,created_at,title,links) VALUES (?,?,?,?,?,?)",
                (text, mode, float(threshold), int(time.time()), title, links),
            )
        elif has_title and not has_links:
            cur = c.execute(
                "INSERT INTO post_template(text,mode,threshold,created_at,title) VALUES (?,?,?,?,?)",
                (text, mode, float(threshold), int(time.time()), title),
            )
        elif has_links and not has_title:
            cur = c.execute(
                "INSERT INTO post_template(text,mode,threshold,created_at,links) VALUES (?,?,?,?,?)",
                (text, mode, float(threshold), int(time.time()), links),
            )
        else:
            cur = c.execute(
                "INSERT INTO post_template(text,mode,threshold,created_at) VALUES (?,?,?,?)",
                (text, mode, float(threshold), int(time.time())),
            )
        return int(cur.lastrowid)

def list_templates(limit: int = 50) -> List[Tuple[int, str, str, float, int]]:
    """
    Поточна (стара) функція – ЗАЛИШАЄМО без змін інтерфейсу для сумісності.
    Не повертає title/links.
    """
    with _conn() as c:
        cur = c.execute(
            "SELECT id, text, mode, threshold, created_at FROM post_template ORDER BY id DESC LIMIT ?",
            (int(limit),)
        )
        return [(int(r[0]), r[1], r[2], float(r[3]), int(r[4])) for r in cur.fetchall()]

def list_templates_full(limit: int = 50) -> List[Tuple[int, str, str, float, int, Optional[str], Optional[str]]]:
    """
    Розширений список із title та links (JSON).
    Якщо колонок ще нема (теоретично), повертає None для них.
    """
    with _conn() as c:
        has_title = _column_exists(c, "post_template", "title")
        has_links = _column_exists(c, "post_template", "links")

        cols = "id, text, mode, threshold, created_at"
        if has_title:
            cols += ", title"
        else:
            cols += ", NULL as title"
        if has_links:
            cols += ", links"
        else:
            cols += ", NULL as links"

        cur = c.execute(
            f"SELECT {cols} FROM post_template ORDER BY id DESC LIMIT ?",
            (int(limit),)
        )
        out = []
        for r in cur.fetchall():
            out.append((
                int(r[0]),         # id
                r[1],              # text
                r[2],              # mode
                float(r[3]),       # threshold
                int(r[4]),         # created_at
                r[5],              # title
                r[6],              # links (JSON)
            ))
        return out