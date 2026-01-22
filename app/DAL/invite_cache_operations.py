"""
InviteCache helpers (separated DAL for invite_cache table).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.db import models as m
from app.utils.link_parser import sanitize_link, normalize_invite_hash
from app.DAL.schemas import InviteCacheRecord, InviteCacheRecordListAdapter

# Фінальні статуси для інвайтів (аналог membership FINAL_GLOBAL)
FINAL_GLOBAL = ("joined", "already", "requested", "invalid", "private")
# Розширені фінальні для акаунта
FINAL_PER_ACC = ("joined", "already", "requested", "invalid", "private", "blocked", "too_many")


def invite_cache_get(db: Session, invite_or_hash: str) -> Optional[InviteCacheRecord]:
    invite_hash = normalize_invite_hash(invite_or_hash)
    if not invite_hash:
        return None
    row = (
        db.query(
            m.InviteCache.invite_hash,
            m.InviteCache.channel_id,
            m.InviteCache.title,
            m.InviteCache.status,
            m.InviteCache.session,
            m.InviteCache.last_error,
        )
        .filter(m.InviteCache.invite_hash == invite_hash)
        .one_or_none()
    )
    if row is None:
        return None
    return InviteCacheRecord.model_validate(row)


def invite_cache_upsert(
    db: Session,
    invite_or_hash: str,
    *,
    channel_id: Optional[int] = None,
    title: Optional[str] = None,
    status: Optional[str] = None,
    session: Optional[str] = None,
    last_error: Optional[str] = None,
) -> InviteCacheRecord:
    invite_hash = normalize_invite_hash(invite_or_hash)
    if not invite_hash:
        raise ValueError("Invalid invite hash")
    row = db.query(m.InviteCache).filter(m.InviteCache.invite_hash == invite_hash).one_or_none()
    if row:
        if channel_id is not None:
            row.channel_id = int(channel_id)
        if title is not None:
            row.title = title
        if status is not None:
            row.status = status
        if session is not None:
            row.session = session
        if last_error is not None:
            row.last_error = last_error
    else:
        row = m.InviteCache(
            invite_hash=invite_hash,
            channel_id=int(channel_id) if channel_id is not None else None,
            title=title,
            status=status,
            session=session,
            last_error=last_error,
        )
        db.add(row)
    db.commit()
    return InviteCacheRecord.model_validate(row)


def map_invite_set(db: Session, invite_or_hash: str, channel_id: Optional[int], title: Optional[str] = None) -> None:
    invite_cache_upsert(db, invite_or_hash, channel_id=channel_id, title=title)


def map_invite_get(db: Session, invite_or_hash: str) -> Tuple[Optional[int], Optional[str]]:
    cache = invite_cache_get(db, invite_or_hash)
    if not cache:
        return None, None
    return cache.channel_id, cache.title


def invite_cache_status_get(db: Session, invite_or_hash: str) -> Optional[str]:
    cache = invite_cache_get(db, invite_or_hash)
    return cache.status if cache else None


def invite_cache_status_put(db: Session, invite_or_hash: str, status: str) -> None:
    invite_cache_upsert(db, invite_or_hash, status=status)


def invite_cache_status_delete(
    db: Session, invite_hashes: list[str], statuses: Optional[list[str]] = None
) -> int:
    hashes = [h for h in (invite_hashes or []) if h]
    if not hashes:
        return 0
    query = db.query(m.InviteCache).filter(m.InviteCache.invite_hash.in_(hashes))
    if statuses:
        statuses_filtered = [s for s in statuses if s]
        if not statuses_filtered:
            return 0
        query = query.filter(m.InviteCache.status.in_(statuses_filtered))
    deleted = query.delete(synchronize_session=False)
    db.commit()
    return deleted or 0


def invite_cache_status_put_for_channel(db: Session, channel_id: int, status: str) -> int:
    if channel_id is None:
        return 0
    rows = (
        db.query(m.InviteCache)
        .filter(m.InviteCache.channel_id == int(channel_id))
        .all()
    )
    if not rows:
        return 0
    for row in rows:
        row.status = status
    db.commit()
    return len(rows)


def invite_cache_delete_by_channels(db: Session, channel_ids: list[int]) -> int:
    if not channel_ids:
        return 0
    return (
        db.query(m.InviteCache)
        .filter(m.InviteCache.channel_id.in_(channel_ids))
        .delete(synchronize_session=False)
    )


def invite_cache_status_get_bulk(db: Session, invites: list[str]) -> List[InviteCacheRecord]:
    invite_hashes = [sanitize_link(x) or x for x in invites or [] if x]
    invite_hashes = [h for h in invite_hashes if h]
    if not invite_hashes:
        return []
    return InviteCacheRecordListAdapter.validate_python(
        db.query(m.InviteCache).filter(m.InviteCache.invite_hash.in_(invite_hashes)).all()
    )
