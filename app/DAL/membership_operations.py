"""Invite cache helpers (functional style; current scope: InviteCache table)."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional, Tuple, List

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.db import models as m

log = logging.getLogger(__name__)

FINAL_GLOBAL = ("joined", "already", "requested", "invalid", "private")
FINAL_PER_ACC = ("joined", "already", "requested", "invalid", "private", "blocked", "too_many")


@dataclass(slots=True)
class InviteCacheRecord:
    invite_hash: str
    channel_id: Optional[int]
    title: Optional[str]
    status: Optional[str]
    session: Optional[str]
    last_error: Optional[str]


def _now_ts() -> int:
    return int(time.time())


def _extract_invite_hash(inv_or_url: str) -> Optional[str]:
    """
    Повертає чистий invite-hash із:
      - https://t.me/+XXXXXXXX
      - https://t.me/joinchat/XXXXXXXX
    або None, якщо це не інвайт.
    Приймає також уже чистий хеш (без пробілів та '/').
    """
    if not inv_or_url:
        return None
    s = str(inv_or_url)
    s = s.replace("\u200b", "").replace("\u200e", "").replace("\u200f", "").strip()
    try:
        if "/+" in s:
            return s.rsplit("/", 1)[-1].replace("+", "").strip()
        if "joinchat/" in s:
            return s.rsplit("joinchat/", 1)[-1].strip()
        if "/" not in s and " " not in s:
            return s
    except Exception:
        return None
    return None


# ---------- membership (пер-акаунтний стан у каналі) ----------
def upsert_membership(db: Session, account: str, channel_id: int, status: str) -> None:
    membership = (
        db.query(m.Membership)
        .filter(m.Membership.channel_id == int(channel_id), m.Membership.account == account)
        .one_or_none()
    )
    now = _now_ts()
    if membership:
        membership.status = status
        membership.ts = now
    else:
        db.add(
            m.Membership(
                channel_id=int(channel_id),
                account=account,
                status=status,
                ts=now,
            )
        )
    db.commit()


def get_membership(db: Session, account: str, channel_id: int) -> Optional[str]:
    membership_row = (
        db.query(m.Membership.status)
        .filter(m.Membership.channel_id == int(channel_id), m.Membership.account == account)
        .limit(1)
        .one_or_none()
    )
    return membership_row[0] if membership_row else None


def any_final_for_channel(db: Session, channel_id: int) -> Optional[str]:
    membership_row = (
        db.query(m.Membership.status)
        .filter(m.Membership.channel_id == int(channel_id), m.Membership.status.in_(FINAL_GLOBAL))
        .limit(1)
        .one_or_none()
    )
    return membership_row[0] if membership_row else None


def get_any_session_for_channel(db: Session, channel_id: int) -> Optional[str]:
    """
    Повертає якусь сесію (account) для channel_id, пріоритезуючи joined/already/requested.
    """
    priority = case(
        (m.Membership.status.in_(("joined", "already")), 1),
        (m.Membership.status == "requested", 2),
        else_=3,
    )
    row = (
        db.query(m.Membership.account, m.Membership.status)
        .filter(m.Membership.channel_id == int(channel_id))
        .order_by(priority, m.Membership.ts.desc())
        .limit(1)
        .one_or_none()
    )
    if not row:
        log.debug("membership: session_lookup channel_id=%s -> none", channel_id)
        return None
    account_val, status_val = row
    log.debug("membership: session_lookup channel_id=%s -> account=%s status=%s", channel_id, account_val, status_val)
    return str(account_val)


def get_session_by_channel(db: Session, channel_id: int) -> Optional[str]:
    """Аліас для get_any_session_for_channel — для читабельності викликів."""
    return get_any_session_for_channel(db, channel_id)


# ---------- invite_cache (інвайт-хеш -> channel_id, title, status, session) ----------
def invite_cache_get(db: Session, invite_or_hash: str) -> Optional[InviteCacheRecord]:
    h = _extract_invite_hash(invite_or_hash)
    if not h:
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
        .filter(m.InviteCache.invite_hash == h)
        .one_or_none()
    )
    if not row:
        return None
    return InviteCacheRecord(
        invite_hash=row[0],
        channel_id=int(row[1]) if row[1] is not None else None,
        title=row[2],
        status=row[3],
        session=row[4],
        last_error=row[5],
    )


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
    h = _extract_invite_hash(invite_or_hash)
    if not h:
        raise ValueError("Invalid invite hash")
    row = db.query(m.InviteCache).filter(m.InviteCache.invite_hash == h).one_or_none()
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
            invite_hash=h,
            channel_id=int(channel_id) if channel_id is not None else None,
            title=title,
            status=status,
            session=session,
            last_error=last_error,
        )
        db.add(row)
    db.commit()
    return InviteCacheRecord(
        invite_hash=h,
        channel_id=row.channel_id,
        title=row.title,
        status=row.status,
        session=row.session,
        last_error=row.last_error,
    )


def map_invite_set(db: Session, invite_or_hash: str, channel_id: Optional[int], title: Optional[str] = None) -> None:
    invite_cache_upsert(db, invite_or_hash, channel_id=channel_id, title=title)


def map_invite_get(db: Session, invite_or_hash: str) -> Tuple[Optional[int], Optional[str]]:
    cache = invite_cache_get(db, invite_or_hash)
    if not cache:
        return None, None
    return cache.channel_id, cache.title


# ---------- invite_cache status (статус інвайту за invite_hash) ----------
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
    q = db.query(m.InviteCache).filter(m.InviteCache.invite_hash.in_(hashes))
    if statuses:
        st = [s for s in statuses if s]
        if not st:
            return 0
        q = q.filter(m.InviteCache.status.in_(st))
    deleted = q.delete(synchronize_session=False)
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


def bump_requested_attempt(db: Session, invite_or_hash: str) -> int:
    h = _extract_invite_hash(invite_or_hash)
    if not h:
        return 0
    # InviteAttempt таблиця дропнута; залишаємо no-op, щоб зберегти інтерфейс
    return 0


def invite_check_last_session(db: Session, invite_or_hash: str) -> Optional[str]:
    h = _extract_invite_hash(invite_or_hash)
    if not h:
        return None
    rec = (
        db.query(m.InviteCheck.session)
        .filter(m.InviteCheck.invite_hash == h)
        .order_by(m.InviteCheck.noted_at.desc())
        .limit(1)
        .one_or_none()
    )
    return rec[0] if rec else None


# ---------- url_cache (статус по URL) ----------
def url_put(db: Session, url: str, status: str) -> None:
    if not url:
        return
    now = _now_ts()
    url_cache = db.query(m.UrlCache).filter(m.UrlCache.url == url).one_or_none()
    if url_cache:
        url_cache.status = status
        url_cache.ts = now
    else:
        db.add(m.UrlCache(url=url, status=status, ts=now))
    db.commit()


def url_get(db: Session, url: str) -> Optional[str]:
    if not url:
        return None
    url_cache = db.query(m.UrlCache.status).filter(m.UrlCache.url == url).one_or_none()
    return url_cache[0] if url_cache else None


def url_delete(db: Session, urls: list[str], statuses: Optional[list[str]] = None) -> int:
    if not urls:
        return 0
    q = db.query(m.UrlCache).filter(m.UrlCache.url.in_(urls))
    if statuses:
        st = [s for s in statuses if s]
        if not st:
            return 0
        q = q.filter(m.UrlCache.status.in_(st))
    deleted = q.delete(synchronize_session=False)
    db.commit()
    return deleted or 0
def list_memberships_for_channels(db: Session, channel_ids: List[int]) -> List[m.Membership]:
    if not channel_ids:
        return []
    return (
        db.query(m.Membership)
        .filter(
            m.Membership.channel_id.in_(channel_ids),
            m.Membership.account != "",
        )
        .all()
    )


def list_membership_account_pairs(db: Session, channel_ids: List[int]) -> List[tuple[str, int]]:
    if not channel_ids:
        return []
    rows = db.execute(
        select(m.Membership.account, m.Membership.channel_id).where(
            m.Membership.channel_id.in_(channel_ids),
            m.Membership.account != "",
        )
    ).all()
    return [(r[0], int(r[1])) for r in rows if r and r[0] and r[1] is not None]


def owner_conflict_get(db: Session, channel_id: int) -> Optional[m.OwnerConflict]:
    return (
        db.query(m.OwnerConflict)
        .filter(m.OwnerConflict.channel_id == int(channel_id))
        .limit(1)
        .one_or_none()
    )


def owner_conflict_delete_by_channels(db: Session, channel_ids: List[int]) -> int:
    if not channel_ids:
        return 0
    return (
        db.query(m.OwnerConflict)
        .filter(m.OwnerConflict.channel_id.in_(channel_ids))
        .delete(synchronize_session=False)
    )
