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
    "find_channel_by_link",
    "get_network_for_channel",
    "get_channels_by_owner",
    "find_channel",
    "recent_links",
    "recent_channels",
    "search_channels_by_username",
    "prune_orphan_links",
    "raw_connection",
    "set_invite_owner",
    "get_invite_owner",
    "upsert_bot_link",
    "get_bot_link",
]

_DB_PATH = (
    os.environ.get("CHANNEL_DB_PATH")
    or os.environ.get("DB_PATH")
    or "post_watchdog.sqlite3"
)

_conn: Optional[sqlite3.Connection] = None
_lock = threading.Lock()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _ensure_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        raise RuntimeError("channel_db not initialized; call init() first")
    return _conn


def init() -> None:
    global _conn
    if _conn is not None:
        return
    _conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL;")
    _conn.execute("PRAGMA synchronous=NORMAL;")
    _conn.execute("PRAGMA foreign_keys=OFF;")

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

    # нова таблиця для мапи invite → owner
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS invite_owners (
            invite_hash TEXT PRIMARY KEY,
            owner_display TEXT,
            owner_username TEXT,
            created_at TEXT
        )
        """
    )

    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            raw_url TEXT,
            status TEXT,
            session TEXT,
            title TEXT,
            owner_display TEXT,
            owner_username TEXT,
            batch_id TEXT,
            last_ts INTEGER,
            last_error TEXT
        )
        """
    )

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
    _conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_bot_links_username ON bot_links(username)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_bot_links_status ON bot_links(status)")

    # Проєктні таблиці для Google Sheets (активні та архівні)
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sheet_projects (
            project TEXT PRIMARY KEY,
            active_spreadsheet_id TEXT,
            active_title TEXT,
            updated_at TEXT
        )
        """
    )
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sheet_project_archives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            spreadsheet_id TEXT NOT NULL,
            title TEXT,
            archived_at TEXT
        )
        """
    )

    _conn.commit()


def _extract_username_from_url(raw_url: str) -> Optional[str]:
    """
    Витягує username із t.me/@username, якщо це не інвайт (+hash).
    """
    if not raw_url:
        return None
    url = raw_url.strip()
    if "+" in url:  # інвайт
        return None
    if url.startswith("@"):
        cand = url.lstrip("@")
    elif "t.me/" in url:
        cand = url.split("t.me/", 1)[1]
    else:
        return None
    cand = cand.split("/", 1)[0].strip()
    if not cand:
        return None
    return cand


def get_network_for_channel(channel_id: int) -> Optional[Tuple[int, Optional[int]]]:
    """
    Повертає (network_id, admin_id) для каналу, якщо він прив'язаний до сітки.
    Якщо запису немає — повертає None.
    """
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT nc.network_id, n.admin_id
            FROM network_channels AS nc
            LEFT JOIN networks AS n ON n.id = nc.network_id
            WHERE nc.channel_id = ?
            LIMIT 1
            """,
            (int(channel_id),),
        )
        row = cur.fetchone()
        if not row:
            return None
        net_id, adm_id = row[0], row[1]
        return int(net_id) if net_id is not None else None, int(adm_id) if adm_id is not None else None


def upsert_channel(
    channel_id: Optional[int],
    username: Optional[str],
    title: Optional[str],
    owner_display: Optional[str],
    owner_username: Optional[str],
    last_status: Optional[str],
) -> None:
    if channel_id is None:
        return
    conn = _ensure_conn()
    now = _now()
    with _lock:
        cur = conn.cursor()
        cur.execute("SELECT id FROM channels WHERE channel_id=?", (channel_id,))
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


def add_link(
    channel_id: Optional[int],
    raw_url: str,
    kind: Optional[str],
    batch_msg_id: Optional[int],
    owner_display: Optional[str],
    owner_username: Optional[str],
) -> None:
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
        # Якщо канал уже відомий, але username відсутній — пробуємо проставити з посилання.
        if channel_id:
            uname = _extract_username_from_url(raw_url)
            if uname:
                conn.execute(
                    """
                    UPDATE channels
                    SET username = COALESCE(?, username)
                    WHERE channel_id = ? AND (username IS NULL OR username = '')
                    """,
                    (uname, channel_id),
                )
        conn.commit()


def get_channel_id_by_url(raw_url: str) -> Optional[int]:
    """
    Повертає channel_id для даного raw_url, якщо він колись зʼявлявся в links
    з ненульовим channel_id.
    """
    if not raw_url:
        return None
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT channel_id
            FROM links
            WHERE raw_url = ? AND channel_id IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (raw_url,),
        )
        row = cur.fetchone()
    if not row:
        return None
    try:
        return int(row[0])
    except Exception:
        return None


def find_channel_by_link(raw_url: str) -> Optional[Tuple[int, Optional[str]]]:
    """
    Повертає (channel_id, title) за точним raw_url, якщо він уже з'являвся в links.
    """
    if not raw_url:
        return None
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT l.channel_id, ch.title
            FROM links l
            LEFT JOIN channels ch ON ch.channel_id = l.channel_id
            WHERE l.raw_url = ?
            ORDER BY l.id DESC
            LIMIT 1
            """,
            (raw_url,),
        )
        row = cur.fetchone()
    if not row or row[0] is None:
        return None
    try:
        return (int(row[0]), row[1])
    except Exception:
        return None


