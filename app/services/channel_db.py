"""
channel_db.py
---------------
Сервіс для збереження метаданих про канали та сирих посилань, які ми опрацьовуємо
(етап 1 — створення БД без інтеграції у process_links / queue_worker).

Поля / ідеї:
- Таблиця channels: по одному запису на channel_id (Telegram internal id).
- Таблиця links: кожне сире посилання, що потрапило в обробку (навіть якщо channel_id ще не відомий).
- Зв’язок links.channel_id -> channels.channel_id (необов’язковий / без FK — для простоти й швидких вставок).
- owner_* фіксуємо «snapshot» (стан на момент обробки пакету), щоб історія не губилася при зміні owner надалі.

Дизайн / компроміси:
- SQLite, один глобальний конект + threading.Lock для серіалізації записів.
- Без складних індексів (лише найпотрібніші).
- Логіка оновлення каналів: якщо існує — оновлюємо вибірково (COALESCE).
- last_status: останній фінальний або проміжний статус (joined / requested / invalid / private / probe / etc).
- updated_at оновлюється при кожному upsert_channel.
- created_at лише при створенні.

Подальші кроки (етапи 2–4):
- Виклик init() при старті (наприклад у main або у plugin.setup()).
- Виклики upsert_channel / add_link у process_links та queue_worker після ensure_join().
- Додати новий плагін для /channels_owner, /recent_links тощо.

ENV:
- CHANNEL_DB_PATH (якщо хочемо окремий файл)
- Якщо немає — беремо DB_PATH (можливо вже використовується membership_db)
- Якщо немає й його — fallback "channel_meta.sqlite3"

Функції публічного API:
- init()
- upsert_channel(channel_id, username, title, owner_display, owner_username, last_status)
- add_link(channel_id, raw_url, kind, batch_msg_id, owner_display, owner_username)
- get_channels_by_owner(owner, limit=50)
- find_channel(channel_id)
- recent_links(limit=30)
- recent_channels(limit=30)
- search_channels_by_username(substring, limit=30)
- prune_orphan_links(max_without_channel=10000)  (опціональна утиліта)
- raw_connection() (для складніших запитів поза модулем — обережно)
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Optional, List, Tuple, Any, Dict

__all__ = [
    "init",
    "upsert_channel",
    "add_link",
    "get_channels_by_owner",
    "find_channel",
    "recent_links",
    "recent_channels",
    "search_channels_by_username",
    "prune_orphan_links",
    "raw_connection",
]

_DB_PATH = (
    os.environ.get("CHANNEL_DB_PATH")
    or os.environ.get("DB_PATH")
    or "channel_meta.sqlite3"
)

_conn: Optional[sqlite3.Connection] = None
_lock = threading.Lock()


# -------------------------
# Helpers
# -------------------------
def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _ensure_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        raise RuntimeError("channel_db not initialized; call init() first")
    return _conn


# -------------------------
# Schema init
# -------------------------
def init() -> None:
    """
    Ініціалізує SQLite БД (idempotent). Безпечний повторний виклик.
    """
    global _conn
    if _conn is not None:
        return
    # isolation_level=None -> autocommit режим небажаний тут; залишимо дефолт
    _conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL;")
    _conn.execute("PRAGMA synchronous=NORMAL;")
    _conn.execute("PRAGMA foreign_keys=OFF;")  # FK не використовуємо (швидкість > строгість)

    # Таблиця каналів
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id BIGINT UNIQUE,
            username TEXT,
            title TEXT,
            owner_display TEXT,
            owner_username TEXT,
            last_status TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    # Таблиця сирих посилань
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id BIGINT,
            raw_url TEXT,
            kind TEXT,
            batch_msg_id BIGINT,
            owner_display TEXT,
            owner_username TEXT,
            added_at TEXT
        )
        """
    )

    # Індекси
    _conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_channels_channel_id ON channels(channel_id)"
    )
    _conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_channels_owner_usr ON channels(owner_username)"
    )
    _conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_channels_owner_disp ON channels(owner_display)"
    )
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_links_channel ON links(channel_id)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_links_owner_usr ON links(owner_username)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_links_owner_disp ON links(owner_display)")

    _conn.commit()


