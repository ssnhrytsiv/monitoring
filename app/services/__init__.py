# app/services/__init__.py
from __future__ import annotations

import os
import sqlite3
import threading
from typing import Optional, Any

# ---------------------------------------------------------------------
# SINGLETON SQLite connection
# ---------------------------------------------------------------------
_DB_PATH = os.getenv("DB_PATH", os.path.join(os.getcwd(), "data.db"))
_CONN_LOCK = threading.Lock()
_CONN: Optional[sqlite3.Connection] = None


def get_conn() -> sqlite3.Connection:
    """
    Повертає єдиний SQLite-конекшн для всього процесу.
    Створює БД та необхідні таблиці при першому зверненні.
    """
    global _CONN
    if _CONN is not None:
        return _CONN

    with _CONN_LOCK:
        if _CONN is not None:
            return _CONN

        conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row

        # Мінімальна ініціалізація для KV-сховища
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv (
                k TEXT PRIMARY KEY,
                v TEXT
            )
            """
        )
        conn.commit()

        _CONN = conn
        return _CONN


# ---------------------------------------------------------------------
# Просте KV-сховище (в пакеті app.services)
# ---------------------------------------------------------------------
def kv_get(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    Отримати значення для ключа key з таблиці kv.
    """
    conn = get_conn()
    cur = conn.execute("SELECT v FROM kv WHERE k = ?", (key,))
    row = cur.fetchone()
    return row["v"] if row else default


def kv_put(key: str, value: Any) -> None:
    """
    Записати/оновити ключ key у таблиці kv.
    Значення приводимо до str для простоти.
    """
    conn = get_conn()
    conn.execute(
        "INSERT INTO kv(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
        (key, str(value)),
    )
    conn.commit()