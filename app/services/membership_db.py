import os, sqlite3, time
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")

DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS membership (
  channel_id INTEGER NOT NULL,
  account    TEXT    NOT NULL,
  status     TEXT    NOT NULL,   -- joined/already/requested/invalid/private/blocked/too_many
  ts         INTEGER NOT NULL,
  attempt_count     INTEGER NOT NULL DEFAULT 0,
  last_error_code   TEXT,
  next_eligible_ts  INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (channel_id, account)
);
CREATE INDEX IF NOT EXISTS idx_membership_channel ON membership(channel_id);
CREATE INDEX IF NOT EXISTS idx_membership_status  ON membership(status);

CREATE TABLE IF NOT EXISTS invite_map (
  invite_hash TEXT PRIMARY KEY,
  channel_id  INTEGER
);

-- URL-кеш (коли channel_id ще невідомий, але маємо фінальний статус по URL)
CREATE TABLE IF NOT EXISTS url_cache (
  url    TEXT PRIMARY KEY,
  status TEXT    NOT NULL,       -- joined/already/requested/invalid/private
  ts     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_urlcache_status ON url_cache(status);
"""

FINAL_GLOBAL = ("joined", "already", "requested", "invalid", "private")
FINAL_PER_ACC = ("joined", "already", "requested", "invalid", "private", "blocked", "too_many")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA busy_timeout=3000;")
    return c


def init(db_path: Optional[str] = None):
    """Створює таблиці (якщо їх ще нема) та мігрує існуючі."""
    global DB_PATH
    if db_path:
        DB_PATH = db_path
    with _conn() as c:
        for stmt in filter(None, DDL.strip().split(";")):
            s = stmt.strip()
            if s:
                c.execute(s)
        
        # Migration: Add new columns to existing membership table if they don't exist
        _migrate_membership_table(c)


def _migrate_membership_table(c):
    """Add new columns to membership table if they don't exist."""
    # Check if columns exist
    cursor = c.execute("PRAGMA table_info(membership)")
    columns = [row[1] for row in cursor.fetchall()]
    
    # Add missing columns
    if 'attempt_count' not in columns:
        c.execute("ALTER TABLE membership ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0")
    if 'last_error_code' not in columns:
        c.execute("ALTER TABLE membership ADD COLUMN last_error_code TEXT")  
    if 'next_eligible_ts' not in columns:
        c.execute("ALTER TABLE membership ADD COLUMN next_eligible_ts INTEGER NOT NULL DEFAULT 0")


# ---------- membership (пер-акаунтний стан у каналі) ----------

def upsert_membership(account: str, channel_id: int, status: str):
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO membership(channel_id,account,status,ts) VALUES (?,?,?,?)",
            (int(channel_id), account, status, int(time.time())),
        )


def get_membership(account: str, channel_id: int) -> Optional[str]:
    with _conn() as c:
        cur = c.execute(
            "SELECT status FROM membership WHERE channel_id=? AND account=? LIMIT 1",
            (int(channel_id), account),
        )
        row = cur.fetchone()
        return row[0] if row else None


def any_final_for_channel(channel_id: int) -> Optional[str]:
    """Повертає один із FINAL_GLOBAL, якщо є у когось для цього каналу (глобальний блокер повторних спроб)."""
    with _conn() as c:
        cur = c.execute(
            f"SELECT status FROM membership WHERE channel_id=? AND status IN ({','.join('?'*len(FINAL_GLOBAL))}) LIMIT 1",
            (int(channel_id), *FINAL_GLOBAL),
        )
        row = cur.fetchone()
        return row[0] if row else None


# ---------- scheduling helper functions ----------

def upsert_membership_with_retry(account: str, channel_id: int, status: str, 
                                attempt_count: int = 0, last_error_code: Optional[str] = None, 
                                next_eligible_ts: int = 0):
    """Extended upsert with retry metadata for scheduling system."""
    with _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO membership(channel_id, account, status, ts, attempt_count, last_error_code, next_eligible_ts) 
               VALUES (?,?,?,?,?,?,?)""",
            (int(channel_id), account, status, int(time.time()), attempt_count, last_error_code, next_eligible_ts),
        )


def get_membership_with_retry(account: str, channel_id: int) -> Optional[tuple[str, int, Optional[str], int]]:
    """Get membership status with retry metadata. Returns (status, attempt_count, last_error_code, next_eligible_ts)."""
    with _conn() as c:
        cur = c.execute(
            """SELECT status, attempt_count, last_error_code, next_eligible_ts 
               FROM membership WHERE channel_id=? AND account=? LIMIT 1""",
            (int(channel_id), account),
        )
        row = cur.fetchone()
        return (row[0], row[1], row[2], row[3]) if row else None


def increment_attempt_count(account: str, channel_id: int, error_code: Optional[str] = None, 
                           next_eligible_ts: int = 0):
    """Increment attempt count and update retry metadata."""
    with _conn() as c:
        c.execute(
            """UPDATE membership 
               SET attempt_count = attempt_count + 1, last_error_code = ?, next_eligible_ts = ?
               WHERE channel_id = ? AND account = ?""",
            (error_code, next_eligible_ts, int(channel_id), account),
        )


# ---------- invite_map (інвайт-хеш → channel_id) ----------

def map_invite_set(invite_hash: str, channel_id: int):
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO invite_map(invite_hash, channel_id) VALUES (?,?)",
            (invite_hash, int(channel_id)),
        )


def map_invite_get(invite_hash: str) -> Optional[int]:
    with _conn() as c:
        cur = c.execute("SELECT channel_id FROM invite_map WHERE invite_hash=? LIMIT 1", (invite_hash,))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else None


# ---------- url_cache (коли немає channel_id, але вже є фінальний статус по URL) ----------

def url_put(url: str, status: str):
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO url_cache(url,status,ts) VALUES (?,?,?)",
            (url, status, int(time.time()))
        )


def url_get(url: str) -> Optional[str]:
    with _conn() as c:
        cur = c.execute("SELECT status FROM url_cache WHERE url=? LIMIT 1", (url,))
        row = cur.fetchone()
        return row[0] if row else None