# app/services/owner_conflict_guard.py
import hashlib
import sqlite3
import time
from typing import Optional, Tuple
from app.services.channel_db import raw_connection

_initialized = False

def _now() -> int:
    return int(time.time())

def _idem(owner: str, source_ref: str, action: str) -> str:
    s = f"{owner}|{source_ref}|{action}".encode("utf-8")
    return hashlib.sha256(s).hexdigest()

def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS owner_actions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      owner TEXT NOT NULL,
      source_ref TEXT NOT NULL,
      action TEXT NOT NULL,
      idempotency_key TEXT NOT NULL,
      status TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    );
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_owner_actions_triplet ON owner_actions(owner, source_ref, action)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_owner_actions_idem ON owner_actions(idempotency_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_owner_actions_status ON owner_actions(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_owner_actions_created_at ON owner_actions(created_at)")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS owner_conflicts(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      owner TEXT NOT NULL,
      channel_id INTEGER,
      source_ref TEXT,
      reason TEXT NOT NULL,
      created_at INTEGER NOT NULL
    );
    """)
    conn.commit()

def _conn() -> sqlite3.Connection:
    return raw_connection()

def init() -> None:
    global _initialized
    conn = _conn()
    _ensure_schema(conn)
    _initialized = True

def begin(owner: str, source_ref: str, action: str) -> Tuple[bool, str]:
    global _initialized
    conn = _conn()
    if not _initialized:
        _ensure_schema(conn)
        _initialized = True
    key = _idem(owner, source_ref, action)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO owner_actions(owner, source_ref, action, idempotency_key, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
            (owner, source_ref, action, key, "in_progress", _now(), _now()),
        )
        conn.commit()
        return True, key
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, key
    except Exception:
        conn.rollback()
        raise

def end(owner: str, source_ref: str, action: str, result: str) -> None:
    key = _idem(owner, source_ref, action)
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE owner_actions SET status=?, updated_at=? WHERE idempotency_key=?",
            (result, _now(), key),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def note_conflict(owner: str, channel_id: Optional[int], source_ref: Optional[str], reason: str) -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO owner_conflicts(owner, channel_id, source_ref, reason, created_at) VALUES(?,?,?,?,?)",
        (owner, channel_id, source_ref, reason, _now()),
    )
    conn.commit()