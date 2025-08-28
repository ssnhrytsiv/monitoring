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

-- Negative cache для інвайтів (невиправні або остаточно оброблені причини)
CREATE TABLE IF NOT EXISTS invite_bad (
  invite_hash TEXT PRIMARY KEY,
  reason      TEXT NOT NULL,     -- invalid/expired/private/blocked/too_many/requested
  ts          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_invite_bad_reason ON invite_bad(reason);
"""

FINAL_GLOBAL = ("joined", "already", "requested", "invalid", "private")
FINAL_PER_ACC = ("joined", "already", "requested", "invalid", "private", "blocked", "too_many")

# Причини які кешуються як остаточно негативні для інвайту
NEGATIVE_INVITE_REASONS = (
    "invalid",
    "expired",
    "private",
    "blocked",
    "too_many",
    "requested",  # запит залишено на модерацію — вважаємо остаточним для URL
)

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


# ---------- invite_bad (negative invite cache) ----------

def invite_bad_add(invite_hash: str, reason: str):
    """
    Заносить інвайт у negative cache, якщо reason у NEGATIVE_INVITE_REASONS.
    Повторні вставки оновлюють timestamp.
    """
    if reason not in NEGATIVE_INVITE_REASONS:
        return
    if not invite_hash:
        return
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO invite_bad(invite_hash,reason,ts) VALUES (?,?,?)",
            (invite_hash, reason, int(time.time()))
        )


def invite_bad_get(invite_hash: str) -> Optional[str]:
    """
    Повертає reason, якщо інвайт у negative cache. Інакше None.
    """
    if not invite_hash:
        return None
    with _conn() as c:
        cur = c.execute(
            "SELECT reason FROM invite_bad WHERE invite_hash=? LIMIT 1",
            (invite_hash,)
        )
        row = cur.fetchone()
        return row[0] if row else None
