import os, sqlite3, time
from typing import List, Optional, Tuple

DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")

DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS link_queue (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  url           TEXT NOT NULL,
  state         TEXT NOT NULL,            -- queued | processing | done | failed
  tries         INTEGER NOT NULL DEFAULT 0,
  added_ts      INTEGER NOT NULL,
  next_try_ts   INTEGER NOT NULL,
  last_error    TEXT,
  batch_id      TEXT,                     -- опційний тег партії/сеансу
  origin_chat   INTEGER,                  -- звідки прийшло (для нотифів)
  origin_msg    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_lq_state_next ON link_queue(state, next_try_ts);
CREATE UNIQUE INDEX IF NOT EXISTS uq_lq_url_active
  ON link_queue(url)
  WHERE state IN ('queued','processing');
"""

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA busy_timeout=3000;")
    return c

def init(db_path: Optional[str] = None):
    global DB_PATH
    if db_path:
        DB_PATH = db_path
    with _conn() as c:
        for stmt in filter(None, DDL.split(";")):
            s = stmt.strip()
            if s: c.execute(s)

def enqueue(urls: List[str], batch_id: Optional[str], origin_chat: Optional[int], origin_msg: Optional[int], delay_sec: int = 0) -> int:
    """Додає у чергу нові URL (яких немає у стані queued/processing). Повертає к-сть доданих."""
    if not urls:
        return 0
    now = int(time.time())
    count = 0
    with _conn() as c:
        for u in urls:
            try:
                c.execute("""INSERT INTO link_queue(url,state,tries,added_ts,next_try_ts,last_error,batch_id,origin_chat,origin_msg)
                             VALUES(?,?,?,?,?,?,?,?,?)""",
                          (u, "queued", 0, now, now + max(0, int(delay_sec)), None, batch_id, origin_chat, origin_msg))
                count += 1
            except sqlite3.IntegrityError:
                # вже queued/processing — пропускаємо
                pass
    return count

def fetch_due(limit: int = 20) -> List[Tuple[int,str,int,Optional[int],Optional[int]]]:
    """Повертає список записів, що час їх обробити: [(id, url, tries, origin_chat, origin_msg), ...]"""
    now = int(time.time())
    with _conn() as c:
        cur = c.execute("""SELECT id,url,tries,origin_chat,origin_msg
                           FROM link_queue
                           WHERE state='queued' AND next_try_ts<=?
                           ORDER BY added_ts ASC
                           LIMIT ?""", (now, limit))
        return [(int(r[0]), r[1], int(r[2]), r[3], r[4]) for r in cur.fetchall()]

def mark_processing(item_id: int):
    with _conn() as c:
        c.execute("UPDATE link_queue SET state='processing' WHERE id=?", (item_id,))

def mark_done(item_id: int):
    with _conn() as c:
        c.execute("UPDATE link_queue SET state='done', last_error=NULL WHERE id=?", (item_id,))

def mark_failed(item_id: int, error: str, backoff_sec: int, max_retries: int = 5):
    """Позначає failed з бекофом; якщо tries >= max_retries → переводимо у final failed (не перевкладаємо)."""
    now = int(time.time())
    with _conn() as c:
        cur = c.execute("SELECT tries FROM link_queue WHERE id=?", (item_id,)).fetchone()
        tries = int(cur[0]) if cur else 0
        tries += 1
        if tries >= max_retries:
            c.execute("UPDATE link_queue SET state='failed', tries=?, last_error=? WHERE id=?",
                      (tries, error[:500], item_id))
        else:
            c.execute("""UPDATE link_queue
                         SET state='queued', tries=?, last_error=?, next_try_ts=?
                         WHERE id=?""",
                      (tries, error[:500], now + max(5, int(backoff_sec)), item_id))