# -------------------------
# Upsert channel
# -------------------------
def upsert_channel(
    channel_id: Optional[int],
    username: Optional[str],
    title: Optional[str],
    owner_display: Optional[str],
    owner_username: Optional[str],
    last_status: Optional[str],
) -> None:
    """
    Додає або частково оновлює канал.
    COALESCE дозволяє не затирати існуючі значення None-ами.
    Якщо channel_id=None → нічого не робимо (немає ключа).
    """
    if channel_id is None:
        return

    conn = _ensure_conn()
    now = _now()

    with _lock:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM channels WHERE channel_id=?",
            (channel_id,),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                """
                UPDATE channels
                SET username = COALESCE(?, username),
                    title = COALESCE(?, title),
                    owner_display = COALESCE(?, owner_display),
                    owner_username = COALESCE(?, owner_username),
                    last_status = COALESCE(?, last_status),
                    updated_at = ?
                WHERE channel_id = ?
                """,
                (username, title, owner_display, owner_username, last_status, now, channel_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO channels (
                    channel_id, username, title,
                    owner_display, owner_username,
                    last_status, created_at, updated_at
                )
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    channel_id,
                    username,
                    title,
                    owner_display,
                    owner_username,
                    last_status,
                    now,
                    now,
                ),
            )
        conn.commit()


# -------------------------
# Add link (raw URL event)
# -------------------------
def add_link(
    channel_id: Optional[int],
    raw_url: str,
    kind: Optional[str],
    batch_msg_id: Optional[int],
    owner_display: Optional[str],
    owner_username: Optional[str],
) -> None:
    """
    Додаємо сире посилання (навіть якщо channel_id ще невідомий).
    kind: public / invite / username / message / unknown (класифікація можлива пізніше).
    """
    if not raw_url:
        return
    conn = _ensure_conn()
    now = _now()
    with _lock:
        conn.execute(
            """
            INSERT INTO links (
                channel_id, raw_url, kind, batch_msg_id,
                owner_display, owner_username, added_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (channel_id, raw_url, kind, batch_msg_id, owner_display, owner_username, now),
        )
        conn.commit()


# -------------------------
# Queries
# -------------------------
def get_channels_by_owner(owner: str, limit: int = 50) -> List[Tuple]:
    """
    Повертає канали по owner. Owner може бути або @username (без @ теж ок),
    або текстове display ім’я. Порівнюємо по обох полях (owner_username / owner_display).
    """
    clean = owner.lstrip("@").lower()
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT channel_id, username, title, last_status,
                   owner_display, owner_username, updated_at
            FROM channels
            WHERE owner_username = ? OR owner_display = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (clean, owner, limit),
        )
        return cur.fetchall()


def find_channel(channel_id: int) -> Optional[Dict[str, Any]]:
    """
    Пошук одного каналу за його channel_id (Telegram internal id).
    """
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT channel_id, username, title, owner_display, owner_username,
                   last_status, created_at, updated_at
            FROM channels WHERE channel_id=?
            """,
            (channel_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "channel_id": row[0],
        "username": row[1],
        "title": row[2],
        "owner_display": row[3],
        "owner_username": row[4],
        "last_status": row[5],
        "created_at": row[6],
        "updated_at": row[7],
    }


def recent_links(limit: int = 30) -> List[Tuple]:
    """
    Останні N посилань (raw_url, channel_id, kind, owner_display, owner_username, added_at).
    """
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT raw_url, channel_id, kind, owner_display, owner_username, added_at
            FROM links
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()


def recent_channels(limit: int = 30) -> List[Tuple]:
    """
    Останні (за updated_at) канали.
    """
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT channel_id, username, title, last_status, owner_display,
                   owner_username, updated_at
            FROM channels
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()


def search_channels_by_username(substring: str, limit: int = 30) -> List[Tuple]:
    """
    Пошук по username (LIKE). Substring приводимо до нижнього регістру.
    """
    if not substring:
        return []
    pattern = f"%{substring.lower()}%"
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT channel_id, username, title, last_status, owner_display,
                   owner_username, updated_at
            FROM channels
            WHERE LOWER(username) LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (pattern, limit),
        )
        return cur.fetchall()


def prune_orphan_links(max_without_channel: int = 10000) -> int:
    """
    Опціональна утиліта: якщо дуже багато links з NULL channel_id — можна обрізати старі.
    Повертає кількість видалених рядків.
    """
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM links WHERE channel_id IS NULL"
        )
        cnt = cur.fetchone()[0] or 0
        if cnt <= max_without_channel:
            return 0
        # Видалимо найстаріші поки не стане <= max_without_channel
        excess = cnt - max_without_channel
        cur.execute(
            """
            DELETE FROM links
            WHERE id IN (
                SELECT id FROM links
                WHERE channel_id IS NULL
                ORDER BY id ASC
                LIMIT ?
            )
            """,
            (excess,),
        )
        deleted = cur.rowcount
        conn.commit()
        return deleted


def raw_connection() -> sqlite3.Connection:
    """
    Повертає сирий конект (якщо потрібні кастомні складні запити).
    Використовуй обережно (самостійно забезпечуй синхронізацію, якщо робиш записи).
    """
    return _ensure_conn()