"""
DAO-операції для invite_check / requested_check (reconciler backoff).
Підтримує опціональну зовнішню Session або fallback на SessionLocal.
"""
from __future__ import annotations

import logging
import math
import os
import time
from typing import List, Optional, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.DAL import SessionLocal
from app.services import models as sm

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


class RequestedDAO:
    """
    DAO-клас для invite_check / requested_check.
    """

    def __init__(self, db: Session):
        self.db = db
        self._note_reset_window: dict[tuple[str, str], dict[str, int]] = {}

    # ---------- helpers ----------
    def _allow_note_reset(self, session: str, invite_hash: str, now_ts: int) -> bool:
        """Anti-bounce для note_requested_invite (debounce + ліміт на годину)."""
        key = (session, invite_hash)

        row = self.db.get(sm.InviteCheck, {"invite_hash": invite_hash, "session": session})
        last_noted = row.noted_at if row else 0
        if now_ts - last_noted < INVITE_NOTE_DEBOUNCE_SEC:
            return False

        win = self._note_reset_window.get(key)
        if not win or now_ts - win["start"] > 3600:
            win = {"start": now_ts, "count": 0}
            self._note_reset_window[key] = win

        if win["count"] >= INVITE_NOTE_RESET_LIMIT_PER_HOUR:
            return False

        win["count"] += 1
        return True

    # ---------- INVITE ----------
    def note_requested_invite(self, session: str, invite_hash: str, start_after_sec: int = 60) -> None:
        now = _now()
        row = self.db.get(sm.InviteCheck, {"invite_hash": invite_hash, "session": session})
        if row is None:
            row = sm.InviteCheck(
                invite_hash=invite_hash,
                session=session,
                noted_at=now,
                next_check_at=now + int(start_after_sec),
                tries=0,
            )
            self.db.add(row)
            self.db.commit()
            return

        prev_noted = row.noted_at or 0
        if now - prev_noted < INVITE_NOTE_DEBOUNCE_SEC:
            row.noted_at = now
            self.db.commit()
            return

        if not self._allow_note_reset(session, invite_hash, now):
            row.noted_at = now
            self.db.commit()
            return

        row.tries = 0
        row.noted_at = now
        min_next = now + INVITE_RECHECK_MIN_SEC
        row.next_check_at = max(row.next_check_at or 0, min_next)
        self.db.commit()

    def get_invite_sessions(self, invite_hash: str) -> List[str]:
        q = select(sm.InviteCheck.session).where(sm.InviteCheck.invite_hash == invite_hash)
        rows = self.db.execute(q).scalars().all()
        return [r for r in rows if r]

    def due_invites(self, sessions: Sequence[str], limit: int) -> List[sm.InviteCheck]:
        if not sessions:
            return []
        now = _now()
        q = (
            select(sm.InviteCheck)
            .where(sm.InviteCheck.session.in_(sessions))
            .where(sm.InviteCheck.next_check_at <= now)
            .order_by(sm.InviteCheck.next_check_at.asc())
            .limit(int(limit))
        )
        return list(self.db.execute(q).scalars().all())

    def backoff_invite_miss(self, session: str, invite_hash: str) -> None:
        row = self.db.get(sm.InviteCheck, {"invite_hash": invite_hash, "session": session})
        if not row:
            self.note_requested_invite(session, invite_hash, start_after_sec=INVITE_BACKOFF_BASE)
            return
        now = _now()
        row.tries = (row.tries or 0) + 1
        step = _calc_next(INVITE_BACKOFF_BASE, row.tries, INVITE_BACKOFF_MAX, factor=INVITE_BACKOFF_FACTOR)
        exp_next = now + step
        floor_next = now + INVITE_RECHECK_MIN_SEC
        row.next_check_at = max(exp_next, floor_next)
        self.db.commit()

    def defer_invite_until(self, session: str, invite_hash: str, next_ts_epoch: int) -> None:
        next_ts_epoch = int(next_ts_epoch)
        stmt = (
            update(sm.InviteCheck)
            .where(sm.InviteCheck.session == session, sm.InviteCheck.invite_hash == invite_hash)
            .where(sm.InviteCheck.next_check_at < next_ts_epoch)
            .values(next_check_at=next_ts_epoch)
        )
        self.db.execute(stmt)
        self.db.commit()

    def bulk_defer_session_invites(self, session: str, next_ts_epoch: int) -> None:
        next_ts_epoch = int(next_ts_epoch)
        stmt = (
            update(sm.InviteCheck)
            .where(sm.InviteCheck.session == session)
            .where(sm.InviteCheck.next_check_at < next_ts_epoch)
            .values(next_check_at=next_ts_epoch)
        )
        self.db.execute(stmt)
        self.db.commit()

    def clear_invite(self, session: str, invite_hash: str) -> None:
        row = self.db.get(sm.InviteCheck, {"invite_hash": invite_hash, "session": session})
        if row:
            self.db.delete(row)
            self.db.commit()

    # ---------- REQUESTED ----------
    def note_requested(self, session: str, channel_id: int, start_after_sec: int = 60) -> None:
        pk = {"session": session, "channel_id": int(channel_id)}
        row = self.db.get(sm.RequestedCheck, pk)
        now = _now()
        if row is None:
            row = sm.RequestedCheck(
                session=session,
                channel_id=int(channel_id),
                noted_at=now,
                next_check_at=now + int(start_after_sec),
                tries=0,
            )
            self.db.add(row)
        else:
            row.noted_at = now
            row.tries = 0
            row.next_check_at = now + int(start_after_sec)
        self.db.commit()

    def due_requested(self, sessions: Sequence[str], per_account: int, limit: int) -> List[sm.RequestedCheck]:
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
        return list(self.db.execute(q).scalars().all())

    def backoff_miss(self, session: str, channel_id: int) -> None:
        pk = {"session": session, "channel_id": int(channel_id)}
        row = self.db.get(sm.RequestedCheck, pk)
        if not row:
            self.note_requested(session, int(channel_id), start_after_sec=REQ_BACKOFF_BASE)
            return
        row.tries = (row.tries or 0) + 1
        step = _calc_next(REQ_BACKOFF_BASE, row.tries, REQ_BACKOFF_MAX, factor=REQ_BACKOFF_FACTOR)
        row.next_check_at = _now() + step
        self.db.commit()

    def bulk_defer_session_requested(self, session: str, next_ts_epoch: int) -> None:
        next_ts_epoch = int(next_ts_epoch)
        stmt = (
            update(sm.RequestedCheck)
            .where(sm.RequestedCheck.session == session)
            .where(sm.RequestedCheck.next_check_at < next_ts_epoch)
            .values(next_check_at=next_ts_epoch)
        )
        self.db.execute(stmt)
        self.db.commit()

    def reset_requested_daily(self, now_ts: Optional[int] = None) -> int:
        ts = int(now_ts or _now())
        stmt = update(sm.RequestedCheck).values(
            tries=0,
            next_check_at=func.min(sm.RequestedCheck.next_check_at, ts),
        )
        res = self.db.execute(stmt)
        self.db.commit()
        return res.rowcount or 0

    def clear(self, session: str, channel_id: int) -> None:
        pk = {"session": session, "channel_id": int(channel_id)}
        row = self.db.get(sm.RequestedCheck, pk)
        if row:
            self.db.delete(row)
            self.db.commit()

    def is_requested(self, session: str, channel_id: int) -> bool:
        pk = {"session": session, "channel_id": int(channel_id)}
        row = self.db.get(sm.RequestedCheck, pk)
        return bool(row)


