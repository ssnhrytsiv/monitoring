import os
import sqlite3
import time
import logging
from typing import List, Optional, Tuple

log = logging.getLogger("services.link_queue")

DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")

# Поточна повна схема (для нового створення)
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS link_queue (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  url            TEXT NOT NULL,
  state          TEXT NOT NULL,            -- queued | processing | done | failed
  tries          INTEGER NOT NULL DEFAULT 0,
  added_ts       INTEGER NOT NULL,
  next_try_ts    INTEGER NOT NULL,
  last_error     TEXT,
  batch_id       TEXT,
  origin_chat    INTEGER,
  origin_msg     INTEGER,
  owner_display  TEXT,
  owner_username TEXT
);
"""

# Імена індексів
INDEXES = {
    "idx_lq_state_next": "CREATE INDEX idx_lq_state_next ON link_queue(state, next_try_ts)",
    "idx_lq_owner_usr": "CREATE INDEX idx_lq_owner_usr ON link_queue(owner_username)",
    "uq_lq_url_active": """CREATE UNIQUE INDEX uq_lq_url_active
                           ON link_queue(url)
                           WHERE state IN ('queued','processing')"""
}


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA busy_timeout=3000;")
    return c


def _index_exists(c: sqlite3.Connection, name: str) -> bool:
    cur = c.execute("SELECT name FROM sqlite_master WHERE type='index' AND name=?", (name,))
    return cur.fetchone() is not None


def _table_exists(c: sqlite3.Connection, name: str) -> bool:
    cur = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


def init(db_path: Optional[str] = None):
    """
    Ініціалізація / міграція:
      - Якщо таблиці немає — створюємо повну нову.
      - Якщо є — додаємо відсутні стовпці.
      - Потім створюємо відсутні індекси (безпечні перевірки).
    """
    global DB_PATH
    if db_path:
        DB_PATH = db_path
    with _conn() as c:
        c.execute("PRAGMA journal_mode=WAL;")
        if not _table_exists(c, "link_queue"):
            # Нова таблиця
            c.execute(CREATE_TABLE_SQL)
        else:
            # Міграції
            cur = c.execute("PRAGMA table_info(link_queue)")
            cols = {r[1] for r in cur.fetchall()}

            if "owner_display" not in cols:
                c.execute("ALTER TABLE link_queue ADD COLUMN owner_display TEXT")
            if "owner_username" not in cols:
                c.execute("ALTER TABLE link_queue ADD COLUMN owner_username TEXT")

        # Створення індексів, якщо їх ще немає.
        # Перевіряємо індекс owner_username тільки якщо колонка присутня.
        cur = c.execute("PRAGMA table_info(link_queue)")
        cols_now = {r[1] for r in cur.fetchall()}

        # idx_lq_state_next
        if not _index_exists(c, "idx_lq_state_next"):
            c.execute(INDEXES["idx_lq_state_next"])

        # uq_lq_url_active
        if not _index_exists(c, "uq_lq_url_active"):
            c.execute(INDEXES["uq_lq_url_active"])

        # idx_lq_owner_usr (тільки якщо колонка готова)
        if "owner_username" in cols_now and not _index_exists(c, "idx_lq_owner_usr"):
            c.execute(INDEXES["idx_lq_owner_usr"])

        c.commit()


def enqueue(
    urls: List[str],
    batch_id: Optional[str],
    origin_chat: Optional[int],
    origin_msg: Optional[int],
    delay_sec: int = 0,
    owner_display: Optional[str] = None,
    owner_username: Optional[str] = None,
    *,
    adopt_existing: bool = False,
    reset_next_try: bool = True,
) -> int:
    """
    Додає у чергу нові URL (яких немає у стані queued/processing). Повертає к-сть доданих.
    Якщо adopt_existing=True — спробує «забрати» існуючий queued-рядок під новий batch_id.
    """
    if not urls:
        return 0
    now = int(time.time())
    count = 0
    if owner_username:
        owner_username = owner_username.lstrip("@").lower()
    with _conn() as c:
        for u in urls:
            try:
                c.execute(
                    """INSERT INTO link_queue(
                           url,state,tries,added_ts,next_try_ts,last_error,
                           batch_id,origin_chat,origin_msg,owner_display,owner_username
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        u, "queued", 0, now,
                        now + max(0, int(delay_sec)),
                        None, batch_id, origin_chat, origin_msg,
                        owner_display, owner_username
                    )
                )
                count += 1
            except sqlite3.IntegrityError:
                updated = 0
                if adopt_existing:
                    try:
                        next_try = now + max(0, int(delay_sec)) if reset_next_try else None
                        sql = """
                            UPDATE link_queue
                            SET batch_id=?, origin_chat=?, origin_msg=?, owner_display=?, owner_username=? {next_try_clause}
                            WHERE url=? AND state='queued'
                        """
                        clause = ", next_try_ts=?" if next_try is not None else ""
                        q = sql.format(next_try_clause=clause)
                        params = [batch_id, origin_chat, origin_msg, owner_display, owner_username]
                        if next_try is not None:
                            params.append(next_try)
                        params.append(u)
                        cur = c.execute(q, tuple(params))
                        updated = cur.rowcount or 0
                    except Exception:
                        updated = 0
                if updated:
                    count += 1
                    log.info(
                        "enqueue_adopt_existing url=%s -> batch_id=%s",
                        u,
                        batch_id,
                    )
                else:
                    # вже queued/processing — пропускаємо, але логгуємо для діагностики
                    try:
                        existing = c.execute(
                            "SELECT id,state,batch_id,next_try_ts FROM link_queue WHERE url=? AND state IN ('queued','processing')",
                            (u,),
                        ).fetchone()
                        log.info(
                            "enqueue_skip_existing url=%s state=%s batch_id=%s id=%s next_try_ts=%s",
                            u,
                            existing[1] if existing else None,
                            existing[2] if existing else None,
                            existing[0] if existing else None,
                            existing[3] if existing else None,
                        )
                    except Exception:
                        pass
    return count


