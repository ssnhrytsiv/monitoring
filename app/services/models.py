# app/services/models.py
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Column, Integer, Text, PrimaryKeyConstraint, Index, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

# Використовуємо спільний engine/Base/SessionLocal з admin_bot, щоб уникнути дублювання моделей
from app.admin_bot.db.session import (
    engine as _engine,
    SessionLocal,
    Base,
    migrate_post_template_media,
    migrate_reply_flags,
)
from app.admin_bot.db import models as admin_models

log = logging.getLogger("services.models")

# ----------------------------------------------------------------------------- #
# Перепризначаємо загальні моделі на існуючі з admin_bot (щоб не дублювати код) #
# ----------------------------------------------------------------------------- #
Membership = admin_models.Membership
InviteMap = admin_models.InviteMap
InviteStatus = admin_models.InviteStatus
UrlCache = admin_models.UrlCache


# ----------------------------------------------------------------------------- #
# Додаткові моделі, яких немає в admin_bot                                    #
# ----------------------------------------------------------------------------- #

class InviteCheck(Base):
    """
    CREATE TABLE invite_check (
      invite_hash TEXT PRIMARY KEY,
      status      TEXT    NOT NULL,  -- joined/already/requested/invalid/private/blocked/too_many
      ts          INTEGER NOT NULL
    );
    """
    __tablename__ = "invite_check"

    invite_hash = Column(Text, nullable=False)
    session = Column(Text, nullable=False)
    noted_at = Column(Integer, nullable=False)
    next_check_at = Column(Integer, nullable=False)
    tries = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        PrimaryKeyConstraint("session", "invite_hash", name="pk_invite_check"),
        Index("idx_invite_check_next", "next_check_at"),
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
    """
    __tablename__ = "requested_check"

    session = Column(Text, nullable=False)
    channel_id = Column(Integer, nullable=False)
    noted_at = Column(Integer, nullable=False)
    next_check_at = Column(Integer, nullable=False)
    tries = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        PrimaryKeyConstraint("session", "channel_id", name="pk_requested_check"),
        Index("idx_requested_check_next", "next_check_at"),
        Index("idx_requested_check_session", "session"),
    )

    def __repr__(self) -> str:
        return (
            f"<RequestedCheck session={self.session} channel_id={self.channel_id} "
            f"next_check_at={self.next_check_at} tries={self.tries}>"
        )


# ----------------------------------------------------------------------------- #
# SQLite PRAGMA (reuse на спільному engine)                                     #
# ----------------------------------------------------------------------------- #
@event.listens_for(_engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    try:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA busy_timeout=3000;")
        cur.close()
        log.debug("[models] SQLite PRAGMA applied (WAL, busy_timeout=3000)")
    except Exception as e:
        log.warning("[models] SQLite PRAGMA apply failed: %s", e)


# ----------------------------------------------------------------------------- #
# Сервісні хелпери                                                              #
# ----------------------------------------------------------------------------- #

def get_engine() -> Engine:
    """Повертає спільний Engine."""
    log.debug("[models] get_engine -> %s", _engine)
    return _engine


def get_session_factory():
    """Повертає sessionmaker."""
    return SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """
    Контекст для коротких юнітів роботи з БД.
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
    """
    log.info("[models] Initializing ORM metadata… (create_all)")
    Base.metadata.create_all(bind=_engine)
    migrate_reply_flags()
    migrate_post_template_media()
    log.info("[models] ORM metadata init done")
