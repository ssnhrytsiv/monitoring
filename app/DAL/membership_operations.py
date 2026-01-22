"""Membership and invite-check helpers (functional style)."""
from __future__ import annotations

import logging
import time
from typing import Optional, List

from sqlalchemy import case, select, text
from sqlalchemy.orm import Session

from app.db import models as m
from app.utils.link_parser import normalize_invite_hash

log = logging.getLogger(__name__)

FINAL_GLOBAL = ("joined", "already", "requested", "invalid", "private")
FINAL_PER_ACC = ("joined", "already", "requested", "invalid", "private", "blocked", "too_many")


def _now_ts() -> int:
    return int(time.time())


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


def bump_requested_attempt(db: Session, invite_or_hash: str) -> int:
    h = normalize_invite_hash(invite_or_hash)
    if not h:
        return 0
    # InviteAttempt таблиця дропнута; залишаємо no-op, щоб зберегти інтерфейс
    return 0


def invite_check_last_session(db: Session, invite_or_hash: str) -> Optional[str]:
    h = normalize_invite_hash(invite_or_hash)
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


def delete_memberships_by_channels(db: Session, channel_ids: List[int]) -> int:
    if not channel_ids:
        return 0
    return (
        db.query(m.Membership)
        .filter(m.Membership.channel_id.in_(channel_ids))
        .delete(synchronize_session=False)
    ) or 0


def delete_membership_status_by_channels(db: Session, channel_ids: List[int]) -> int:
    if not channel_ids:
        return 0
    try:
        placeholders = ",".join([str(int(cid)) for cid in channel_ids])
        return db.execute(text(f"DELETE FROM membership_status WHERE channel_id IN ({placeholders})")).rowcount or 0
    except Exception:
        return 0
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
