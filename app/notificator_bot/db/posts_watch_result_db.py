from __future__ import annotations

import os
import sqlite3
import threading
import logging
import json
import hashlib
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
import time
from zoneinfo import ZoneInfo

from sqlalchemy import select, update, func, case
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.services import channel_db
from app.services.membership_db import get_any_session_for_channel
from app.services.channel_db import get_network_for_channel
from admin_bot.db import models as m
from app.notificator_bot.db.posts_watch_result_models import (
    Base,
    get_engine,
    init_schema,
    session_scope,
    WatchPost,
    WatchEvent,
    WatchGroup,
    WatchCandidate,
)

log = logging.getLogger("services.posts_watch_result_db")

__all__ = [
    "init",
    "create_watch",
    "mark_matched",
    "mark_done_views",
    "mark_done_deleted",
    "mark_expired",
    "mark_unmatched_after_edit",
    "cancel_watch",
    "get_pending_by_channel",
    "list_active_channels",
    "list_due_coverage",
    "list_due_pending_expire",
    "find_active_duplicate",
    "get_watch_source_url",
    "get_watch_created_by",
    "get_watch_created_via",
    "create_watch_group",
    "fetch_pending_by_group",
    "fetch_watches_by_group",
    "insert_watch_event",
    "fetch_unsent_events",
    "mark_event_sent",
    # кандидати
    "insert_watch_candidate",
    "list_watch_candidates",
    "list_group_watch_candidates",
    "list_candidates_by_hash",
    "get_watch_candidate",
    "set_watch_candidate_status",
    "accept_watch_candidate",
    "get_watch_expected_links",
    "get_watch_expected_text",
    "raw_connection",
    "DuplicateWatchError",
]

_DB_PATH = (
    os.environ.get("POSTS_WATCH_RESULT_DB_PATH")
    or os.environ.get("DB_PATH")
    or "post_watchdog.sqlite3"
)

_engine: Optional[Engine] = None
_conn: Optional[sqlite3.Connection] = None
_lock = threading.Lock()

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def _now() -> str:
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _coverage_hours_default() -> float:
    m = os.getenv("WATCH_COVERAGE_MINUTES")
    if m:
        try:
            return float(m) / 60.0
        except Exception:
            pass
    h = os.getenv("WATCH_COVERAGE_HOURS", "24")
    try:
        return float(h)
    except Exception:
        return 24.0


def _calc_coverage_at(hours_after: float | None = None) -> Optional[str]:
    hrs = hours_after if hours_after is not None else _coverage_hours_default()
    try:
        dt = datetime.now(MOSCOW_TZ) + timedelta(hours=hrs)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _candidate_expires_at(days: float = 1.0) -> str:
    try:
        dt = datetime.now(MOSCOW_TZ) + timedelta(days=days)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return _now()


def calc_text_hash(text: str | None) -> str:
    if not text:
        return ""
    try:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()
    except Exception:
        return ""


def _ensure_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        raise RuntimeError("posts_watch_result_db not initialized; call init() first")
    return _conn


def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == col for row in cur.fetchall())


