from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime
from zoneinfo import ZoneInfo
import json

from sqlalchemy import func, select, update

from app.admin_bot.db.session import SessionLocal
from app.admin_bot.db import models as m
from app.DAL.watch_processing_operations import mark_matched as process_mark_matched
from app.DAL.watch_events_operations import insert_watch_event

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def _now_str() -> str:
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d %H:%M:%S")


def list_watch_candidates(watch_id: int, status: str = "pending") -> List[Dict[str, Any]]:
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


def list_group_watch_candidates(watch_ids: List[int], status: str = "pending") -> List[Dict[str, Any]]:
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


def list_candidates_by_hash(text_hash: str, status: str = "pending") -> List[Dict[str, Any]]:
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


def accept_watch_candidate(candidate_id: int, matched_session: Optional[str] = None) -> bool:
    cand = get_watch_candidate(candidate_id)
    if not cand or cand.get("status") != "pending":
        return False
    text_hash = cand.get("text_hash") or ""
    candidates = list_candidates_by_hash(text_hash) if text_hash else [cand]

    any_ok = False
    for c in candidates:
        watch_id = c.get("watch_id")
        message_id = c.get("message_id")
        channel_id = c.get("channel_id")
        cid = c.get("id")
        if not watch_id or not message_id:
            continue
        coverage_at = _now_str()
        try:
            process_mark_matched(
                int(watch_id),
                int(message_id),
                coverage_at,
                matched_session=matched_session,
            )
            insert_watch_event(
                int(watch_id),
                "matched",
                json.dumps(
                    {
                        "watch_id": watch_id,
                        "channel_id": channel_id,
                        "message_id": message_id,
                        "session": matched_session,
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
