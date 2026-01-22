from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select, update, distinct
from sqlalchemy.orm import Session

from app.db import models as m
from app.DAL import channels_operations as cho
from app.DAL.membership_operations import get_any_session_for_channel
from app.utils.time_utils import MOSCOW_TIME_FORMAT, moscow_now, moscow_now_str
from app.db.session import session_scope


def _now_str() -> str:
    return moscow_now_str()


def calc_text_hash(text: str | None) -> str:
    if not text:
        return ""
    try:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()
    except Exception:
        return ""


def _candidate_expires_at(days: float = 1.0) -> str:
    try:
        dt = moscow_now() + timedelta(days=days)
        return dt.strftime(MOSCOW_TIME_FORMAT)
    except Exception:
        return _now_str()


def list_active_channels_db(db: Session) -> List[int]:
    rows = db.execute(
        select(distinct(m.WatchPost.channel_id)).where(m.WatchPost.status.in_(["pending", "matched"]))
    ).all()
    return [int(r[0]) for r in rows if r[0] is not None]


def get_pending_by_channel_db(channel_id: int) -> List[Dict[str, Any]]:
    with session_scope() as db:
        rows = db.execute(
            select(
                m.WatchPost.id,
                m.WatchPost.template_id,
                m.WatchPost.expected_text_hash,
                m.WatchPost.expected_text_norm_len,
                m.WatchPost.expected_links_json,
                m.WatchPost.expected_media_fingerprint,
                m.WatchPost.time_window_start,
                m.WatchPost.time_window_end,
                m.WatchPost.group_id,
            ).where(m.WatchPost.channel_id == channel_id, m.WatchPost.status == "pending")
        ).all()
    return [
        {
            "id": int(r.id),
            "template_id": r.template_id,
            "expected_text_hash": r.expected_text_hash,
            "expected_text_norm_len": r.expected_text_norm_len,
            "expected_links_json": r.expected_links_json,
            "expected_media_fingerprint": r.expected_media_fingerprint,
            "time_window_start": r.time_window_start,
            "time_window_end": r.time_window_end,
            "group_id": r.group_id,
        }
        for r in rows
    ]


def list_due_coverage_db(now_ts: Optional[str] = None) -> List[Tuple[int, int, int, Optional[str]]]:
    current_ts = now_ts or _now_str()
    with session_scope() as db:
        rows = db.execute(
            select(
                m.WatchPost.id,
                m.WatchPost.channel_id,
                m.WatchPost.matched_message_id,
                m.WatchPost.matched_session,
            ).where(
                m.WatchPost.status == "matched",
                m.WatchPost.coverage_check_at <= current_ts,
            )
        ).all()
    out: List[Tuple[int, int, int, Optional[str]]] = []
    for r in rows:
        if r.matched_message_id is None:
            continue
        out.append(
            (
                int(r.id),
                int(r.channel_id),
                int(r.matched_message_id),
                r.matched_session if r.matched_session is not None else None,
            )
        )
    return out




def mark_matched_db(
    watch_id: int,
    message_id: int,
    coverage_check_at: Optional[str],
    matched_session: Optional[str] = None,
) -> None:
    now_val = _now_str()
    with session_scope() as db:
        db.execute(
            update(m.WatchPost)
            .where(m.WatchPost.id == watch_id, m.WatchPost.status == "pending")
            .values(
                matched_message_id=message_id,
                matched_at=now_val,
                coverage_check_at=coverage_check_at,
                matched_session=matched_session,
                status="matched",
                updated_at=now_val,
            )
        )