def get_channels_by_owner(owner: str, limit: int = 50) -> List[Tuple]:
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
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM links WHERE channel_id IS NULL")
        cnt = cur.fetchone()[0] or 0
        if cnt <= max_without_channel:
            return 0
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
    return _ensure_conn()


def upsert_bot_link(
    username: str,
    raw_url: Optional[str],
    status: str,
    session: Optional[str] = None,
    title: Optional[str] = None,
    owner_display: Optional[str] = None,
    owner_username: Optional[str] = None,
    batch_id: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    if not username:
        return
    conn = _ensure_conn()
    now = _now()
    with _lock:
        conn.execute(
            """
            INSERT INTO bot_links (username, raw_url, status, session, title, owner_display, owner_username, batch_id, last_ts, last_error)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(username) DO UPDATE SET
                raw_url=excluded.raw_url,
                status=excluded.status,
                session=excluded.session,
                title=excluded.title,
                owner_display=excluded.owner_display,
                owner_username=excluded.owner_username,
                batch_id=excluded.batch_id,
                last_ts=excluded.last_ts,
                last_error=excluded.last_error
            """,
            (
                username,
                raw_url,
                status,
                session,
                title,
                owner_display,
                owner_username,
                batch_id,
                now,
                error,
            ),
        )
        conn.commit()


def get_bot_link(username: str) -> Optional[Dict[str, Any]]:
    if not username:
        return None
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT username, raw_url, status, session, title, owner_display, owner_username, batch_id, last_ts, last_error
            FROM bot_links
            WHERE username = ?
            """,
            (username,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "username": row[0],
        "raw_url": row[1],
        "status": row[2],
        "session": row[3],
        "title": row[4],
        "owner_display": row[5],
        "owner_username": row[6],
        "batch_id": row[7],
        "last_ts": row[8],
        "last_error": row[9],
    }


def set_invite_owner(invite_hash: str, owner_display: Optional[str], owner_username: Optional[str]) -> None:
    if not invite_hash:
        return
    conn = _ensure_conn()
    now = _now()
    with _lock:
        conn.execute(
            """
            INSERT INTO invite_owners (invite_hash, owner_display, owner_username, created_at)
            VALUES (?,?,?,?)
            ON CONFLICT(invite_hash) DO UPDATE SET
                owner_display=excluded.owner_display,
                owner_username=excluded.owner_username
            """,
            (invite_hash, owner_display, owner_username, now),
        )
        conn.commit()


def get_invite_owner(invite_hash: str) -> Optional[Dict[str, Any]]:
    if not invite_hash:
        return None
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            "SELECT invite_hash, owner_display, owner_username, created_at FROM invite_owners WHERE invite_hash=?",
            (invite_hash,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "invite_hash": row[0],
        "owner_display": row[1],
        "owner_username": row[2],
        "created_at": row[3],
    }


def list_bot_links(owner_display: Optional[str] = None, owner_username: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Повертає ботів (username + статус), опційно відфільтрованих по власнику.
    """
    conn = _ensure_conn()
    params: List[Any] = []
    where: List[str] = []
    if owner_display:
        where.append("owner_display = ?")
        params.append(owner_display)
    if owner_username:
        where.append("owner_username = ?")
        params.append(owner_username)
    where_sql = ""
    if where:
        where_sql = "WHERE " + " OR ".join(where)
    with _lock:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT username, status, session, title, owner_display, owner_username, last_ts, last_error
            FROM bot_links
            {where_sql}
            ORDER BY username
            """,
            params,
        )
        rows = cur.fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "username": r[0],
                "status": r[1],
                "session": r[2],
                "title": r[3],
                "owner_display": r[4],
                "owner_username": r[5],
                "last_ts": r[6],
                "last_error": r[7],
            }
        )
    return out


def get_bot_link_by_username(username: str) -> Optional[Dict[str, Any]]:
    """
    Повертає один запис про бота за username.
    """
    if not username:
        return None
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT username, status, session, title, owner_display, owner_username, batch_id, last_ts, last_error, raw_url
            FROM bot_links
            WHERE username = ?
            LIMIT 1
            """,
            (username,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "username": row[0],
        "status": row[1],
        "session": row[2],
        "title": row[3],
        "owner_display": row[4],
        "owner_username": row[5],
        "batch_id": row[6],
        "last_ts": row[7],
        "last_error": row[8],
        "raw_url": row[9],
    }


def delete_bot_link(username: str) -> bool:
    if not username:
        return False
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute("DELETE FROM bot_links WHERE username = ?", (username,))
        conn.commit()
        return cur.rowcount > 0


# --------- Sheet projects (Google Sheets per project) ----------

def set_active_sheet(project: str, spreadsheet_id: str, title: Optional[str]) -> None:
    """
    Встановлює активну таблицю для проєкту і додає попередню у архів (якщо була).
    """
    project = (project or "").strip()
    if not project or not spreadsheet_id:
        return
    conn = _ensure_conn()
    now = _now()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            "SELECT active_spreadsheet_id, active_title FROM sheet_projects WHERE project=? LIMIT 1",
            (project,),
        )
        row = cur.fetchone()
        prev_id = row[0] if row else None
        prev_title = row[1] if row else None
        if prev_id:
            cur.execute(
                """
                INSERT INTO sheet_project_archives(project, spreadsheet_id, title, archived_at)
                VALUES (?,?,?,?)
                """,
                (project, prev_id, prev_title, now),
            )
        cur.execute(
            """
            INSERT INTO sheet_projects(project, active_spreadsheet_id, active_title, updated_at)
            VALUES (?,?,?,?)
            ON CONFLICT(project) DO UPDATE SET
                active_spreadsheet_id=excluded.active_spreadsheet_id,
                active_title=excluded.active_title,
                updated_at=excluded.updated_at
            """,
            (project, spreadsheet_id, title, now),
        )
        conn.commit()