# ---------- Функціональні обгортки з опційною Session ----------

def _dao(db: Optional[Session]) -> RequestedDAO:
    return RequestedDAO(db or SessionLocal())


def note_requested_invite(session: str, invite_hash: str, start_after_sec: int = 60, db: Optional[Session] = None) -> None:
    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        RequestedDAO(db).note_requested_invite(session, invite_hash, start_after_sec)
    finally:
        if close:
            db.close()


def get_invite_sessions(invite_hash: str, db: Optional[Session] = None) -> List[str]:
    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        return RequestedDAO(db).get_invite_sessions(invite_hash)
    finally:
        if close:
            db.close()


def due_invites(sessions: Sequence[str], limit: int, db: Optional[Session] = None):
    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        return RequestedDAO(db).due_invites(sessions, limit)
    finally:
        if close:
            db.close()


def backoff_invite_miss(session: str, invite_hash: str, db: Optional[Session] = None) -> None:
    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        RequestedDAO(db).backoff_invite_miss(session, invite_hash)
    finally:
        if close:
            db.close()


def defer_invite_until(session: str, invite_hash: str, next_ts_epoch: int, db: Optional[Session] = None) -> None:
    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        RequestedDAO(db).defer_invite_until(session, invite_hash, next_ts_epoch)
    finally:
        if close:
            db.close()


def bulk_defer_session_invites(session: str, next_ts_epoch: int, db: Optional[Session] = None) -> None:
    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        RequestedDAO(db).bulk_defer_session_invites(session, next_ts_epoch)
    finally:
        if close:
            db.close()


def clear_invite(session: str, invite_hash: str, db: Optional[Session] = None) -> None:
    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        RequestedDAO(db).clear_invite(session, invite_hash)
    finally:
        if close:
            db.close()


def note_requested(session: str, channel_id: int, start_after_sec: int = 60, db: Optional[Session] = None) -> None:
    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        RequestedDAO(db).note_requested(session, channel_id, start_after_sec)
    finally:
        if close:
            db.close()


def due_requested(sessions: Sequence[str], per_account: int, limit: int, db: Optional[Session] = None):
    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        return RequestedDAO(db).due_requested(sessions, per_account, limit)
    finally:
        if close:
            db.close()


def backoff_miss(session: str, channel_id: int, db: Optional[Session] = None) -> None:
    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        RequestedDAO(db).backoff_miss(session, channel_id)
    finally:
        if close:
            db.close()


def bulk_defer_session_requested(session: str, next_ts_epoch: int, db: Optional[Session] = None) -> None:
    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        RequestedDAO(db).bulk_defer_session_requested(session, next_ts_epoch)
    finally:
        if close:
            db.close()


def reset_requested_daily(now_ts: Optional[int] = None, db: Optional[Session] = None) -> int:
    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        return RequestedDAO(db).reset_requested_daily(now_ts)
    finally:
        if close:
            db.close()


def clear(session: str, channel_id: int, db: Optional[Session] = None) -> None:
    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        RequestedDAO(db).clear(session, channel_id)
    finally:
        if close:
            db.close()


def is_requested(session: str, channel_id: int, db: Optional[Session] = None) -> bool:
    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        return RequestedDAO(db).is_requested(session, channel_id)
    finally:
        if close:
            db.close()
