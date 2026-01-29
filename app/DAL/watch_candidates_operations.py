from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
import json

from sqlalchemy import func, select, update

from app.admin_bot.db.session import SessionLocal
from app.admin_bot.db import models as m
from app.DAL import membership_operations as mem_db
from app.DAL.watch_processing_operations import mark_matched as process_mark_matched
from app.DAL.watch_events_operations import insert_watch_event
from app.utils.time_utils import (
    MOSCOW_TIME_FORMAT,
    ensure_moscow_timezone,
    moscow_now,
    moscow_now_str,
)

CANDIDATE_PENDING_STATUS = "pending_candidate"


def _now_str() -> str:
    return moscow_now_str()


def list_watch_candidates(watch_id: int, status: str = CANDIDATE_PENDING_STATUS) -> List[Dict[str, Any]]:
    now_ts = _now_str()
    db = SessionLocal()
    try:
        rows = db.execute(
            select(
                m.WatchCandidate.watch_id,
                m.WatchCandidate.id,
                m.WatchCandidate.channel_id,
                m.WatchCandidate.message_id,
                m.WatchCandidate.text_hash,
                m.WatchCandidate.similarity,
                m.WatchCandidate.message_text,
                m.WatchCandidate.created_at,
                m.WatchCandidate.expires_at,
                m.WatchCandidate.status,
            ).where(
                m.WatchCandidate.watch_id == watch_id,
                m.WatchCandidate.status == status,
                func.coalesce(m.WatchCandidate.expires_at, now_ts) >= now_ts,
            )
            .order_by(m.WatchCandidate.id.desc())
        ).all()
    finally:
        db.close()
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


def list_group_watch_candidates(watch_ids: List[int], status: str = CANDIDATE_PENDING_STATUS) -> List[Dict[str, Any]]:
    if not watch_ids:
        return []
    now_ts = _now_str()
    db = SessionLocal()
    try:
        rows = db.execute(
            select(
                m.WatchCandidate.watch_id,
                m.WatchCandidate.id,
                m.WatchCandidate.channel_id,
                m.WatchCandidate.message_id,
                m.WatchCandidate.text_hash,
                m.WatchCandidate.similarity,
                m.WatchCandidate.message_text,
                m.WatchCandidate.created_at,
                m.WatchCandidate.expires_at,
                m.WatchCandidate.status,
            ).where(
                m.WatchCandidate.watch_id.in_(watch_ids),
                m.WatchCandidate.status == status,
                func.coalesce(m.WatchCandidate.expires_at, now_ts) >= now_ts,
            )
            .order_by(m.WatchCandidate.id.desc())
        ).all()
    finally:
        db.close()
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


def list_candidates_by_hash(text_hash: str, status: str = CANDIDATE_PENDING_STATUS) -> List[Dict[str, Any]]:
    if not text_hash:
        return []
    now_ts = _now_str()
    db = SessionLocal()
    try:
        rows = db.execute(
            select(
                m.WatchCandidate.watch_id,
                m.WatchCandidate.id,
                m.WatchCandidate.channel_id,
                m.WatchCandidate.message_id,
                m.WatchCandidate.text_hash,
                m.WatchCandidate.similarity,
                m.WatchCandidate.message_text,
                m.WatchCandidate.created_at,
                m.WatchCandidate.expires_at,
                m.WatchCandidate.status,
            ).where(
                m.WatchCandidate.text_hash == text_hash,
                m.WatchCandidate.status == status,
                func.coalesce(m.WatchCandidate.expires_at, now_ts) >= now_ts,
            )
            .order_by(m.WatchCandidate.id.desc())
        ).all()
    finally:
        db.close()
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


def find_candidates_by_channel_message(
    channel_id: int,
    message_id: int,
    status: str = CANDIDATE_PENDING_STATUS,
) -> List[Dict[str, Any]]:
    if not channel_id or not message_id:
        return []
    now_ts = _now_str()
    db = SessionLocal()
    try:
        rows = db.execute(
            select(
                m.WatchCandidate.id,
                m.WatchCandidate.watch_id,
                m.WatchCandidate.channel_id,
                m.WatchCandidate.message_id,
                m.WatchCandidate.text_hash,
                m.WatchCandidate.similarity,
                m.WatchCandidate.message_text,
                m.WatchCandidate.created_at,
                m.WatchCandidate.expires_at,
                m.WatchCandidate.status,
            ).where(
                m.WatchCandidate.channel_id == int(channel_id),
                m.WatchCandidate.message_id == int(message_id),
                m.WatchCandidate.status == status,
                func.coalesce(m.WatchCandidate.expires_at, now_ts) >= now_ts,
            )
        ).all()
    finally:
        db.close()
    return [
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
        for r in rows
    ]


