#!/usr/bin/env python3
"""
Безпечне вдосконалення схеми для каналів/підписок:
  - таблиця membership_status (довідник статусів)
  - додаткові індекси для пошуку по account
  - view membership_with_title для зручних вибірок

Скрипт ідемпотентний: не змінює існуючі дані, можна запускати повторно.
"""
import os
import sqlite3
from typing import Iterable, Tuple

DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA busy_timeout=3000;")
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def _object_exists(conn: sqlite3.Connection, name: str, kind: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE lower(name)=lower(?) AND type=? LIMIT 1",
        (name, kind),
    )
    return cur.fetchone() is not None


def _ensure_index(conn: sqlite3.Connection, name: str, sql: str) -> bool:
    if _object_exists(conn, name, "index"):
        return False
    conn.execute(sql)
    return True


def _ensure_view(conn: sqlite3.Connection, name: str, sql: str) -> bool:
    if _object_exists(conn, name, "view"):
        return False
    conn.execute(sql)
    return True


def _ensure_membership_status(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS membership_status (
          status     TEXT PRIMARY KEY,
          is_final   INTEGER NOT NULL DEFAULT 0,
          description TEXT
        );
        """
    )
    rows: Iterable[Tuple[str, int, str]] = [
        ("joined", 1, "Успішна підписка"),
        ("already", 1, "Вже був підписаний"),
        ("requested", 1, "Відправлена заявка"),
        ("invalid", 1, "Невалідний/неіснуючий інвайт або юзернейм"),
        ("private", 1, "Приватний канал/інвайт"),
        ("blocked", 1, "Забанений/кикнутий"),
        ("too_many", 1, "Перевищено ліміт підписок у Telegram"),
        ("flood_wait", 0, "Тимчасова помилка (FloodWait)"),
        ("temp", 0, "Тимчасова помилка/інший код"),
        ("error", 0, "Неочікувана помилка"),
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO membership_status(status, is_final, description)
        VALUES (?, ?, ?)
        """,
        rows,
    )


def main() -> None:
    print(f"DB: {DB_PATH}")
    with _connect() as conn:
        _ensure_membership_status(conn)

        created_idx = []
        if _ensure_index(
            conn,
            "idx_membership_account_channel",
            "CREATE INDEX idx_membership_account_channel ON membership(account, channel_id);",
        ):
            created_idx.append("idx_membership_account_channel")
        if _ensure_index(
            conn,
            "idx_membership_account_status",
            "CREATE INDEX idx_membership_account_status ON membership(account, status);",
        ):
            created_idx.append("idx_membership_account_status")

        view_sql = """
        CREATE VIEW membership_with_title AS
        SELECT
            m.account,
            m.channel_id,
            m.status,
            m.ts,
            c.username,
            c.title,
            c.owner_display,
            c.owner_username
        FROM membership AS m
        LEFT JOIN channels AS c
          ON c.channel_id = m.channel_id;
        """
        created_view = _ensure_view(conn, "membership_with_title", view_sql)

        conn.commit()

    print("✅ Done.")
    if created_idx:
        print(f"  + created indexes: {', '.join(created_idx)}")
    if created_view:
        print("  + created view: membership_with_title")
    print("Скрипт можна запускати повторно — він не ламає існуючі дані.")


if __name__ == "__main__":
    main()
