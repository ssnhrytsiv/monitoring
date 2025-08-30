# app/services/membership_db.py
import os
import sqlite3
import time
from typing import Optional, Tuple

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

-- Інвайт-карта (ключ — invite_hash). Для зворотної сумісності нижче є м'які міграції.
CREATE TABLE IF NOT EXISTS invite_map (
  invite_hash TEXT PRIMARY KEY,
  channel_id  INTEGER,
  title       TEXT,
  updated_at  INTEGER
);

-- СТАТУСИ інвайтів по invite_hash (щоб не залежати від конкретної URL-строки)
CREATE TABLE IF NOT EXISTS invite_status (
  invite_hash TEXT PRIMARY KEY,
  status      TEXT    NOT NULL,  -- joined/already/requested/invalid/private/blocked/too_many
  ts          INTEGER NOT NULL
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


def _has_column(c: sqlite3.Connection, table: str, col: str) -> bool:
    try:
        cur = c.execute(f"PRAGMA table_info({table});")
        cols = [row[1] for row in cur.fetchall()]
        return col in cols
    except Exception:
        return False


def init(db_path: Optional[str] = None):
    """Створює таблиці (якщо їх ще нема) + м’які міграції."""
    global DB_PATH
    if db_path:
        DB_PATH = db_path
    with _conn() as c:
        # Базові таблиці
        for stmt in filter(None, DDL.strip().split(";")):
            s = stmt.strip()
            if s:
                c.execute(s)

        # М’які міграції для invite_map (на випадок старої схеми)
        if not _has_column(c, "invite_map", "title"):
            c.execute("ALTER TABLE invite_map ADD COLUMN title TEXT;")
        if not _has_column(c, "invite_map", "updated_at"):
            c.execute("ALTER TABLE invite_map ADD COLUMN updated_at INTEGER;")
        # invite_status створюється в DDL; додаткових міграцій тут не потрібно


# ---------- helpers: нормалізація invite-ключа ----------

def _extract_invite_hash(inv_or_url: str) -> Optional[str]:
    """
    Повертає чистий invite-hash із:
      - https://t.me/+XXXXXXXX
      - https://t.me/joinchat/XXXXXXXX
    або None, якщо це не інвайт.
    Приймає також уже чистий хеш (без пробілів та '/').
    """
    if not inv_or_url:
        return None
    s = str(inv_or_url)
    # прибираємо типові невидимі артефакти копіпаста
    s = s.replace("\u200b", "").replace("\u200e", "").replace("\u200f", "").strip()
    try:
        if "/+" in s:
            return s.rsplit("/", 1)[-1].replace("+", "").strip()
        if "joinchat/" in s:
            return s.rsplit("joinchat/", 1)[-1].strip()
        # Якщо передали вже hash — приймаємо як є (без пробілів / слешів)
        if "/" not in s and " " not in s:
            return s
    except Exception:
        pass
    return None


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
        placeholders = ",".join("?" * len(FINAL_GLOBAL))
        cur = c.execute(
            f"SELECT status FROM membership WHERE channel_id=? AND status IN ({placeholders}) LIMIT 1",
            (int(channel_id), *FINAL_GLOBAL),
        )
        row = cur.fetchone()
        return row[0] if row else None


# ---------- invite_map (інвайт-хеш → channel_id, title) ----------

def map_invite_set(invite_or_hash: str, channel_id: Optional[int], title: Optional[str] = None) -> None:
    """
    Зберігає відповідність (invite-hash) -> channel_id (+ title).
    Нормалізує ключ до invite-hash. Якщо хеш не дістався — нічого не пишемо.
    """
    h = _extract_invite_hash(invite_or_hash)
    if not h:
        return
    now = int(time.time())
    with _conn() as c:
        # М’які міграції (на випадок, якщо init() ще не викликано)
        if not _has_column(c, "invite_map", "title"):
            c.execute("ALTER TABLE invite_map ADD COLUMN title TEXT;")
        if not _has_column(c, "invite_map", "updated_at"):
            c.execute("ALTER TABLE invite_map ADD COLUMN updated_at INTEGER;")

        c.execute(
            """
            INSERT INTO invite_map(invite_hash, channel_id, title, updated_at)
            VALUES (?,?,?,?)
            ON CONFLICT(invite_hash) DO UPDATE SET
                channel_id=excluded.channel_id,
                title=COALESCE(excluded.title, invite_map.title),
                updated_at=excluded.updated_at
            """,
            (h, int(channel_id) if channel_id is not None else None, title, now),
        )


def map_invite_get(invite_or_hash: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Повертає (channel_id, title) для інвайта/URL/хеша.
    Якщо таблиця стара (без title) — поверне (channel_id, None).
    """
    h = _extract_invite_hash(invite_or_hash)
    if not h:
        return (None, None)
    with _conn() as c:
        # Якщо є колонка title — читаємо обидві
        if _has_column(c, "invite_map", "title"):
            cur = c.execute(
                "SELECT channel_id, title FROM invite_map WHERE invite_hash=? LIMIT 1",
                (h,),
            )
            row = cur.fetchone()
            if row:
                ch = row[0] if row[0] is not None else None
                return (int(ch) if ch is not None else None, row[1])
            return (None, None)
        # Стара схема
        cur = c.execute(
            "SELECT channel_id FROM invite_map WHERE invite_hash=? LIMIT 1",
            (h,),
        )
        row = cur.fetchone()
        return (int(row[0]) if row and row[0] is not None else None, None)


# ---------- invite_status (фінальні стани по invite_hash) ----------

def invite_status_put(invite_or_hash: str, status: str) -> None:
    """
    Зберігає фінальний/стабільний статус по invite_hash:
      joined/already/requested/invalid/private/blocked/too_many
    Використовується, щоб не дергати API, якщо вже знаємо, що інвайт невалідний/приватний тощо.
    """
    h = _extract_invite_hash(invite_or_hash)
    if not h:
        return
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO invite_status(invite_hash,status,ts) VALUES (?,?,?)",
            (h, status, int(time.time()))
        )


def invite_status_get(invite_or_hash: str) -> Optional[str]:
    """
    Повертає збережений статус по invite_hash або None.
    """
    h = _extract_invite_hash(invite_or_hash)
    if not h:
        return None
    with _conn() as c:
        cur = c.execute(
            "SELECT status FROM invite_status WHERE invite_hash=? LIMIT 1",
            (h,)
        )
        row = cur.fetchone()
        return row[0] if row else None


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