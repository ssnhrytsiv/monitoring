import os, sqlite3, time
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
BAD_INVITE_TTL_HOURS = int(os.getenv("BAD_INVITE_TTL_HOURS", "48"))

DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS membership (
  channel_id INTEGER NOT NULL,
  account    TEXT    NOT NULL,
  status     TEXT    NOT NULL,   -- joined/already/requested/invalid/private/blocked/too_many
  ts         INTEGER NOT NULL,
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

-- Persistent negative invite cache
CREATE TABLE IF NOT EXISTS invite_bad (
  invite_hash TEXT PRIMARY KEY,
  status      TEXT    NOT NULL,  -- invalid/private/requested
  ts          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_invite_bad_status ON invite_bad(status);
CREATE INDEX IF NOT EXISTS idx_invite_bad_ts ON invite_bad(ts);
"""

FINAL_GLOBAL = ("joined", "already", "requested", "invalid", "private")
FINAL_PER_ACC = ("joined", "already", "requested", "invalid", "private", "blocked", "too_many")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA busy_timeout=3000;")
    return c


def init(db_path: Optional[str] = None):
    """Створює таблиці (якщо їх ще нема)."""
    global DB_PATH
    if db_path:
        DB_PATH = db_path
    with _conn() as c:
        for stmt in filter(None, DDL.strip().split(";")):
            s = stmt.strip()
            if s:
                c.execute(s)


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
    from app.utils.link_parser import normalize_url
    normalized_url = normalize_url(url)
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO url_cache(url,status,ts) VALUES (?,?,?)",
            (normalized_url, status, int(time.time()))
        )


def url_get(url: str) -> Optional[str]:
    from app.utils.link_parser import normalize_url
    normalized_url = normalize_url(url)
    with _conn() as c:
        cur = c.execute("SELECT status FROM url_cache WHERE url=? LIMIT 1", (normalized_url,))
        row = cur.fetchone()
        return row[0] if row else None


# ---------- invite_bad (persistent negative invite cache) ----------

def bad_invite_get(invite_hash: str) -> Optional[str]:
    """
    Get cached negative status for an invite hash.
    Returns None if not found or expired.
    """
    if not invite_hash:
        return None
        
    ttl_seconds = BAD_INVITE_TTL_HOURS * 3600
    min_ts = int(time.time()) - ttl_seconds
    
    with _conn() as c:
        cur = c.execute(
            "SELECT status FROM invite_bad WHERE invite_hash=? AND ts >= ? LIMIT 1", 
            (invite_hash.lower(), min_ts)
        )
        row = cur.fetchone()
        return row[0] if row else None


def bad_invite_put(invite_hash: str, status: str):
    """
    Cache negative status for an invite hash.
    Status should be one of: invalid, private, requested
    """
    if not invite_hash or status not in ("invalid", "private", "requested"):
        return
        
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO invite_bad(invite_hash, status, ts) VALUES (?,?,?)",
            (invite_hash.lower(), status, int(time.time()))
        )


def prune_bad_invites():
    """
    Remove expired entries from invite_bad table.
    """
    ttl_seconds = BAD_INVITE_TTL_HOURS * 3600
    min_ts = int(time.time()) - ttl_seconds
    
    with _conn() as c:
        cur = c.execute("DELETE FROM invite_bad WHERE ts < ?", (min_ts,))
        deleted = cur.rowcount
        return deleted