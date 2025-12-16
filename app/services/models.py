# app/services/models.py
from __future__ import annotations

import os
import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import (
    create_engine,
    event,
    Column,
    Integer,
    Text,
    String,
    BigInteger,
    PrimaryKeyConstraint,
    Index,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# -----------------------------------------------------------------------------
# ЛОГІНГ
# -----------------------------------------------------------------------------
log = logging.getLogger("services.models")

# -----------------------------------------------------------------------------
# НАЛАШТУВАННЯ БД
# -----------------------------------------------------------------------------
# важливо: шлях той самий, що й у старих модульних функціях (post_watchdog.sqlite3)
DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")

def _mk_sqlite_url(path: str) -> str:
    # відносний шлях → sqlite:///file.db ; абсолютний → sqlite:////abs/file.db
    if os.path.isabs(path):
        return f"sqlite:///{path}"
    return f"sqlite:///{os.path.abspath(path)}"

SQLALCHEMY_DATABASE_URI = _mk_sqlite_url(DB_PATH)

# echo=False (SQLAlchemy SQL-echo не використовуємо; ми і так даємо нормальні логи)
# pool_pre_ping=True на випадок реюзу engine в довгоживучих процесах
_engine: Engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    echo=False,
    pool_pre_ping=True,
    future=True,
)

# Увімкнемо WAL + розумні PRAGMA для sqlite під час connect
@event.listens_for(_engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    try:
        cur = dbapi_conn.cursor()
        # WAL для кращої concurency
        cur.execute("PRAGMA journal_mode=WAL;")
        # Щоб не ловити дрібні блокування
        cur.execute("PRAGMA busy_timeout=3000;")
        cur.close()
        log.debug("[models] SQLite PRAGMA applied (WAL, busy_timeout=3000)")
    except Exception as e:
        log.warning("[models] SQLite PRAGMA apply failed: %s", e)

SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()

# -----------------------------------------------------------------------------
# ORM-МОДЕЛІ (імена полів збережені 1-в-1 із SQL схемою)
# -----------------------------------------------------------------------------

class Membership(Base):
    """
    CREATE TABLE membership (
      channel_id INTEGER NOT NULL,
      account    TEXT    NOT NULL,
      status     TEXT    NOT NULL,   -- joined/already/requested/invalid/private/blocked/too_many
      ts         INTEGER NOT NULL,
      PRIMARY KEY (channel_id, account)
    );
    CREATE INDEX idx_membership_channel ON membership(channel_id);
    CREATE INDEX idx_membership_status  ON membership(status);
    """
    __tablename__ = "membership"

    channel_id = Column(Integer, nullable=False)
    account    = Column(Text,    nullable=False)
    status     = Column(Text,    nullable=False)
    ts         = Column(Integer, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("channel_id", "account", name="pk_membership"),
        Index("idx_membership_channel", "channel_id"),
        Index("idx_membership_status",  "status"),
    )

    def __repr__(self) -> str:
        return f"<Membership channel_id={self.channel_id} account={self.account} status={self.status} ts={self.ts}>"


class InviteMap(Base):
    """
    CREATE TABLE invite_map (
      invite_hash TEXT PRIMARY KEY,
      channel_id  INTEGER,
      title       TEXT,
      updated_at  INTEGER
    );
    """
    __tablename__ = "invite_map"

    invite_hash = Column(Text, primary_key=True)
    channel_id  = Column(Integer, nullable=True)
    title       = Column(Text,    nullable=True)
    updated_at  = Column(Integer, nullable=True)

    def __repr__(self) -> str:
        return f"<InviteMap invite_hash={self.invite_hash} channel_id={self.channel_id} title={self.title}>"


class InviteStatus(Base):
    """
    CREATE TABLE invite_status (
      invite_hash TEXT PRIMARY KEY,
      status      TEXT    NOT NULL,  -- joined/already/requested/invalid/private/blocked/too_many
      ts          INTEGER NOT NULL
    );
    """
    __tablename__ = "invite_status"

    invite_hash = Column(Text, primary_key=True)
    status      = Column(Text,    nullable=False)
    ts          = Column(Integer, nullable=False)

    def __repr__(self) -> str:
        return f"<InviteStatus invite_hash={self.invite_hash} status={self.status} ts={self.ts}>"


class UrlCache(Base):
    """
    CREATE TABLE url_cache (
      url    TEXT PRIMARY KEY,
      status TEXT    NOT NULL,       -- joined/already/requested/invalid/private
      ts     INTEGER NOT NULL
    );
    """
    __tablename__ = "url_cache"

    url    = Column(Text, primary_key=True)
    status = Column(Text,    nullable=False)
    ts     = Column(Integer, nullable=False)

    def __repr__(self) -> str:
        return f"<UrlCache url={self.url} status={self.status} ts={self.ts}>"


class InviteCheck(Base):
    """
    CREATE TABLE invite_check (
      session       TEXT    NOT NULL,
      invite_hash   TEXT    NOT NULL,
      noted_at      INTEGER NOT NULL,
      next_check_at INTEGER NOT NULL,
      tries         INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (session, invite_hash)
    );
    CREATE INDEX idx_invite_check_next    ON invite_check(next_check_at);
    CREATE INDEX idx_invite_check_session ON invite_check(session);
    """
    __tablename__ = "invite_check"

    session       = Column(Text,    nullable=False)
    invite_hash   = Column(Text,    nullable=False)
    noted_at      = Column(Integer, nullable=False)
    next_check_at = Column(Integer, nullable=False)
    tries         = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        PrimaryKeyConstraint("session", "invite_hash", name="pk_invite_check"),
        Index("idx_invite_check_next",    "next_check_at"),
        Index("idx_invite_check_session", "session"),
    )

    def __repr__(self) -> str:
        return (
            f"<InviteCheck session={self.session} invite_hash={self.invite_hash} "
            f"next_check_at={self.next_check_at} tries={self.tries}>"
        )


