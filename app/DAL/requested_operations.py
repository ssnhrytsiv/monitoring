"""
DAO-операції для invite_check / requested_check (reconciler backoff).
Працюємо у функціональному стилі: усі функції приймають явний db: Session.
"""
from __future__ import annotations

import logging
import math
import os
import time
from typing import List, Optional, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.DAL.schemas import InviteCheckRecord, InviteCheckRecordListAdapter, RequestedCheckRecord
from app.db import models as sm

log = logging.getLogger("dal.requested")

# ---------------------------------------------------------------------
# Конфіг
# ---------------------------------------------------------------------
INVITE_BACKOFF_BASE = int(os.getenv("REQUESTED_INVITE_BACKOFF_BASE", "15"))
INVITE_BACKOFF_MAX = int(os.getenv("REQUESTED_INVITE_BACKOFF_MAX", "3600"))
REQ_BACKOFF_BASE = int(os.getenv("REQUESTED_BACKOFF_BASE", "30"))
REQ_BACKOFF_MAX = int(os.getenv("REQUESTED_BACKOFF_MAX", "3600"))

INVITE_BACKOFF_FACTOR = float(os.getenv("REQUESTED_INVITE_BACKOFF_FACTOR", "2.0") or "2.0")
REQ_BACKOFF_FACTOR = float(os.getenv("REQUESTED_BACKOFF_FACTOR", "5.0") or "5.0")

INVITE_RECHECK_MIN_SEC = int(
    os.getenv("REQUESTED_RECONCILER_INVITE_RECHECK_MIN_SEC", str(30 * 60)) or str(30 * 60)
)
INVITE_NOTE_DEBOUNCE_SEC = int(
    os.getenv("REQUESTED_RECONCILER_INVITE_NOTE_DEBOUNCE_SEC", "60") or "60"
)
INVITE_NOTE_RESET_LIMIT_PER_HOUR = int(
    os.getenv("REQUESTED_RECONCILER_INVITE_RESET_LIMIT_PER_HOUR", "120") or "120"
)


def _now() -> int:
    return int(time.time())


def _calc_next(base: int, tries: int, max_cap: int, factor: float = 2.0) -> int:
    """Експоненційний backoff із обрізанням max_cap, завжди >=1."""
    if tries < 1:
        tries = 1
    try:
        raw = base * (factor ** (tries - 1))
    except OverflowError:
        raw = float("inf")
    if not math.isfinite(raw):
        step = max_cap if max_cap > 0 else base
    else:
        if max_cap > 0:
            raw = min(raw, max_cap)
        step = int(raw)
    return step if step > 0 else 1


_NOTE_RESET_WINDOW: dict[tuple[str, str], dict[str, int]] = {}


def _allow_note_reset(db: Session, session: str, invite_hash: str, now_ts: int) -> bool:
    """Anti-bounce для note_requested_invite (debounce + ліміт на годину)."""
    key = (session, invite_hash)

    row = db.get(sm.InviteCheck, {"invite_hash": invite_hash, "session": session})
    last_noted = row.noted_at if row else 0
    if now_ts - last_noted < INVITE_NOTE_DEBOUNCE_SEC:
        return False

    win = _NOTE_RESET_WINDOW.get(key)
    if not win or now_ts - win["start"] > 3600:
        win = {"start": now_ts, "count": 0}
        _NOTE_RESET_WINDOW[key] = win

    if win["count"] >= INVITE_NOTE_RESET_LIMIT_PER_HOUR:
        return False

    win["count"] += 1
    return True


# ---------- INVITE ----------
def note_requested_invite(db: Session, session: str, invite_hash: str, start_after_sec: int = 60) -> None:
    now = _now()
    row = db.get(sm.InviteCheck, {"invite_hash": invite_hash, "session": session})
    if row is None:
        row = sm.InviteCheck(
            invite_hash=invite_hash,
            session=session,
            noted_at=now,
            next_check_at=now + int(start_after_sec),
            tries=0,
        )
        db.add(row)
        db.commit()
        return

    prev_noted = row.noted_at or 0
    if now - prev_noted < INVITE_NOTE_DEBOUNCE_SEC:
        row.noted_at = now
        db.commit()
        return

    if not _allow_note_reset(db, session, invite_hash, now):
        row.noted_at = now
        db.commit()
        return

    row.tries = 0
    row.noted_at = now
    min_next = now + INVITE_RECHECK_MIN_SEC
    row.next_check_at = max(row.next_check_at or 0, min_next)
    db.commit()


def get_invite_sessions(db: Session, invite_hash: str) -> List[str]:
    q = select(sm.InviteCheck.session).where(sm.InviteCheck.invite_hash == invite_hash)
    rows = db.execute(q).scalars().all()
    return [r for r in rows if r]


def due_invites(db: Session, sessions: Sequence[str], limit: int) -> List[InviteCheckRecord]:
    now = _now()
    return InviteCheckRecordListAdapter.validate_python(
        db.query(sm.InviteCheck)
        .filter(sm.InviteCheck.session.in_(sessions))
        .filter(sm.InviteCheck.next_check_at <= now)
        .order_by(sm.InviteCheck.next_check_at.asc())
        .limit(int(limit))
        .all()
    )


