# app/services/db/invite_map.py
from __future__ import annotations

import time
from typing import Optional, Tuple

from .core import _conn, _ensure_tables, _has_column


def _extract_invite_hash(inv_or_url: str) -> Optional[str]:
    """
    Повертає чистий invite-hash із:
      - https://t.me/+XXXXXXXX
      - https://t.me/joinchat/XXXXXXXX
    або None, якщо це не інвайт.
    """
    if not inv_or_url:
        return None
    s = inv_or_url.strip()
    try:
        if "/+" in s:
            return s.rsplit("/", 1)[-1].replace("+", "").strip()
        if "joinchat/" in s:
            return s.rsplit("joinchat/", 1)[-1].strip()
        # Якщо передали вже hash — приймаємо як є (лише латиниця/цифри/_- довільно)
        if "/" not in s and " " not in s:
            return s
    except Exception:
        pass
    return None


def _invite_col(c) -> str:
    """
    Повертає назву колонки-ключа у таблиці invite_map.
    Підтримує старі схеми з колонкою 'url' та нові з 'invite'.
    """
    if _has_column(c, "invite_map", "invite"):
        return "invite"
    if _has_column(c, "invite_map", "url"):
        return "url"
    return "invite"


def map_invite_set(invite_or_url: str, channel_id: Optional[int], title: Optional[str] = None) -> None:
    """
    Зберігає відповідність (invite-hash або повний URL) -> channel_id (+ title).
    Нормалізує ключ до invite-hash коли можливо (кращий кеш-хіт).
    Сумісно зі старою схемою (PRIMARY KEY на 'url').
    """
    _ensure_tables()
    now = int(time.time())

    key = _extract_invite_hash(invite_or_url) or invite_or_url.strip()

    with _conn() as c:
        col = _invite_col(c)

        # м’які міграції відсутніх колонок
        if not _has_column(c, "invite_map", "title"):
            c.execute("ALTER TABLE invite_map ADD COLUMN title TEXT;")
        if not _has_column(c, "invite_map", "updated_at"):
            c.execute("ALTER TABLE invite_map ADD COLUMN updated_at INTEGER;")

        sql = f"""
            INSERT INTO invite_map({col}, channel_id, title, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT({col}) DO UPDATE SET
                channel_id=excluded.channel_id,
                title=COALESCE(excluded.title, invite_map.title),
                updated_at=excluded.updated_at
        """
        c.execute(sql, (key, channel_id, title, now))


def map_invite_get(invite_or_url: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Повертає (channel_id, title) для інвайта/URL.
    Ключ нормалізується до invite-hash де можливо.
    Працює зі схемами з ключем 'invite' або 'url'.
    """
    _ensure_tables()

    key = _extract_invite_hash(invite_or_url) or invite_or_url.strip()

    with _conn() as c:
        col = _invite_col(c)

        if _has_column(c, "invite_map", "title"):
            cur = c.execute(
                f"SELECT channel_id, title FROM invite_map WHERE {col}=?",
                (key,),
            )
            row = cur.fetchone()
            return (row[0], row[1]) if row else (None, None)
        else:
            cur = c.execute(
                f"SELECT channel_id FROM invite_map WHERE {col}=?",
                (key,),
            )
            row = cur.fetchone()
            return (row[0] if row else None, None)