def get_active_sheet(project: str) -> Optional[Dict[str, Any]]:
    project = (project or "").strip()
    if not project:
        return None
    conn = _ensure_conn()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT project, active_spreadsheet_id, active_title, updated_at
            FROM sheet_projects
            WHERE project=? LIMIT 1
            """,
            (project,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "project": row[0],
        "spreadsheet_id": row[1],
        "title": row[2],
        "updated_at": row[3],
    }


def list_archived_sheets(project: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = _ensure_conn()
    params: list[Any] = []
    where = ""
    if project:
        where = "WHERE project=?"
        params.append(project)
    with _lock:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT id, project, spreadsheet_id, title, archived_at
            FROM sheet_project_archives
            {where}
            ORDER BY archived_at DESC, id DESC
            """,
            params,
        )
        rows = cur.fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r[0],
                "project": r[1],
                "spreadsheet_id": r[2],
                "title": r[3],
                "archived_at": r[4],
            }
        )
    return out


def list_sheet_projects() -> List[str]:
    """
    Повертає унікальні назви проєктів, для яких є активні або архівні таблиці.
    """
    conn = _ensure_conn()
    res: set[str] = set()
    with _lock:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT project FROM sheet_projects")
        for (p,) in cur.fetchall():
            if p:
                res.add(str(p))
        cur.execute("SELECT DISTINCT project FROM sheet_project_archives")
        for (p,) in cur.fetchall():
            if p:
                res.add(str(p))
    return sorted(res)