def fetch_due(
    limit: int = 20,
    exclude_batch_prefixes: Optional[List[str]] = None,
) -> List[Tuple[int, str, int, Optional[int], Optional[int], Optional[str], Optional[str]]]:
    """
    Повертає список записів, що час їх обробити:
    (id, url, tries, origin_chat, origin_msg, owner_display, owner_username)
    """
    now = int(time.time())
    prefixes = exclude_batch_prefixes or []
    conditions = ["state='queued'", "next_try_ts<=?"]
    params: list = [now]
    if prefixes:
        # пропускаємо batch_id, що починаються з указаних префіксів
        conds = ["batch_id IS NULL"]
        for pref in prefixes:
            conds.append("batch_id NOT LIKE ?")
            params.append(pref)
        conditions.append("(" + " AND ".join(conds) + ")")
    with _conn() as c:
        cur = c.execute(
            """SELECT id,url,tries,origin_chat,origin_msg,owner_display,owner_username
               FROM link_queue
               WHERE """
               + " AND ".join(conditions)
               + """
               ORDER BY added_ts ASC
               LIMIT ?""",
            (*params, limit)
        )
        return [
            (int(r[0]), r[1], int(r[2]), r[3], r[4], r[5], r[6])
            for r in cur.fetchall()
        ]


def fetch_batch_due(batch_id: str, limit: int = 50) -> List[Tuple[int, str, int, Optional[int], Optional[int], Optional[str], Optional[str]]]:
    """
    Повертає чергу для конкретного batch_id, що готова до обробки.
    (id, url, tries, origin_chat, origin_msg, owner_display, owner_username)
    """
    now = int(time.time())
    with _conn() as c:
        cur = c.execute(
            """SELECT id,url,tries,origin_chat,origin_msg,owner_display,owner_username
               FROM link_queue
               WHERE state='queued' AND batch_id=? AND next_try_ts<=?
               ORDER BY added_ts ASC, id ASC
               LIMIT ?""",
            (batch_id, now, limit)
        )
        return [
            (int(r[0]), r[1], int(r[2]), r[3], r[4], r[5], r[6])
            for r in cur.fetchall()
        ]


def count_processing() -> int:
    """
    Повертає кількість рядків у стані processing (активні батчі).
    """
    with _conn() as c:
        cur = c.execute("SELECT COUNT(*) FROM link_queue WHERE state='processing'")
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0


def mark_processing(item_id: int):
    with _conn() as c:
        c.execute("UPDATE link_queue SET state='processing' WHERE id=?", (item_id,))


def mark_done(item_id: int):
    with _conn() as c:
        c.execute("UPDATE link_queue SET state='done', last_error=NULL WHERE id=?", (item_id,))


def mark_failed(item_id: int, error: str, backoff_sec: int, max_retries: int = 5):
    """
    Позначає failed з бекофом; якщо tries >= max_retries → final failed.
    """
    now = int(time.time())
    with _conn() as c:
        cur = c.execute("SELECT tries FROM link_queue WHERE id=?", (item_id,)).fetchone()
        tries = int(cur[0]) if cur else 0
        tries += 1
        if tries >= max_retries:
            c.execute(
                "UPDATE link_queue SET state='failed', tries=?, last_error=? WHERE id=?",
                (tries, error[:500], item_id)
            )
        else:
            c.execute(
                """UPDATE link_queue
                   SET state='queued', tries=?, last_error=?, next_try_ts=?
                   WHERE id=?""",
                (tries, error[:500], now + max(5, int(backoff_sec)), item_id)
            )
