from __future__ import annotations

import os
import time
import logging
from typing import Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import (
    create_engine, event, Integer, String, PrimaryKeyConstraint, Index,
    select, func
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, Session, sessionmaker
)

log = logging.getLogger("services.requested_reconciler.db")

# ---------------------------------------------------------------------
# Конфіг
# ---------------------------------------------------------------------
DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")
SQLITE_URL = f"sqlite:///{DB_PATH}"

# Параметри backoff
INVITE_BACKOFF_BASE = int(os.getenv("REQUESTED_INVITE_BACKOFF_BASE", "15"))   # сек
INVITE_BACKOFF_MAX  = int(os.getenv("REQUESTED_INVITE_BACKOFF_MAX", "3600"))  # сек
REQ_BACKOFF_BASE    = int(os.getenv("REQUESTED_BACKOFF_BASE", "30"))          # сек
REQ_BACKOFF_MAX     = int(os.getenv("REQUESTED_BACKOFF_MAX", "3600"))         # сек

# ---------------------------------------------------------------------
# SQLAlchemy базові речі
# ---------------------------------------------------------------------
class Base(DeclarativeBase):
    pass

class InviteCheck(Base):
    __tablename__ = "invite_check"

    invite_hash: Mapped[str] = mapped_column(String, nullable=False)
    session:     Mapped[str] = mapped_column(String, nullable=False)
    noted_at:    Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
    next_check_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
    tries:       Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        PrimaryKeyConstraint("invite_hash", "session", name="pk_invite_check"),
        Index("idx_invite_check_next", "next_check_at"),
        Index("idx_invite_check_sess_next", "session", "next_check_at"),
    )

class RequestedCheck(Base):
    __tablename__ = "requested_check"

    session:    Mapped[str] = mapped_column(String, nullable=False)
    channel_id: Mapped[int] = mapped_column(Integer, nullable=False)
    noted_at:   Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
    next_check_at: Mapped[int] = mapped_column(Integer, nullable=False, default=lambda: int(time.time()))
    tries:      Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        PrimaryKeyConstraint("session", "channel_id", name="pk_requested_check"),
        Index("idx_requested_check_next", "next_check_at"),
        Index("idx_requested_check_sess_next", "session", "next_check_at"),
    )

# Engine + Session
engine = create_engine(
    SQLITE_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)

# WAL, busy_timeout
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    try:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA busy_timeout=3000;")
        cur.close()
    except Exception:
        pass

SessionLocal = sessionmaker(bind=engine, class_=Session, autoflush=False, autocommit=False, future=True)

# ---------------------------------------------------------------------
# Ініціалізація
# ---------------------------------------------------------------------
def init(db_path: Optional[str] = None) -> None:
    """
    Створює таблиці, якщо їх немає. Схему НЕ змінює.
    """
    global DB_PATH
    if db_path:
        DB_PATH_local = db_path
    else:
        DB_PATH_local = DB_PATH

    log.debug("[rdb.init] Using DB: %s", DB_PATH_local)
    Base.metadata.create_all(engine)
    log.debug("[rdb.init] DDL applied")

# ---------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------
def _now() -> int:
    return int(time.time())

def _calc_next(base: int, tries: int, max_cap: int) -> int:
    # експоненційний зростаючий бекоф: base * 2^tries, але обрізаємо max_cap
    step = min(max_cap, base * (2 ** max(0, tries)))
    return _now() + step

# ---------------------------------------------------------------------
# API — INVITE
# ---------------------------------------------------------------------
def note_requested_invite(session: str, invite_hash: str, start_after_sec: int = 60) -> None:
    """
    Додати/оновити запис для інвайта, перша спроба перевірки не раніше ніж через start_after_sec.
    ВАЖЛИВО: при повторних викликах ми скидаємо tries=0 і ставимо next_check_at=now+start_after_sec,
    щоб не «залипав» далекий backoff після прийняття заявки.
    """
    with SessionLocal() as s:
        row = s.get(InviteCheck, {"invite_hash": invite_hash, "session": session})
        now = _now()
        if row is None:
            row = InviteCheck(
                invite_hash=invite_hash,
                session=session,
                noted_at=now,
                next_check_at=now + int(start_after_sec),
                tries=0,
            )
            s.add(row)
            log.debug("[note_requested_invite] set sess=%s invite=%s next=%d", session, invite_hash, row.next_check_at)
        else:
            row.noted_at = now  # оновлюємо час останньої ноти
            row.tries = 0
            row.next_check_at = now + int(start_after_sec)
            s.add(row)
            log.debug("[note_requested_invite] update+reset sess=%s invite=%s tries=%d next=%d",
                      session, invite_hash, row.tries, row.next_check_at)
        s.commit()

def get_invite_sessions(invite_hash: str) -> List[str]:
    """
    Повертає список сесій, для яких уже існує pending-запис цього інвайта.
    Використовується, щоб НЕ створювати нові записи на «випадкову» сесію.
    """
    with SessionLocal() as s:
        q = select(InviteCheck.session).where(InviteCheck.invite_hash == invite_hash)
        rows = s.execute(q).scalars().all()
        out = [r for r in rows if r]
        log.debug("[get_invite_sessions] invite=%s sessions=%s", invite_hash, out)
        return out

