import os, sqlite3, time, re, urllib.parse
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

CREATE TABLE IF NOT EXISTS invite_map (
  invite_hash TEXT PRIMARY KEY,
  channel_id  INTEGER
);

-- URL-кеш (коли channel_id ще невідомий, але маємо фінальний статус по URL)
CREATE TABLE IF NOT EXISTS url_cache (
  url    TEXT PRIMARY KEY,       -- вже нормалізований URL
  status TEXT    NOT NULL,       -- joined/already/requested/invalid/private
  ts     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_urlcache_status ON url_cache(status);

-- Негативний кеш для інвайтів / хешів, що завжди дають поганий результат
-- (наприклад: invalid/private/expired/blocked). Зберігаємо reason для діагностики.
CREATE TABLE IF NOT EXISTS invite_bad (
  invite_hash TEXT PRIMARY KEY,
  reason      TEXT    NOT NULL,  -- invalid/private/expired/blocked/too_many/unknown
  ts          INTEGER NOT NULL
);
"""

FINAL_GLOBAL = ("joined", "already", "requested", "invalid", "private")
FINAL_PER_ACC = ("joined", "already", "requested", "invalid", "private", "blocked", "too_many")
NEGATIVE_INVITE_REASONS = ("invalid", "private", "expired", "blocked", "too_many")

# ----------------------- Low-level helpers -----------------------

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA busy_timeout=3000;")
    return c


def init(db_path: Optional[str] = None):
    """Створює таблиці (якщо їх ще нема). Мігрує схему додаванням відсутніх таблиць.
    Для існуючої БД нові таблиці (invite_bad) просто створяться IF NOT EXISTS.
    """
    global DB_PATH
    if db_path:
        DB_PATH = db_path
    with _conn() as c:
        for stmt in filter(None, DDL.strip().split(";")):
            s = stmt.strip()
            if s:
                c.execute(s)

# ----------------------- URL Normalization -----------------------
_T_ME_HOSTS = {"t.me", "telegram.me", "www.t.me", "www.telegram.me"}
_CHANNEL_PREFIXES = ("https://", "http://")

_URL_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid"}

_TELEGRAM_PATH_NORMALIZE = re.compile(r"^/(joinchat/)?")


def normalize_url(url: str) -> str:
    """Нормалізує Telegram-подібні URL для стабільного кешування.
    Кроки:
      1. trim + strip quotes
      2. lower() схема та хост
      3. canonical host: t.me
      4. видалення трекінгових параметрів
      5. drop fragment (#...)
      6. у joinchat/invite посиланнях лишаємо тільки базову форму 'https://t.me/<rest>'
      7. Прибираємо кінцевий слеш (окрім кореня)
    """
    if not url:
        return url
    url = url.strip().strip('"')
    # Якщо відсутня схема – додаємо https://
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    try:
        parsed = urllib.parse.urlsplit(url)
    except Exception:
        return url  # fallback – повертаємо як є

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    if netloc in _T_ME_HOSTS:
        netloc = "t.me"

    # Очистимо query від трекерів
    if parsed.query:
        q = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        q = [(k, v) for k, v in q if k not in _URL_TRACKING_PARAMS]
        query = urllib.parse.urlencode(q)
    else:
        query = ""

    path = parsed.path or ""
    # Нема потреби зберігати префікс /joinchat/ у кеші – зводимо
    # (але не змінюємо фактичний invite hash після нього)
    if path.startswith("/joinchat/"):
        path = path[len("/joinchat"):]  # залишимо /<hash>

    # Прибираємо зайві слеші
    while '//' in path:
        path = path.replace('//', '/')

    # Финальний rebuild
    fragless = urllib.parse.SplitResult(
        scheme, netloc, path.rstrip('/'), query, "")
    rebuilt = fragless.geturl()
    return rebuilt

# ----------------------- membership (пер-акаунтний стан у каналі) -----------------------

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

# ----------------------- invite_map (інвайт-хеш → channel_id) -----------------------

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

# ----------------------- invite_bad (негативний кеш інвайтів) -----------------------

def invite_bad_add(invite_hash: str, reason: str):
    if reason not in NEGATIVE_INVITE_REASONS and reason != "unknown":
        reason = "unknown"
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO invite_bad(invite_hash,reason,ts) VALUES (?,?,?)",
            (invite_hash, reason, int(time.time())),
        )


def invite_bad_get(invite_hash: str) -> Optional[str]:
    with _conn() as c:
        cur = c.execute("SELECT reason FROM invite_bad WHERE invite_hash=? LIMIT 1", (invite_hash,))
        row = cur.fetchone()
        return row[0] if row else None

# ----------------------- url_cache (коли немає channel_id, але вже є фінальний статус по URL) -----------------------

def url_put(url: str, status: str) -> str:
    nurl = normalize_url(url)
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO url_cache(url,status,ts) VALUES (?,?,?)",
            (nurl, status, int(time.time()))
        )
    return nurl


def url_get(url: str) -> Optional[str]:
    nurl = normalize_url(url)
    with _conn() as c:
        cur = c.execute("SELECT status FROM url_cache WHERE url=? LIMIT 1", (nurl,))
        row = cur.fetchone()
        return row[0] if row else None

# ----------------------- Utility / Debug -----------------------

def debug_counts() -> Tuple[int,int,int,int]:
    """Повертає (membership, invite_map, url_cache, invite_bad) кількості рядків."""
    with _conn() as c:
        cur = c.execute("SELECT (SELECT COUNT(*) FROM membership), (SELECT COUNT(*) FROM invite_map), (SELECT COUNT(*) FROM url_cache), (SELECT COUNT(*) FROM invite_bad)")
        row = cur.fetchone()
        return tuple(int(x) for x in row)  # type: ignore

if __name__ == "__main__":
    init()
    print("DEBUG COUNTS:", debug_counts())