def get_watch_candidate(candidate_id: int) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        row = db.execute(
            select(
                m.WatchCandidate.id,
                m.WatchCandidate.watch_id,
                m.WatchCandidate.channel_id,
                m.WatchCandidate.message_id,
                m.WatchCandidate.text_hash,
                m.WatchCandidate.similarity,
                m.WatchCandidate.message_text,
                m.WatchCandidate.created_at,
                m.WatchCandidate.expires_at,
                m.WatchCandidate.status,
            ).where(m.WatchCandidate.id == candidate_id)
        ).first()
    finally:
        db.close()
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
    db = SessionLocal()
    try:
        res = db.execute(
            update(m.WatchCandidate)
            .where(m.WatchCandidate.id == candidate_id)
            .values(status=status)
        )
        db.commit()
        return (res.rowcount or 0) > 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def merge_watch_candidate(
    candidate_id: int,
    message_id: Optional[int],
    text_hash: Optional[str],
    similarity: Optional[float],
    message_text: Optional[str],
) -> None:
    """
    Оновлює існуючого кандидата: зберігає більшу схожість і, за потреби, новий текст/хеш/повідомлення.
    """
    db = SessionLocal()
    try:
        row = db.execute(
            select(
                m.WatchCandidate.similarity,
                m.WatchCandidate.message_text,
                m.WatchCandidate.message_id,
                m.WatchCandidate.text_hash,
            ).where(m.WatchCandidate.id == candidate_id)
        ).first()
        if not row:
            return
        current_sim = float(row.similarity or 0.0)
        new_sim = max(current_sim, float(similarity or 0.0))

        # За замовчуванням залишаємо поточні значення
        update_message_id = row.message_id
        update_message_text = row.message_text
        update_text_hash = row.text_hash

        # Якщо новий текст довший/інформативніший — підміняємо його разом із message_id та хешем
        try:
            if message_text and len(message_text) > len(row.message_text or ""):
                update_message_text = message_text
                update_message_id = message_id if message_id is not None else row.message_id
                update_text_hash = text_hash if text_hash is not None else row.text_hash
        except Exception:
            pass

        db.execute(
            update(m.WatchCandidate)
            .where(m.WatchCandidate.id == candidate_id)
            .values(
                similarity=new_sim,
                message_id=update_message_id,
                message_text=update_message_text,
                text_hash=update_text_hash,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def accept_watch_candidate(
    candidate_id: int,
    matched_session: Optional[str] = None,
    coverage_hours: Optional[float] = None,
) -> bool:
    cand = get_watch_candidate(candidate_id)
    if not cand or cand.get("status") not in ("pending", CANDIDATE_PENDING_STATUS):
        return False
    text_hash = cand.get("text_hash") or ""
    candidates = list_candidates_by_hash(text_hash, status=CANDIDATE_PENDING_STATUS) if text_hash else [cand]

    def _coverage_at_from_created(created_at: Optional[str]) -> str:
        if coverage_hours is None:
            return _now_str()
        try:
            dt = datetime.fromisoformat(str(created_at)) if created_at else moscow_now()
            dt = ensure_moscow_timezone(dt)
            dt = dt + timedelta(hours=float(coverage_hours))
            return dt.strftime(MOSCOW_TIME_FORMAT)
        except Exception:
            return _now_str()

    any_ok = False
    for c in candidates:
        watch_id = c.get("watch_id")
        message_id = c.get("message_id")
        channel_id = c.get("channel_id")
        cid = c.get("id")
        if not watch_id or not message_id:
            continue
        coverage_at = _coverage_at_from_created(c.get("created_at"))
        effective_session = matched_session
        if effective_session is None and channel_id:
            try:
                effective_session = mem_db.get_any_session_for_channel(int(channel_id))
            except Exception:
                effective_session = None
        try:
            process_mark_matched(
                int(watch_id),
                int(message_id),
                coverage_at,
                matched_session=effective_session,
            )
            insert_watch_event(
                int(watch_id),
                "matched",
                json.dumps(
                    {
                        "watch_id": watch_id,
                        "channel_id": channel_id,
                        "message_id": message_id,
                        "session": effective_session,
                        "via": "manual_candidate",
                        "candidate_id": cid,
                        "text_hash": text_hash,
                    }
                ),
            )
            set_watch_candidate_status(int(cid), "accepted")
            any_ok = True
        except Exception:
            continue
    return any_ok


def get_watch_expected_links(watch_id: int) -> List[str]:
    db = SessionLocal()
    try:
        row = db.execute(
            select(m.WatchPost.expected_links_json).where(m.WatchPost.id == watch_id).limit(1)
        ).first()
    finally:
        db.close()
    if not row or not row[0]:
        return []
    try:
        import json

        data = json.loads(row[0])
        if isinstance(data, list):
            return [str(x) for x in data if x]
    except Exception:
        return []
    return []


def get_watch_expected_text(watch_id: int) -> Optional[str]:
    db = SessionLocal()
    try:
        row = db.execute(
            select(m.WatchPost.expected_text_hash).where(m.WatchPost.id == watch_id).limit(1)
        ).first()
    finally:
        db.close()
    if not row:
        return None
    return row[0]