def init() -> None:
    global _conn, _engine
    if _conn is not None:
        return

    _engine = get_engine()
    log.debug("[posts_watch_result_db.init] Using DB: %s", _DB_PATH)
    # ORM: створимо таблиці, якщо їх немає (додаткові ALTER нижче для зворотної сумісності)
    init_schema()

    _conn = _engine.raw_connection()

    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watch_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id BIGINT NOT NULL,
            group_id BIGINT,
            template_id BIGINT,
            expected_text_hash TEXT,
            expected_text_norm_len INTEGER,
            expected_links_json TEXT,
            expected_media_fingerprint TEXT,
            time_window_start TEXT,
            time_window_end TEXT,
            status TEXT,
            matched_message_id BIGINT,
            matched_at TEXT,
            coverage_check_at TEXT,
            final_views INTEGER,
            deleted_at TEXT,
            created_at TEXT,
            updated_at TEXT,
            matched_session TEXT,
            source_url TEXT,
            created_by BIGINT,
            created_via TEXT,
            project TEXT,
            admin_id INTEGER,
            network_id INTEGER,
            posted_at TEXT,
            views_at_post INTEGER,
            subs_at_post INTEGER,
            cpm_at_post FLOAT,
            price_at_post FLOAT
        )
        """
    )

    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watch_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT,
            title TEXT,
            created_by BIGINT,
            created_via TEXT,
            created_at TEXT NOT NULL,
            admin_id INTEGER,
            network_id INTEGER,
            actual_views INTEGER,
            actual_price FLOAT,
            actual_cpm FLOAT,
            subscribers INTEGER
        )
        """
    )

    if not _has_column(_conn, "watch_posts", "group_id"):
        _conn.execute("ALTER TABLE watch_posts ADD COLUMN group_id BIGINT")

    if not _has_column(_conn, "watch_posts", "source_url"):
        _conn.execute("ALTER TABLE watch_posts ADD COLUMN source_url TEXT")

    if not _has_column(_conn, "watch_posts", "created_by"):
        _conn.execute("ALTER TABLE watch_posts ADD COLUMN created_by BIGINT")

    if not _has_column(_conn, "watch_posts", "created_via"):
        _conn.execute("ALTER TABLE watch_posts ADD COLUMN created_via TEXT")

    if not _has_column(_conn, "watch_posts", "project"):
        _conn.execute("ALTER TABLE watch_posts ADD COLUMN project TEXT")

    if not _has_column(_conn, "watch_posts", "admin_id"):
        _conn.execute("ALTER TABLE watch_posts ADD COLUMN admin_id INTEGER")

    if not _has_column(_conn, "watch_posts", "network_id"):
        _conn.execute("ALTER TABLE watch_posts ADD COLUMN network_id INTEGER")

    if not _has_column(_conn, "watch_posts", "posted_at"):
        _conn.execute("ALTER TABLE watch_posts ADD COLUMN posted_at TEXT")

    if not _has_column(_conn, "watch_posts", "views_at_post"):
        _conn.execute("ALTER TABLE watch_posts ADD COLUMN views_at_post INTEGER")

    if not _has_column(_conn, "watch_posts", "subs_at_post"):
        _conn.execute("ALTER TABLE watch_posts ADD COLUMN subs_at_post INTEGER")

    if not _has_column(_conn, "watch_posts", "cpm_at_post"):
        _conn.execute("ALTER TABLE watch_posts ADD COLUMN cpm_at_post FLOAT")

    if not _has_column(_conn, "watch_posts", "price_at_post"):
        _conn.execute("ALTER TABLE watch_posts ADD COLUMN price_at_post FLOAT")

    if not _has_column(_conn, "watch_groups", "admin_id"):
        _conn.execute("ALTER TABLE watch_groups ADD COLUMN admin_id INTEGER")

    if not _has_column(_conn, "watch_groups", "network_id"):
        _conn.execute("ALTER TABLE watch_groups ADD COLUMN network_id INTEGER")

    if not _has_column(_conn, "watch_groups", "actual_views"):
        _conn.execute("ALTER TABLE watch_groups ADD COLUMN actual_views INTEGER")

    if not _has_column(_conn, "watch_groups", "actual_price"):
        _conn.execute("ALTER TABLE watch_groups ADD COLUMN actual_price FLOAT")

    if not _has_column(_conn, "watch_groups", "actual_cpm"):
        _conn.execute("ALTER TABLE watch_groups ADD COLUMN actual_cpm FLOAT")

    if not _has_column(_conn, "watch_groups", "subscribers"):
        _conn.execute("ALTER TABLE watch_groups ADD COLUMN subscribers INTEGER")

    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watch_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            watch_id BIGINT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT,
            created_at TEXT NOT NULL,
            sent_to BIGINT,
            sent_at TEXT
        )
        """
    )

    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watch_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            watch_id BIGINT NOT NULL,
            channel_id BIGINT,
            message_id BIGINT,
            text_hash TEXT,
            similarity REAL,
            message_text TEXT,
            status TEXT,
            created_at TEXT,
            expires_at TEXT
        )
        """
    )

    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_channel ON watch_posts(channel_id)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_status ON watch_posts(status)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_covcheck ON watch_posts(coverage_check_at)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_matched_session ON watch_posts(matched_session)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_created_by ON watch_posts(created_by)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_group ON watch_posts(group_id)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_posted_at ON watch_posts(posted_at)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_admin ON watch_posts(admin_id)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wp_network ON watch_posts(network_id)")

    _conn.execute("CREATE INDEX IF NOT EXISTS idx_we_sent_at ON watch_events(sent_at)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_we_unsent ON watch_events(sent_at, id)")

    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wc_watch ON watch_candidates(watch_id)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wc_status ON watch_candidates(status)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wc_expires ON watch_candidates(expires_at)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wc_text_hash ON watch_candidates(text_hash)")

    _conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_active_watch
        ON watch_posts(channel_id, template_id, expected_text_hash)
        WHERE status IN ('pending','matched')
        """
    )
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wg_admin ON watch_groups(admin_id)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_wg_network ON watch_groups(network_id)")

    if not _has_column(_conn, "watch_candidates", "text_hash"):
        _conn.execute("ALTER TABLE watch_candidates ADD COLUMN text_hash TEXT")

    _conn.commit()
    log.debug("[posts_watch_result_db.init] DDL applied")


class DuplicateWatchError(RuntimeError):
    pass


def create_watch_group(
    project: Optional[str] = None,
    title: Optional[str] = None,
    created_by: Optional[int] = None,
    created_via: Optional[str] = None,
    admin_id: Optional[int] = None,
    network_id: Optional[int] = None,
) -> int:
    now = _now()
    with session_scope() as session:
        obj = WatchGroup(
            project=project,
            title=title,
            created_by=created_by,
            created_via=created_via,
            created_at=now,
            admin_id=admin_id,
            network_id=network_id,
        )
        session.add(obj)
        session.flush()
        gid = int(obj.id)
    log.debug(
        "[posts_watch_result_db.create_watch_group] group_id=%s project=%s title=%s created_by=%s via=%s admin_id=%s network_id=%s",
        gid, project, title, created_by, created_via, admin_id, network_id,
    )
    return gid


def create_watch(
    channel_id: int,
    group_id: Optional[int] = None,
    template_id: Optional[int] = None,
    expected_text_hash: Optional[str] = None,
    expected_text_norm_len: Optional[int] = None,
    expected_links_json: Optional[str] = None,
    expected_media_fingerprint: Optional[str] = None,
    time_window_start: Optional[str] = None,
    time_window_end: Optional[str] = None,
    source_url: Optional[str] = None,
    created_by: Optional[int] = None,
    created_via: Optional[str] = None,
    project: Optional[str] = None,
    admin_id: Optional[int] = None,
    network_id: Optional[int] = None,
    posted_at: Optional[str] = None,
    views_at_post: Optional[int] = None,
    subs_at_post: Optional[int] = None,
    cpm_at_post: Optional[float] = None,
    price_at_post: Optional[float] = None,
) -> int:
    now = _now()
    # Якщо не передали admin/network, спробуємо визначити за каналом через network_channels
    if admin_id is None or network_id is None:
        try:
            net = get_network_for_channel(channel_id)
            if net:
                net_id, adm_id = net
                if network_id is None:
                    network_id = net_id
                if admin_id is None:
                    admin_id = adm_id
        except Exception:
            log.debug("create_watch: get_network_for_channel failed", exc_info=True)
    try:
        with session_scope() as session:
            obj = WatchPost(
                channel_id=channel_id,
                group_id=group_id,
                template_id=template_id,
                expected_text_hash=expected_text_hash,
                expected_text_norm_len=expected_text_norm_len,
                expected_links_json=expected_links_json,
                expected_media_fingerprint=expected_media_fingerprint,
                time_window_start=time_window_start,
                time_window_end=time_window_end,
                status="pending",
                created_at=now,
                updated_at=now,
                source_url=source_url,
                created_by=created_by,
                created_via=created_via,
                project=project,
                admin_id=admin_id,
                network_id=network_id,
                posted_at=posted_at,
                views_at_post=views_at_post,
                subs_at_post=subs_at_post,
                cpm_at_post=cpm_at_post,
                price_at_post=price_at_post,
            )
            session.add(obj)
            session.flush()
            wid = int(obj.id)
    except IntegrityError as e:
        raise DuplicateWatchError(
            f"Duplicate active watch for channel={channel_id}, template={template_id}"
        ) from e

    log.info(
        "[posts_watch_result_db.create_watch] watch_id=%s channel_id=%s status=pending group_id=%s source_url=%s created_by=%s created_via=%s",
        wid, channel_id, group_id, source_url, created_by, created_via,
    )
    return wid


def get_watch_source_url(watch_id: int) -> Optional[str]:
    with session_scope() as session:
        row = session.execute(
            select(WatchPost.source_url).where(WatchPost.id == watch_id).limit(1)
        ).first()
    if not row:
        return None
    val = row[0]
    return str(val) if val else None


def get_watch_created_by(watch_id: int) -> Optional[int]:
    with session_scope() as session:
        row = session.execute(
            select(WatchPost.created_by).where(WatchPost.id == watch_id).limit(1)
        ).first()
    if not row or row[0] is None:
        return None
    try:
        return int(row[0])
    except Exception:
        return None


def get_watch_created_via(watch_id: int) -> Optional[str]:
    with session_scope() as session:
        row = session.execute(
            select(WatchPost.created_via).where(WatchPost.id == watch_id).limit(1)
        ).first()
    if not row:
        return None
    val = row[0]
    return str(val) if val else None


def get_watch_expected_links(watch_id: int) -> List[str]:
    with session_scope() as session:
        row = session.execute(
            select(WatchPost.expected_links_json).where(WatchPost.id == watch_id).limit(1)
        ).first()
    if not row or not row[0]:
        return []
    try:
        data = json.loads(row[0])
        if isinstance(data, list):
            return list(dict.fromkeys(str(x) for x in data if x))
    except Exception:
        pass
    return []


def get_watch_expected_text(watch_id: int) -> Optional[str]:
    with session_scope() as session:
        row = session.execute(
            select(WatchPost.expected_text_hash).where(WatchPost.id == watch_id).limit(1)
        ).first()
    if not row:
        return None
    return row[0]


def insert_watch_event(watch_id: int, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    now = _now()
    try:
        payload_json = json.dumps(payload or {}, ensure_ascii=False)
    except Exception:
        payload_json = "{}"
    with session_scope() as session:
        obj = WatchEvent(
            watch_id=int(watch_id),
            event_type=str(event_type),
            payload_json=payload_json,
            created_at=now,
        )
        session.add(obj)
        session.flush()
        if log.isEnabledFor(logging.DEBUG):
            log.debug(
                "watch_event inserted id=%s watch_id=%s type=%s created_at=%s",
                obj.id,
                watch_id,
                event_type,
                now,
            )


# --- Candidates (similar posts) ------------------------------------------------


def insert_watch_candidate(
    watch_id: int,
    channel_id: Optional[int],
    message_id: Optional[int],
    similarity: Optional[float],
    message_text: Optional[str],
    ttl_days: float = 1.0,
    expires_at: Optional[str] = None,
    status: str = "pending",
) -> int:
    now = _now()
    expires_at = expires_at or _candidate_expires_at(ttl_days)
    text_hash = calc_text_hash(message_text)
    with session_scope() as session:
        obj = WatchCandidate(
            watch_id=int(watch_id),
            channel_id=channel_id,
            message_id=message_id,
            text_hash=text_hash,
            similarity=similarity,
            message_text=message_text,
            status=status,
            created_at=now,
            expires_at=expires_at,
        )
        session.add(obj)
        session.flush()
        cid = int(obj.id)
    if log.isEnabledFor(logging.DEBUG):
        log.debug(
            "watch_candidate inserted id=%s wid=%s cid=%s mid=%s sim=%.3f expires=%s",
            cid,
            watch_id,
            channel_id,
            message_id,
            similarity if similarity is not None else -1,
            expires_at,
        )
    return cid


def list_watch_candidates(watch_id: int, status: str = "pending") -> List[Dict[str, Any]]:
    now = _now()
    with session_scope() as session:
        rows = session.execute(
            select(
                WatchCandidate.watch_id,
                WatchCandidate.id,
                WatchCandidate.channel_id,
                WatchCandidate.message_id,
                WatchCandidate.text_hash,
                WatchCandidate.similarity,
                WatchCandidate.message_text,
                WatchCandidate.created_at,
                WatchCandidate.expires_at,
                WatchCandidate.status,
            ).where(
                WatchCandidate.watch_id == watch_id,
                WatchCandidate.status == status,
                func.coalesce(WatchCandidate.expires_at, now) >= now,
            )
            .order_by(WatchCandidate.id.desc())
        ).all()
    return [
        {
            "watch_id": r.watch_id,
            "id": int(r.id),
            "channel_id": r.channel_id,
            "message_id": r.message_id,
            "text_hash": r.text_hash,
            "similarity": r.similarity,
            "message_text": r.message_text,
            "created_at": r.created_at,
            "expires_at": r.expires_at,
            "status": r.status,
        }
        for r in rows
    ]


def list_group_watch_candidates(
    watch_ids: List[int],
    status: str = "pending",
) -> List[Dict[str, Any]]:
    """
    Повертає кандидати для кількох watch_id одразу (без прострочених).
    """
    if not watch_ids:
        return []
    now = _now()
    with session_scope() as session:
        rows = session.execute(
            select(
                WatchCandidate.watch_id,
                WatchCandidate.id,
                WatchCandidate.channel_id,
                WatchCandidate.message_id,
                WatchCandidate.text_hash,
                WatchCandidate.similarity,
                WatchCandidate.message_text,
                WatchCandidate.created_at,
                WatchCandidate.expires_at,
                WatchCandidate.status,
            ).where(
                WatchCandidate.watch_id.in_(watch_ids),
                WatchCandidate.status == status,
                func.coalesce(WatchCandidate.expires_at, now) >= now,
            )
            .order_by(WatchCandidate.id.desc())
        ).all()
    return [
        {
            "watch_id": r.watch_id,
            "id": int(r.id),
            "channel_id": r.channel_id,
            "message_id": r.message_id,
            "text_hash": r.text_hash,
            "similarity": r.similarity,
            "message_text": r.message_text,
            "created_at": r.created_at,
            "expires_at": r.expires_at,
            "status": r.status,
        }
        for r in rows
    ]


def list_candidates_by_hash(text_hash: str, status: str = "pending") -> List[Dict[str, Any]]:
    """
    Повертає кандидатів за text_hash (без прострочених), опційно по статусу.
    """
    if not text_hash:
        return []
    now = _now()
    with session_scope() as session:
        rows = session.execute(
            select(
                WatchCandidate.watch_id,
                WatchCandidate.id,
                WatchCandidate.channel_id,
                WatchCandidate.message_id,
                WatchCandidate.text_hash,
                WatchCandidate.similarity,
                WatchCandidate.message_text,
                WatchCandidate.created_at,
                WatchCandidate.expires_at,
                WatchCandidate.status,
            ).where(
                WatchCandidate.text_hash == text_hash,
                WatchCandidate.status == status,
                func.coalesce(WatchCandidate.expires_at, now) >= now,
            )
            .order_by(WatchCandidate.id.desc())
        ).all()
    return [
        {
            "watch_id": r.watch_id,
            "id": int(r.id),
            "channel_id": r.channel_id,
            "message_id": r.message_id,
            "text_hash": r.text_hash,
            "similarity": r.similarity,
            "message_text": r.message_text,
            "created_at": r.created_at,
            "expires_at": r.expires_at,
            "status": r.status,
        }
        for r in rows
    ]


def get_watch_candidate(candidate_id: int) -> Optional[Dict[str, Any]]:
    with session_scope() as session:
        row = session.execute(
            select(
                WatchCandidate.id,
                WatchCandidate.watch_id,
                WatchCandidate.channel_id,
                WatchCandidate.message_id,
                WatchCandidate.text_hash,
                WatchCandidate.similarity,
                WatchCandidate.message_text,
                WatchCandidate.created_at,
                WatchCandidate.expires_at,
                WatchCandidate.status,
            ).where(WatchCandidate.id == candidate_id)
        ).first()
    if not row:
        return None
    return {
        "id": int(row.id),
        "watch_id": int(row.watch_id),
        "channel_id": row.channel_id,
        "message_id": row.message_id,
        "text_hash": row.text_hash,
        "similarity": row.similarity,
        "message_text": row.message_text,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
        "status": row.status,
    }


def set_watch_candidate_status(candidate_id: int, status: str) -> bool:
    with session_scope() as session:
        res = session.execute(
            update(WatchCandidate)
            .where(WatchCandidate.id == candidate_id)
            .values(status=status)
        )
        updated = res.rowcount or 0
    return updated > 0


def _pending_candidates_by_hash(text_hash: str) -> List[Dict[str, Any]]:
    if not text_hash:
        return []
    now = _now()
    with session_scope() as session:
        rows = session.execute(
            select(
                WatchCandidate.id,
                WatchCandidate.watch_id,
                WatchCandidate.channel_id,
                WatchCandidate.message_id,
                WatchCandidate.text_hash,
                WatchCandidate.similarity,
                WatchCandidate.message_text,
                WatchCandidate.created_at,
                WatchCandidate.expires_at,
                WatchCandidate.status,
            ).where(
                WatchCandidate.text_hash == text_hash,
                WatchCandidate.status == "pending",
                func.coalesce(WatchCandidate.expires_at, now) >= now,
            )
        ).all()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": int(r.id),
                "watch_id": int(r.watch_id),
                "channel_id": r.channel_id,
                "message_id": r.message_id,
                "text_hash": r.text_hash,
                "similarity": r.similarity,
                "message_text": r.message_text,
                "created_at": r.created_at,
                "expires_at": r.expires_at,
                "status": r.status,
            }
        )
    return out


def accept_watch_candidate(candidate_id: int, matched_session: Optional[str] = None) -> bool:
    """
    Позначає кандидат як прийнятий, ставить watch у matched і записує подію matched.
    Якщо є інші pending кандидати з тим самим text_hash — матчить їх теж (одним натисканням).
    """
    cand = get_watch_candidate(candidate_id)
    if not cand:
        return False
    if cand.get("status") != "pending":
        return False
    text_hash = cand.get("text_hash") or ""
    candidates = _pending_candidates_by_hash(text_hash) if text_hash else [cand]

    any_ok = False
    for c in candidates:
        watch_id = c.get("watch_id")
        msg_id = c.get("message_id")
        channel_id = c.get("channel_id")
        cid = c.get("id")
        if not watch_id or not msg_id:
            continue
        coverage_at = _calc_coverage_at()
        try:
            force_mark_matched(
                watch_id,
                int(msg_id),
                coverage_at,
                matched_session=matched_session,
            )
            insert_watch_event(
                watch_id,
                "matched",
                {
                    "watch_id": watch_id,
                    "channel_id": channel_id,
                    "message_id": msg_id,
                    "session": matched_session,
                    "via": "manual_candidate",
                    "candidate_id": cid,
                    "text_hash": text_hash,
                },
            )
            set_watch_candidate_status(int(cid), "accepted")
            any_ok = True
        except Exception as e:
            log.exception("accept_watch_candidate failed for candidate_id=%s watch_id=%s: %s", cid, watch_id, e)
            continue

    return any_ok


def fetch_pending_by_group(group_id: int) -> List[Dict[str, Any]]:
    with session_scope() as session:
        rows = session.execute(
            select(
                WatchPost.id,
                WatchPost.channel_id,
                WatchPost.source_url,
                WatchPost.project,
                WatchPost.created_at,
            )
            .where(WatchPost.group_id == int(group_id), WatchPost.status == "pending")
            .order_by(WatchPost.id.asc())
        ).all()
    if log.isEnabledFor(logging.DEBUG):
        log.debug("fetch_pending_by_group: group_id=%s fetched=%s", group_id, len(rows))
    result: List[Dict[str, Any]] = []
    for r in rows:
        result.append(
            {
                "id": int(r.id),
                "channel_id": int(r.channel_id),
                "source_url": str(r.source_url) if r.source_url else None,
                "project": r.project,
                "created_at": str(r.created_at or ""),
            }
        )
    return result


def fetch_watches_by_group(group_id: int) -> List[Dict[str, Any]]:
    with session_scope() as session:
        rows = session.execute(
            select(
                WatchPost.id,
                WatchPost.channel_id,
                WatchPost.source_url,
                WatchPost.project,
                WatchPost.status,
                WatchPost.created_at,
                WatchPost.updated_at,
                WatchPost.deleted_at,
                WatchPost.final_views,
            )
            .where(WatchPost.group_id == int(group_id))
            .order_by(WatchPost.id.asc())
        ).all()
    result: List[Dict[str, Any]] = []
    for r in rows:
        result.append(
            {
                "id": int(r.id),
                "channel_id": int(r.channel_id),
                "source_url": str(r.source_url) if r.source_url else None,
                "project": r.project,
                "status": r.status,
                "created_at": str(r.created_at or ""),
                "updated_at": str(r.updated_at or ""),
                "deleted_at": str(r.deleted_at or ""),
                "final_views": r.final_views,
            }
        )
    if log.isEnabledFor(logging.DEBUG):
        log.debug("fetch_watches_by_group: group_id=%s fetched=%s", group_id, len(result))
    return result


def fetch_unsent_events(limit: int = 100) -> List[Tuple[int, int, str, str, str]]:
    with session_scope() as session:
        rows = session.execute(
            select(
                WatchEvent.id,
                WatchEvent.watch_id,
                WatchEvent.event_type,
                WatchEvent.payload_json,
                WatchEvent.created_at,
            )
            .where(WatchEvent.sent_at.is_(None))
            .order_by(WatchEvent.id.asc())
            .limit(int(limit))
        ).all()
    if log.isEnabledFor(logging.DEBUG):
        log.debug("fetch_unsent_events: fetched=%s", len(rows))
    return [
        (int(r.id), int(r.watch_id), str(r.event_type), str(r.payload_json or ""), str(r.created_at or ""))
        for r in rows
    ]


def mark_event_sent(event_id: int, sent_to: int) -> None:
    now = _now()
    with session_scope() as session:
        res = session.execute(
            update(WatchEvent)
            .where(WatchEvent.id == int(event_id), WatchEvent.sent_at.is_(None))
            .values(sent_to=int(sent_to), sent_at=now)
        )
        if log.isEnabledFor(logging.DEBUG):
            log.debug("mark_event_sent: id=%s sent_to=%s updated=%s at=%s", event_id, sent_to, res.rowcount, now)


def mark_matched(
    watch_id: int,
    message_id: int,
    coverage_check_at: Optional[str],
    matched_session: Optional[str] = None,
) -> None:
    now = _now()
    with session_scope() as session:
        session.execute(
            update(WatchPost)
            .where(WatchPost.id == watch_id, WatchPost.status == "pending")
            .values(
                matched_message_id=message_id,
                matched_at=now,
                coverage_check_at=coverage_check_at,
                matched_session=matched_session,
                status="matched",
                updated_at=now,
            )
        )
    log.info(
        "[posts_watch_result_db.mark_matched] watch_id=%s msg_id=%s status=matched cov_at=%s session=%s",
        watch_id, message_id, coverage_check_at, matched_session,
    )


def mark_done_views(watch_id: int, final_views: Optional[int]) -> None:
    now = _now()
    with session_scope() as session:
        wp = session.execute(
            select(WatchPost.network_id, WatchPost.admin_id, WatchPost.group_id).where(WatchPost.id == watch_id).limit(1)
        ).first()
        session.execute(
            update(WatchPost)
            .where(WatchPost.id == watch_id, WatchPost.status == "matched")
            .values(final_views=final_views, status="done", updated_at=now)
        )
        # оновлюємо фактичні метрики сітки, якщо відомий network_id
        if wp and wp[0]:
            net_id = int(wp[0])
            views_sum, spent_sum = session.execute(
                select(
                    func.sum(
                        func.coalesce(WatchPost.final_views, WatchPost.views_at_post, 0)
                    ),
                    func.sum(
                        func.coalesce(
                            WatchPost.price_at_post,
                            func.coalesce(
                                WatchPost.cpm_at_post, 0
                            )
                            * func.coalesce(WatchPost.final_views, WatchPost.views_at_post, 0)
                            / 1000.0,
                        )
                    ),
                ).where(
                    WatchPost.network_id == net_id,
                    WatchPost.status == "done",
                )
            ).first()
            try:
                views_sum = int(views_sum or 0)
            except Exception:
                views_sum = 0
            try:
                spent_sum = float(spent_sum or 0.0)
            except Exception:
                spent_sum = 0.0
            actual_cpm = None
            if views_sum > 0:
                actual_cpm = spent_sum * 1000.0 / float(views_sum)
            session.execute(
                update(m.Network)
                .where(m.Network.id == net_id)
                .values(
                    actual_views=views_sum,
                    actual_price=spent_sum,
                    actual_cpm=actual_cpm,
                    updated_at=int(time.time()),
                )
            )
        # оновлюємо фактичні метрики по групі вотчу (реклама)
        if wp and wp[2]:
            gid = int(wp[2])
            g_views, g_spent = session.execute(
                select(
                    func.sum(func.coalesce(WatchPost.final_views, WatchPost.views_at_post, 0)),
                    func.sum(
                        func.coalesce(
                            WatchPost.price_at_post,
                            func.coalesce(WatchPost.cpm_at_post, 0)
                            * func.coalesce(WatchPost.final_views, WatchPost.views_at_post, 0)
                            / 1000.0,
                        )
                    ),
                ).where(
                    WatchPost.group_id == gid,
                    WatchPost.status == "done",
                )
            ).first()
            try:
                g_views = int(g_views or 0)
            except Exception:
                g_views = 0
            try:
                g_spent = float(g_spent or 0.0)
            except Exception:
                g_spent = 0.0
            g_cpm = None
            if g_views > 0:
                g_cpm = g_spent * 1000.0 / float(g_views)
            session.execute(
                update(WatchGroup)
                .where(WatchGroup.id == gid)
                .values(
                    actual_views=g_views,
                    actual_price=g_spent,
                    actual_cpm=g_cpm,
                )
            )
    log.info("[posts_watch_result_db.mark_done_views] watch_id=%s final_views=%s status=done", watch_id, final_views)


def set_watch_group_subscribers(group_id: int, subscribers: int) -> None:
    """Задає manual subscribers для групи (реклами)."""
    with session_scope() as session:
        session.execute(
            update(WatchGroup)
            .where(WatchGroup.id == group_id)
            .values(subscribers=int(subscribers))
        )
    log.info("set_watch_group_subscribers group_id=%s subscribers=%s", group_id, subscribers)


def mark_done_deleted(watch_id: int) -> Optional[str]:
    now = _now()
    with session_scope() as session:
        row = session.execute(
            select(WatchPost.status).where(WatchPost.id == watch_id).limit(1)
        ).first()
        if not row:
            return None
        status = (row[0] or "").lower()

        if status == "done":
            session.execute(
                update(WatchPost)
                .where(WatchPost.id == watch_id, WatchPost.status == "done")
                .values(deleted_at=func.coalesce(WatchPost.deleted_at, now), updated_at=now)
            )
            log.info("[posts_watch_result_db.mark_done_deleted] watch_id=%s deleted_at set, status kept as done", watch_id)
            return status

        session.execute(
            update(WatchPost)
            .where(WatchPost.id == watch_id, WatchPost.status.in_(["matched", "deleted", "edited"]))
            .values(deleted_at=func.coalesce(WatchPost.deleted_at, now), status="deleted", updated_at=now)
        )
    log.info("[posts_watch_result_db.mark_done_deleted] watch_id=%s deleted status=deleted", watch_id)
    return status


def find_matched_by_message(channel_id: int, message_id: int) -> list[int]:
    with session_scope() as session:
        rows = session.execute(
            select(WatchPost.id).where(
                WatchPost.status.in_(["matched", "done", "deleted", "edited"]),
                WatchPost.channel_id == channel_id,
                WatchPost.matched_message_id == message_id,
            )
        ).all()
    return [int(r.id) for r in rows]


def mark_expired(watch_id: int) -> None:
    now = _now()
    with session_scope() as session:
        session.execute(
            update(WatchPost)
            .where(WatchPost.id == watch_id, WatchPost.status == "pending")
            .values(status="expired", updated_at=now)
        )
    log.info("[posts_watch_result_db.mark_expired] watch_id=%s status=expired", watch_id)


def mark_unmatched_after_edit(watch_id: int) -> None:
    now = _now()
    with session_scope() as session:
        session.execute(
            update(WatchPost)
            .where(WatchPost.id == watch_id, WatchPost.status.in_(["matched", "done", "edited"]))
            .values(
                status=case(
                    (WatchPost.status == "matched", "expired"),
                    else_=WatchPost.status,
                ),
                coverage_check_at=None,
                updated_at=now,
            )
        )
    log.info("[posts_watch_result_db.mark_unmatched_after_edit] watch_id=%s edited->unmatched", watch_id)


def cancel_watch(watch_id: int) -> None:
    now = _now()
    with session_scope() as session:
        session.execute(
            update(WatchPost)
            .where(WatchPost.id == watch_id, WatchPost.status.in_(["pending", "matched"]))
            .values(status="cancelled", updated_at=now)
        )
    log.info("[posts_watch_result_db.cancel_watch] watch_id=%s status=cancelled", watch_id)


def get_pending_by_channel(channel_id: int) -> List[Dict[str, Any]]:
    with session_scope() as session:
        rows = session.execute(
            select(
                WatchPost.id,
                WatchPost.template_id,
                WatchPost.expected_text_hash,
                WatchPost.expected_text_norm_len,
                WatchPost.expected_links_json,
                WatchPost.expected_media_fingerprint,
                WatchPost.time_window_start,
                WatchPost.time_window_end,
            ).where(WatchPost.channel_id == channel_id, WatchPost.status == "pending")
        ).all()
    return [
        {
            "id": r.id,
            "template_id": r.template_id,
            "expected_text_hash": r.expected_text_hash,
            "expected_text_norm_len": r.expected_text_norm_len,
            "expected_links_json": r.expected_links_json,
            "expected_media_fingerprint": r.expected_media_fingerprint,
            "time_window_start": r.time_window_start,
            "time_window_end": r.time_window_end,
        }
        for r in rows
    ]


def list_active_channels() -> List[int]:
    with session_scope() as session:
        rows = session.execute(
            select(WatchPost.channel_id).where(WatchPost.status.in_(["pending", "matched"])).distinct()
        ).all()
    return [int(r.channel_id) for r in rows]


def list_due_coverage(now_ts: Optional[str] = None) -> List[Tuple[int, int, int, Optional[str]]]:
    if not now_ts:
        now_ts = _now()
    with session_scope() as session:
        rows = session.execute(
            select(
                WatchPost.id,
                WatchPost.channel_id,
                WatchPost.matched_message_id,
                WatchPost.matched_session,
            ).where(
                WatchPost.status == "matched",
                WatchPost.coverage_check_at <= now_ts,
            )
        ).all()
    out: List[Tuple[int, int, int, Optional[str]]] = []
    for r in rows:
        if r.matched_message_id is None:
            continue
        out.append((int(r.id), int(r.channel_id), int(r.matched_message_id), (r.matched_session if r.matched_session is not None else None)))
    return out

def force_mark_matched(
    watch_id: int,
    message_id: int,
    coverage_check_at: Optional[str],
    matched_session: Optional[str] = None,
) -> None:
    """
    Примусово ставить вотч у matched як з pending, так і з expired.
    Використовується для ручного матчу через бота.
    """
    now = _now()
    with session_scope() as session:
        session.execute(
            update(WatchPost)
            .where(WatchPost.id == watch_id, WatchPost.status.in_(["pending", "expired"]))
            .values(
                matched_message_id=message_id,
                matched_at=now,
                coverage_check_at=coverage_check_at,
                matched_session=matched_session,
                status="matched",
                updated_at=now,
            )
        )
    log.info(
        "[posts_watch_result_db.force_mark_matched] watch_id=%s msg_id=%s status=matched (from pending/expired) cov_at=%s session=%s",
        watch_id, message_id, coverage_check_at, matched_session,
    )

def get_watch_channel_id(watch_id: int) -> Optional[int]:
    with session_scope() as session:
        row = session.execute(
            select(WatchPost.channel_id).where(WatchPost.id == watch_id).limit(1)
        ).first()
    if not row or row[0] is None:
        return None
    try:
        return int(row[0])
    except Exception:
        return None

def get_session_for_source_url(source_url: str) -> Optional[str]:
    """
    Знаходить сесію, яка вже працювала з каналом для цього source_url:
      source_url -> channel_id (channel_db.links) -> account (membership.account).
    """
    if not source_url:
        return None
    try:
        cid = channel_db.get_channel_id_by_url(source_url)
    except Exception:
        cid = None
    if not cid:
        return None
    try:
        return get_any_session_for_channel(cid)
    except Exception:
        return None


def list_due_pending_expire(now_ts: Optional[str] = None) -> List[int]:
    if not now_ts:
        now_ts = _now()
    with session_scope() as session:
        rows = session.execute(
            select(WatchPost.id).where(
                WatchPost.status == "pending",
                WatchPost.time_window_end.is_not(None),
                WatchPost.time_window_end != "",
                WatchPost.time_window_end <= now_ts,
            )
        ).all()
    return [int(r.id) for r in rows]


def find_active_duplicate(
    channel_id: int,
    template_id: Optional[int],
    expected_text_hash: Optional[str],
) -> Optional[Dict[str, Any]]:
    with session_scope() as session:
        row = session.execute(
            select(
                WatchPost.id,
                WatchPost.status,
                WatchPost.created_at,
                WatchPost.time_window_end,
                WatchPost.matched_message_id,
            )
            .where(
                WatchPost.channel_id == channel_id,
                WatchPost.template_id == template_id,
                WatchPost.expected_text_hash == expected_text_hash,
                WatchPost.status.in_(["pending", "matched"]),
            )
            .order_by(WatchPost.id.desc())
            .limit(1)
        ).first()
    if not row:
        return None
    return {
        "id": int(row.id),
        "status": str(row.status),
        "created_at": row.created_at,
        "time_window_end": row.time_window_end,
        "matched_message_id": row.matched_message_id,
    }


def raw_connection() -> sqlite3.Connection:
    if _engine is None:
        raise RuntimeError("posts_watch_result_db not initialized; call init() first")
    return _engine.raw_connection()
