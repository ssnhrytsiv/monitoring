from __future__ import annotations

import os
import time
import logging
from typing import Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import (
    create_engine, event, Integer, String, PrimaryKeyConstraint, Index,
    select, func, update
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
INVITE_BACKOFF_BASE = int(os.getenv("REQUESTED_INVITE_BACKOFF_BASE", "15"))    # сек
INVITE_BACKOFF_MAX  = int(os.getenv("REQUESTED_INVITE_BACKOFF_MAX", "3600"))   # сек
REQ_BACKOFF_BASE    = int(os.getenv("REQUESTED_BACKOFF_BASE", "30"))           # сек
REQ_BACKOFF_MAX     = int(os.getenv("REQUESTED_BACKOFF_MAX", "3600"))          # сек

# Нове: Множник експоненційного зростання (щоб зробити крок більшим)
# Для requested за замовчуванням робимо агресивніше (×3), для invites лишаємо ×2.
INVITE_BACKOFF_FACTOR = float(os.getenv("REQUESTED_INVITE_BACKOFF_FACTOR", "2.0") or "2.0")
REQ_BACKOFF_FACTOR    = float(os.getenv("REQUESTED_BACKOFF_FACTOR", "5.0") or "5.0")

# Мінімальний інтервал до наступної ПОВТОРНОЇ перевірки інвайта
# Тепер 6 годин за замовчуванням (21600 секунд)
INVITE_RECHECK_MIN_SEC = int(os.getenv("REQUESTED_RECONCILER_INVITE_RECHECK_MIN_SEC", "200") or "200")

# Анти-дребезг для повторних note_requested_invite
INVITE_NOTE_DEBOUNCE_SEC = int(os.getenv("REQUESTED_RECONCILER_INVITE_NOTE_DEBOUNCE_SEC", "60") or "60")
INVITE_NOTE_RESET_LIMIT_PER_HOUR = int(os.getenv("REQUESTED_RECONCILER_INVITE_RESET_LIMIT_PER_HOUR", "120") or "120")

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

def _calc_next(base: int, tries: int, max_cap: int, factor: float = 2.0) -> int:
    """
    Експоненційний backoff: base * (factor ** tries), обрізаний max_cap.
    Повертає epoch-second when to run next.
    """
    try:
        step = base * (factor ** max(0, tries))
    except Exception:
        step = base * (2 ** max(0, tries))
    step = int(step)
    step = min(max_cap, step)
    return _now() + step

# ---------------------------------------------------------------------
# Внутрішні: анти-дребезг для note_requested_invite
# ---------------------------------------------------------------------
# Пам'ять для ліміту скидань на годину
_note_reset_window = {}  # key: (session, invite_hash) -> dict(start:int, count:int)

def _allow_note_reset(session: str, invite_hash: str, now_ts: int) -> bool:
    """
    Повертає True, якщо можна робити reset (tries=0/next_check_at оновлення) у note_requested_invite.
    Лімітуємо:
      - мін. інтервал між нотами для одного інвайта (debounce),
      - макс. кількість reset'ів на годину.
    """
    key = (session, invite_hash)

    # debounce по часу: беремо останній noted_at з БД (останньо закомічений)
    with SessionLocal() as s:
        row = s.get(InviteCheck, {"invite_hash": invite_hash, "session": session})
        last_noted = row.noted_at if row else 0
    if now_ts - last_noted < INVITE_NOTE_DEBOUNCE_SEC:
        return False

    # кап на кількість reset'ів на годину (в ін-меморі)
    win = _note_reset_window.get(key)
    if not win or now_ts - win["start"] > 3600:
        win = {"start": now_ts, "count": 0}
        _note_reset_window[key] = win

    if win["count"] >= INVITE_NOTE_RESET_LIMIT_PER_HOUR:
        return False

    win["count"] += 1
    return True

# ---------------------------------------------------------------------
# API — INVITE
# ---------------------------------------------------------------------
def note_requested_invite(session: str, invite_hash: str, start_after_sec: int = 60) -> None:
    """
    Додати/оновити запис для інвайта.

    Поведінка:
    - Якщо інвайт новий → ставимо першу перевірку через start_after_sec (деф. 60с).
    - Якщо інвайт повторний → не робимо "прискорення" занадто часто (anti-bounce) і
      ГАРАНТУЄМО, що повторна перевірка не раніше, ніж через INVITE_RECHECK_MIN_SEC (деф. 6 год).
    """
    with SessionLocal() as s:
        row = s.get(InviteCheck, {"invite_hash": invite_hash, "session": session})
        now = _now()
        if row is None:
            # перша поява інвайта: швидка перша спроба
            row = InviteCheck(
                invite_hash=invite_hash,
                session=session,
                noted_at=now,
                next_check_at=now + int(start_after_sec),
                tries=0,
            )
            s.add(row)
            s.commit()
            log.debug("[note_requested_invite] set sess=%s invite=%s next=%d", session, invite_hash, row.next_check_at)
            return

        prev_noted = row.noted_at or 0  # зберігаємо попереднє значення noted_at для debounce-перевірки

        # Анти-дребезг за часом від попередньої ноти
        if now - prev_noted < INVITE_NOTE_DEBOUNCE_SEC:
            # лише оновимо noted_at для інформації (опційно), без reset/backoff
            row.noted_at = now
            s.add(row)
            s.commit()
            log.debug(
                "[note_requested_invite] debounce skip sess=%s invite=%s keep next=%d tries=%d (dt=%ds < %ds)",
                session, invite_hash, row.next_check_at, row.tries, now - prev_noted, INVITE_NOTE_DEBOUNCE_SEC
            )
            return

        # Додатковий ліміт скидань на годину
        if not _allow_note_reset(session, invite_hash, now):
            row.noted_at = now
            s.add(row)
            s.commit()
            log.debug("[note_requested_invite] hourly cap skip sess=%s invite=%s keep next=%d tries=%d",
                      session, invite_hash, row.next_check_at, row.tries)
            return

        # Дозволений reset: tries=0, але НЕ раніше ніж через INVITE_RECHECK_MIN_SEC від зараз
        row.tries = 0
        row.noted_at = now
        min_next = now + INVITE_RECHECK_MIN_SEC
        row.next_check_at = max(row.next_check_at or 0, min_next)
        s.add(row)
        s.commit()
        log.debug(
            "[note_requested_invite] update+reset(sess=%s invite=%s) tries=%d next=%d(>=now+%ds)",
            session, invite_hash, row.tries, row.next_check_at, INVITE_RECHECK_MIN_SEC
        )

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

    Гарантія: повторна перевірка буде НЕ РАНІШЕ ніж через INVITE_RECHECK_MIN_SEC від теперішнього моменту.
    """
    with SessionLocal() as s:
        row = s.get(InviteCheck, {"invite_hash": invite_hash, "session": session})
        if not row:
            # дефенсивно: якщо раптом нема, створимо наново з маленьким бекофом
            note_requested_invite(session, invite_hash, start_after_sec=INVITE_BACKOFF_BASE)
            return
        now = _now()
        row.tries = (row.tries or 0) + 1
        exp_next = _calc_next(INVITE_BACKOFF_BASE, row.tries, INVITE_BACKOFF_MAX, factor=INVITE_BACKOFF_FACTOR)
        # Підлога: не раніше ніж через INVITE_RECHECK_MIN_SEC від зараз (6 год за замовчуванням)
        floor_next = now + INVITE_RECHECK_MIN_SEC
        row.next_check_at = max(exp_next, floor_next)
        s.add(row)
        s.commit()
        log.debug(
            "[backoff_invite_miss] sess=%s invite=%s tries=%d next=%d(>=now+%ds)",
            session, invite_hash, row.tries, row.next_check_at, INVITE_RECHECK_MIN_SEC
        )

def defer_invite_until(session: str, invite_hash: str, next_ts_epoch: int) -> None:
    """
    Гарантує next_check_at >= next_ts_epoch для конкретного інвайта. НЕ змінює tries.
    """
    with SessionLocal() as s:
        next_ts_epoch = int(next_ts_epoch)
        stmt = (
            update(InviteCheck)
            .where(InviteCheck.session == session, InviteCheck.invite_hash == invite_hash)
            .where(InviteCheck.next_check_at < next_ts_epoch)
            .values(next_check_at=next_ts_epoch)
        )
        res = s.execute(stmt)
        s.commit()
        log.debug("[defer_invite_until] sess=%s invite=%s set next>=%d rows=%d",
                  session, invite_hash, next_ts_epoch, res.rowcount or 0)

def bulk_defer_session_invites(session: str, next_ts_epoch: int) -> None:
    """
    Масово зсуває next_check_at для ВСІХ інвайтів сесії до не раніше ніж next_ts_epoch. НЕ змінює tries.
    """
    with SessionLocal() as s:
        next_ts_epoch = int(next_ts_epoch)
        stmt = (
            update(InviteCheck)
            .where(InviteCheck.session == session)
            .where(InviteCheck.next_check_at < next_ts_epoch)
            .values(next_check_at=next_ts_epoch)
        )
        res = s.execute(stmt)
        s.commit()
        log.debug("[bulk_defer_session_invites] sess=%s set next>=%d rows=%d",
                  session, next_ts_epoch, res.rowcount or 0)

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
    ТЕПЕР: використовуємо більший крок (factor=REQ_BACKOFF_FACTOR, за замовчуванням ×3).
    """
    with SessionLocal() as s:
        pk = {"session": session, "channel_id": int(channel_id)}
        row = s.get(RequestedCheck, pk)
        if not row:
            # дефенсивно
            note_requested(session, int(channel_id), start_after_sec=REQ_BACKOFF_BASE)
            return
        row.tries = (row.tries or 0) + 1
        row.next_check_at = _calc_next(REQ_BACKOFF_BASE, row.tries, REQ_BACKOFF_MAX, factor=REQ_BACKOFF_FACTOR)
        s.add(row)
        s.commit()
        log.debug("[backoff_miss] sess=%s cid=%s tries=%d next=%d (factor=%.2f)",
                  session, channel_id, row.tries, row.next_check_at, REQ_BACKOFF_FACTOR)

def bulk_defer_session_requested(session: str, next_ts_epoch: int) -> None:
    """
    Масово зсуває next_check_at для ВСІХ requested-записів сесії до не раніше ніж next_ts_epoch. НЕ змінює tries.
    """
    with SessionLocal() as s:
        next_ts_epoch = int(next_ts_epoch)
        stmt = (
            update(RequestedCheck)
            .where(RequestedCheck.session == session)
            .where(RequestedCheck.next_check_at < next_ts_epoch)
            .values(next_check_at=next_ts_epoch)
        )
        res = s.execute(stmt)
        s.commit()
        log.debug("[bulk_defer_session_requested] sess=%s set next>=%d rows=%d",
                  session, next_ts_epoch, res.rowcount or 0)

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