def due_invites(sessions: Sequence[str], limit: int) -> List[InviteCheck]:
    """
    Вибрати due інвайти для заданих сесій.
    """
    if not sessions:
        log.debug("[due_invites] fetched=0")
        return []
    now = _now()
    with SessionLocal() as s:
        q = (
            select(InviteCheck)
            .where(InviteCheck.session.in_(sessions))
            .where(InviteCheck.next_check_at <= now)
            .order_by(InviteCheck.next_check_at.asc())
            .limit(int(limit))
        )
        rows = list(s.execute(q).scalars().all())
        log.debug("[due_invites] fetched=%d", len(rows))
        return rows

def backoff_invite_miss(session: str, invite_hash: str) -> None:
    """
    Немає рішення ще — збільшити tries і зрушити next_check_at.
    """
    with SessionLocal() as s:
        row = s.get(InviteCheck, {"invite_hash": invite_hash, "session": session})
        if not row:
            # дефенсивно: якщо раптом нема, створимо наново з маленьким бекофом
            note_requested_invite(session, invite_hash, start_after_sec=INVITE_BACKOFF_BASE)
            return
        row.tries = (row.tries or 0) + 1
        row.next_check_at = _calc_next(INVITE_BACKOFF_BASE, row.tries, INVITE_BACKOFF_MAX)
        s.add(row)
        s.commit()
        log.debug("[backoff_invite_miss] sess=%s invite=%s tries=%d next=%d",
                  session, invite_hash, row.tries, row.next_check_at)

def clear_invite(session: str, invite_hash: str) -> None:
    with SessionLocal() as s:
        row = s.get(InviteCheck, {"invite_hash": invite_hash, "session": session})
        if row:
            s.delete(row)
            s.commit()
            log.debug("[clear_invite] removed sess=%s invite=%s", session, invite_hash)

# ---------------------------------------------------------------------
# API — REQUESTED (channel_id)
# ---------------------------------------------------------------------
def note_requested(session: str, channel_id: int, start_after_sec: int = 60) -> None:
    """
    Додати/оновити запис для requested за channel_id.
    Як і для інвайтів — при повторних викликах скидаємо tries=0 і прискорюємо наступну перевірку.
    """
    with SessionLocal() as s:
        pk = {"session": session, "channel_id": int(channel_id)}
        row = s.get(RequestedCheck, pk)
        now = _now()
        if row is None:
            row = RequestedCheck(
                session=session,
                channel_id=int(channel_id),
                noted_at=now,
                next_check_at=now + int(start_after_sec),
                tries=0,
            )
            s.add(row)
            log.debug("[note_requested] set sess=%s cid=%s next=%d", session, channel_id, row.next_check_at)
        else:
            row.noted_at = now
            row.tries = 0
            row.next_check_at = now + int(start_after_sec)
            s.add(row)
            log.debug("[note_requested] update+reset sess=%s cid=%s tries=%d next=%d",
                      session, channel_id, row.tries, row.next_check_at)
        s.commit()

def due_requested(sessions: Sequence[str], per_account: int, limit: int) -> List[RequestedCheck]:
    """
    Вибрати due requested для набору сесій.
    Ми віддаємо до `limit` рядків загалом.
    """
    if not sessions:
        log.debug("[due_requested] fetched=0 (raw=0, sessions=0, per_account=%d, limit=%d)", per_account, limit)
        return []
    now = _now()
    with SessionLocal() as s:
        q = (
            select(RequestedCheck)
            .where(RequestedCheck.session.in_(sessions))
            .where(RequestedCheck.next_check_at <= now)
            .order_by(RequestedCheck.next_check_at.asc())
            .limit(int(limit))
        )
        rows = list(s.execute(q).scalars().all())
        log.debug("[due_requested] fetched=%d (raw=%d, sessions=%d, per_account=%d, limit=%d)",
                  len(rows), len(rows), len(sessions), per_account, limit)
        return rows

def backoff_miss(session: str, channel_id: int) -> None:
    """
    Немає рішення ще — збільшуємо tries і пересуваємо next_check_at.
    """
    with SessionLocal() as s:
        pk = {"session": session, "channel_id": int(channel_id)}
        row = s.get(RequestedCheck, pk)
        if not row:
            # дефенсивно
            note_requested(session, int(channel_id), start_after_sec=REQ_BACKOFF_BASE)
            return
        row.tries = (row.tries or 0) + 1
        row.next_check_at = _calc_next(REQ_BACKOFF_BASE, row.tries, REQ_BACKOFF_MAX)
        s.add(row)
        s.commit()
        log.debug("[backoff_miss] sess=%s cid=%s tries=%d next=%d",
                  session, channel_id, row.tries, row.next_check_at)

def clear(session: str, channel_id: int) -> None:
    with SessionLocal() as s:
        pk = {"session": session, "channel_id": int(channel_id)}
        row = s.get(RequestedCheck, pk)
        if row:
            s.delete(row)
            s.commit()
            log.debug("[clear] removed sess=%s cid=%s", session, channel_id)

def is_requested(session: str, channel_id: int) -> bool:
    with SessionLocal() as s:
        pk = {"session": session, "channel_id": int(channel_id)}
        row = s.get(RequestedCheck, pk)
        return bool(row)