class RequestedCheck(Base):
    """
    CREATE TABLE requested_check (
      session       TEXT    NOT NULL,
      channel_id    INTEGER NOT NULL,
      noted_at      INTEGER NOT NULL,
      next_check_at INTEGER NOT NULL,
      tries         INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (session, channel_id)
    );
    CREATE INDEX idx_requested_check_next    ON requested_check(next_check_at);
    CREATE INDEX idx_requested_check_session ON requested_check(session);
    """
    __tablename__ = "requested_check"

    session       = Column(Text,    nullable=False)
    channel_id    = Column(Integer, nullable=False)
    noted_at      = Column(Integer, nullable=False)
    next_check_at = Column(Integer, nullable=False)
    tries         = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        PrimaryKeyConstraint("session", "channel_id", name="pk_requested_check"),
        Index("idx_requested_check_next",    "next_check_at"),
        Index("idx_requested_check_session", "session"),
    )

    def __repr__(self) -> str:
        return (
            f"<RequestedCheck session={self.session} channel_id={self.channel_id} "
            f"next_check_at={self.next_check_at} tries={self.tries}>"
        )

# -----------------------------------------------------------------------------
# СЕРВІСНІ ХЕЛПЕРИ
# -----------------------------------------------------------------------------

def get_engine() -> Engine:
    """Повертає загальний Engine. Лог один раз при першому зверненні."""
    log.debug("[models] get_engine -> %s", SQLALCHEMY_DATABASE_URI)
    return _engine

def get_session_factory():
    """Повертає sessionmaker — корисно, якщо треба інʼєктити фабрику."""
    return SessionLocal

@contextmanager
def session_scope() -> Iterator[Session]:
    """
    Контекст для коротких юнітів роботи з БД.
    Завжди логікує відкриття/commit/rollback/close — для простого дебагу.
    """
    session: Session = SessionLocal()
    log.debug("[models] session open")
    try:
        yield session
        session.commit()
        log.debug("[models] session commit ok")
    except Exception as e:
        log.exception("[models] session rollback due to error: %s", e)
        session.rollback()
        raise
    finally:
        session.close()
        log.debug("[models] session close")

def init_db() -> None:
    """
    Ідempotent create_all за ORM-моделями.
    Ти вже піднімаєш базові таблиці окремо — але цей метод не завадить:
    він просто створить відсутні таблиці за потреби.
    """
    log.info("[models] Initializing ORM metadata… (create_all)")
    Base.metadata.create_all(bind=_engine)
    log.info("[models] ORM metadata init done")