def backoff_invite_miss(db: Session, session: str, invite_hash: str) -> None:
    row = db.get(sm.InviteCheck, {"invite_hash": invite_hash, "session": session})
    if not row:
        note_requested_invite(db, session, invite_hash, start_after_sec=INVITE_BACKOFF_BASE)
        return
    now = _now()
    row.tries = (row.tries or 0) + 1
    step = _calc_next(INVITE_BACKOFF_BASE, row.tries, INVITE_BACKOFF_MAX, factor=INVITE_BACKOFF_FACTOR)
    exp_next = now + step
    floor_next = now + INVITE_RECHECK_MIN_SEC
    row.next_check_at = max(exp_next, floor_next)
    db.commit()


def defer_invite_until(db: Session, session: str, invite_hash: str, next_ts_epoch: int) -> None:
    next_ts_epoch = int(next_ts_epoch)
    stmt = (
        update(sm.InviteCheck)
        .where(sm.InviteCheck.session == session, sm.InviteCheck.invite_hash == invite_hash)
        .where(sm.InviteCheck.next_check_at < next_ts_epoch)
        .values(next_check_at=next_ts_epoch)
    )
    db.execute(stmt)
    db.commit()


def bulk_defer_session_invites(db: Session, session: str, next_ts_epoch: int) -> None:
    next_ts_epoch = int(next_ts_epoch)
    stmt = (
        update(sm.InviteCheck)
        .where(sm.InviteCheck.session == session)
        .where(sm.InviteCheck.next_check_at < next_ts_epoch)
        .values(next_check_at=next_ts_epoch)
    )
    db.execute(stmt)
    db.commit()


def clear_invite(db: Session, session: str, invite_hash: str) -> None:
    row = db.get(sm.InviteCheck, {"invite_hash": invite_hash, "session": session})
    if row:
        db.delete(row)
        db.commit()


# ---------- REQUESTED ----------
def note_requested(db: Session, session: str, channel_id: int, start_after_sec: int = 60) -> None:
    pk = {"session": session, "channel_id": int(channel_id)}
    row = db.get(sm.RequestedCheck, pk)
    now = _now()
    if row is None:
        row = sm.RequestedCheck(
            session=session,
            channel_id=int(channel_id),
            noted_at=now,
            next_check_at=now + int(start_after_sec),
            tries=0,
        )
        db.add(row)
    else:
        row.noted_at = now
        row.tries = 0
        row.next_check_at = now + int(start_after_sec)
    db.commit()


def due_requested(db: Session, sessions: Sequence[str], per_account: int, limit: int) -> List[RequestedCheckRecord]:
    if not sessions:
        return []
    now = _now()
    q = (
        select(sm.RequestedCheck)
        .where(sm.RequestedCheck.session.in_(sessions))
        .where(sm.RequestedCheck.next_check_at <= now)
        .order_by(sm.RequestedCheck.next_check_at.asc())
        .limit(int(limit))
    )
    rows = list(db.execute(q).scalars().all())
    return [
        RequestedCheckRecord(
            session=row.session,
            channel_id=row.channel_id,
            noted_at=row.noted_at,
            next_check_at=row.next_check_at,
            tries=row.tries or 0,
        )
        for row in rows
    ]


def backoff_miss(db: Session, session: str, channel_id: int) -> None:
    pk = {"session": session, "channel_id": int(channel_id)}
    row = db.get(sm.RequestedCheck, pk)
    if not row:
        note_requested(db, session, int(channel_id), start_after_sec=REQ_BACKOFF_BASE)
        return
    row.tries = (row.tries or 0) + 1
    step = _calc_next(REQ_BACKOFF_BASE, row.tries, REQ_BACKOFF_MAX, factor=REQ_BACKOFF_FACTOR)
    row.next_check_at = _now() + step
    db.commit()


def bulk_defer_session_requested(db: Session, session: str, next_ts_epoch: int) -> None:
    next_ts_epoch = int(next_ts_epoch)
    stmt = (
        update(sm.RequestedCheck)
        .where(sm.RequestedCheck.session == session)
        .where(sm.RequestedCheck.next_check_at < next_ts_epoch)
        .values(next_check_at=next_ts_epoch)
    )
    db.execute(stmt)
    db.commit()


def reset_requested_daily(db: Session, now_ts: Optional[int] = None) -> int:
    ts = int(now_ts or _now())
    stmt = update(sm.RequestedCheck).values(
        tries=0,
        next_check_at=func.min(sm.RequestedCheck.next_check_at, ts),
    )
    res = db.execute(stmt)
    db.commit()
    return res.rowcount or 0


def clear(db: Session, session: str, channel_id: int) -> None:
    pk = {"session": session, "channel_id": int(channel_id)}
    row = db.get(sm.RequestedCheck, pk)
    if row:
        db.delete(row)
        db.commit()


def is_requested(db: Session, session: str, channel_id: int) -> bool:
    pk = {"session": session, "channel_id": int(channel_id)}
    row = db.get(sm.RequestedCheck, pk)
    return bool(row)