def mark_done_views_db(watch_id: int, final_views: Optional[int]) -> None:
    now_str = _now_str()
    with session_scope() as db:
        wp = db.execute(
            select(m.WatchPost.network_id, m.WatchPost.admin_id, m.WatchPost.group_id).where(m.WatchPost.id == watch_id).limit(1)
        ).first()
        db.execute(
            update(m.WatchPost)
            .where(m.WatchPost.id == watch_id, m.WatchPost.status == "matched")
            .values(final_views=final_views, status="done", updated_at=now_str)
        )
        if wp and wp[0]:
            net_id = int(wp[0])
            views_sum, spent_sum = db.execute(
                select(
                    func.sum(func.coalesce(m.WatchPost.final_views, m.WatchPost.views_at_post, 0)),
                    func.sum(
                        func.coalesce(
                            m.WatchPost.price_at_post,
                            func.coalesce(m.WatchPost.cpm_at_post, 0)
                            * func.coalesce(m.WatchPost.final_views, m.WatchPost.views_at_post, 0)
                            / 1000.0,
                        )
                    ),
                ).where(
                    m.WatchPost.network_id == net_id,
                    m.WatchPost.status == "done",
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
            actual_cpm = spent_sum * 1000.0 / float(views_sum) if views_sum > 0 else None
            db.execute(
                update(m.Network)
                .where(m.Network.id == net_id)
                .values(
                    actual_views=views_sum,
                    actual_price=spent_sum,
                    actual_cpm=actual_cpm,
                    updated_at=int(moscow_now().timestamp()),
                )
            )
        if wp and wp[2]:
            gid = int(wp[2])
            g_views, g_spent = db.execute(
                select(
                    func.sum(func.coalesce(m.WatchPost.final_views, m.WatchPost.views_at_post, 0)),
                    func.sum(
                        func.coalesce(
                            m.WatchPost.price_at_post,
                            func.coalesce(m.WatchPost.cpm_at_post, 0)
                            * func.coalesce(m.WatchPost.final_views, m.WatchPost.views_at_post, 0)
                            / 1000.0,
                        )
                    ),
                ).where(
                    m.WatchPost.group_id == gid,
                    m.WatchPost.status == "done",
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
            g_cpm = g_spent * 1000.0 / float(g_views) if g_views > 0 else None
            db.execute(
                update(m.WatchGroup)
                .where(m.WatchGroup.id == gid)
                .values(
                    actual_views=g_views,
                    actual_price=g_spent,
                    actual_cpm=g_cpm,
                )
            )


def mark_done_deleted_db(watch_id: int) -> Optional[str]:
    now_val = _now_str()
    with session_scope() as db:
        row = db.execute(select(m.WatchPost.status).where(m.WatchPost.id == watch_id).limit(1)).first()
        if not row:
            return None
        status = (row[0] or "").lower()
        if status == "done":
            db.execute(
                update(m.WatchPost)
                .where(m.WatchPost.id == watch_id, m.WatchPost.status == "done")
                .values(deleted_at=func.coalesce(m.WatchPost.deleted_at, now_val), updated_at=now_val)
            )
            return status
        db.execute(
            update(m.WatchPost)
            .where(m.WatchPost.id == watch_id, m.WatchPost.status.in_(["matched", "deleted", "edited"]))
            .values(deleted_at=func.coalesce(m.WatchPost.deleted_at, now_val), status="deleted", updated_at=now_val)
        )
        return status


def find_matched_by_message_db(channel_id: int, message_id: int) -> List[int]:
    with session_scope() as db:
        rows = db.execute(
            select(m.WatchPost.id).where(
                m.WatchPost.status.in_(["matched", "done", "deleted", "edited"]),
                m.WatchPost.channel_id == channel_id,
                m.WatchPost.matched_message_id == message_id,
            )
        ).all()
    return [int(r.id) for r in rows]


def mark_expired_db(db: Session, watch_id: int) -> None:
    now_val = _now_str()
    try:
        db.execute(
            update(m.WatchPost)
            .where(m.WatchPost.id == watch_id, m.WatchPost.status == "pending")
            .values(status="expired", updated_at=now_val)
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def list_due_pending_expire_db(db: Session, now_ts: Optional[str] = None) -> List[int]:
    now_val = now_ts or _now_str()
    rows = db.execute(
        select(m.WatchPost.id).where(
            m.WatchPost.status == "pending",
            m.WatchPost.time_window_end.is_not(None),
            m.WatchPost.time_window_end != "",
            m.WatchPost.time_window_end <= now_val,
        )
    ).all()
    return [int(r.id) for r in rows]


def list_pending_without_expected_db(db: Session, limit: int = 200) -> List[int]:
    """
    Повертає pending watch_id, у яких немає expected_text_hash (для health-check).
    """
    rows = db.execute(
        select(m.WatchPost.id)
        .where(
            m.WatchPost.status == "pending",
            (m.WatchPost.expected_text_hash.is_(None)) | (m.WatchPost.expected_text_hash == ""),
        )
        .order_by(m.WatchPost.id.desc())
        .limit(int(limit))
    ).all()
    return [int(r.id) for r in rows]


def insert_watch_candidate_db(
    db: Session,
    watch_id: int,
    channel_id: int,
    message_id: int,
    text_hash: str,
    similarity: float,
    message_text: str,
    status: str = "pending_candidate",
    expires_days: Optional[float] = None,
    ttl_days: Optional[float] = None,
) -> int:
    """
    Додає запис у watch_candidates.
    expires_days / ttl_days взаємозамінні; за замовчуванням 1.0.
    """
    exp_days_val = expires_days if expires_days is not None else ttl_days
    if exp_days_val is None:
        exp_days_val = 1.0
    try:
        obj = m.WatchCandidate(
            watch_id=int(watch_id),
            channel_id=int(channel_id),
            message_id=int(message_id),
            text_hash=text_hash,
            similarity=similarity,
            message_text=message_text,
            status=status,
            created_at=_now_str(),
            expires_at=_candidate_expires_at(exp_days_val),
        )
        db.add(obj)
        db.commit()
        return int(obj.id)
    except Exception:
        db.rollback()
        raise


def get_session_for_source_url_db(db: Session, source_url: str) -> Optional[str]:
    """
    Знаходить сесію, яка вже працювала з каналом для цього source_url:
      source_url -> channel_id -> account (membership.account).
    """
    if not source_url:
        return None
    cid = None
    try:
        cid = cho.get_channel_id_by_url(db, source_url)
    except Exception:
        cid = None
    if not cid:
        return None
    return get_any_session_for_channel(db, cid)
