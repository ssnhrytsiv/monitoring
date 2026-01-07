from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import (
    BigInteger,
    Column,
    Index,
    Integer,
    String,
    Text,
    Float,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.sql import expression

log = logging.getLogger("services.posts_watch_result_models")

# DB path бере ту ж змінну, що й старий модуль
DB_PATH = (
    os.environ.get("POSTS_WATCH_RESULT_DB_PATH")
    or os.environ.get("DB_PATH")
    or "post_watchdog.sqlite3"
)


def _mk_sqlite_url(path: str) -> str:
    # Відносний шлях → sqlite:///file.db ; абсолютний → sqlite:////abs/file.db
    if os.path.isabs(path):
        return f"sqlite:///{path}"
    return f"sqlite:///{os.path.abspath(path)}"


SQLALCHEMY_DATABASE_URI = _mk_sqlite_url(DB_PATH)

# Пул/engine
_engine: Engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    echo=False,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(_engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    try:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA busy_timeout=3000;")
        cur.close()
        log.debug("[posts_watch_result_models] SQLite PRAGMA applied (WAL, NORMAL, busy_timeout=3000)")
    except Exception as e:
        log.warning("[posts_watch_result_models] SQLite PRAGMA apply failed: %s", e)


SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


class WatchGroup(Base):
    __tablename__ = "watch_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project = Column(Text, nullable=True)
    title = Column(Text, nullable=True)
    created_by = Column(BigInteger, nullable=True)
    created_via = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)
    admin_id = Column(Integer, nullable=True)
    network_id = Column(Integer, nullable=True)


class WatchPost(Base):
    __tablename__ = "watch_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(BigInteger, nullable=True)
    template_id = Column(Integer, nullable=True)
    expected_text_hash = Column(Text, nullable=True)
    expected_text_norm_len = Column(Integer, nullable=True)
    expected_links_json = Column(Text, nullable=True)
    expected_media_fingerprint = Column(Text, nullable=True)
    time_window_start = Column(Text, nullable=True)
    time_window_end = Column(Text, nullable=True)
    status = Column(Text, nullable=True)
    matched_message_id = Column(BigInteger, nullable=True)
    matched_at = Column(Text, nullable=True)
    coverage_check_at = Column(Text, nullable=True)
    final_views = Column(Integer, nullable=True)
    deleted_at = Column(Text, nullable=True)
    created_at = Column(Text, nullable=True)
    updated_at = Column(Text, nullable=True)
    matched_session = Column(Text, nullable=True)
    source_url = Column(Text, nullable=True)
    created_by = Column(BigInteger, nullable=True)
    created_via = Column(Text, nullable=True)
    project = Column(Text, nullable=True)
    group_id = Column(BigInteger, nullable=True)
    admin_id = Column(Integer, nullable=True)
    network_id = Column(Integer, nullable=True)
    posted_at = Column(Text, nullable=True)
    views_at_post = Column(Integer, nullable=True)
    subs_at_post = Column(Integer, nullable=True)
    cpm_at_post = Column(Float, nullable=True)
    price_at_post = Column(Float, nullable=True)

    __table_args__ = (
        Index("idx_wp_channel", "channel_id"),
        Index("idx_wp_status", "status"),
        Index("idx_wp_covcheck", "coverage_check_at"),
        Index("idx_wp_matched_session", "matched_session"),
        Index("idx_wp_created_by", "created_by"),
        Index("idx_wp_group", "group_id"),
        Index("idx_wp_posted_at", "posted_at"),
        Index("idx_wp_admin", "admin_id"),
        Index("idx_wp_network", "network_id"),
        Index(
            "uq_active_watch",
            "channel_id",
            "template_id",
            "expected_text_hash",
            unique=True,
            sqlite_where=expression.text("status IN ('pending','matched')"),
        ),
    )


class WatchEvent(Base):
    __tablename__ = "watch_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    watch_id = Column(BigInteger, nullable=False)
    event_type = Column(String, nullable=False)
    payload_json = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)
    sent_to = Column(BigInteger, nullable=True)
    sent_at = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_we_sent_at", "sent_at"),
        Index("idx_we_unsent", "sent_at", "id"),
    )


class WatchCandidate(Base):
    __tablename__ = "watch_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    watch_id = Column(BigInteger, nullable=False)
    channel_id = Column(BigInteger, nullable=True)
    message_id = Column(BigInteger, nullable=True)
    text_hash = Column(Text, nullable=True)
    similarity = Column(Float, nullable=True)
    message_text = Column(Text, nullable=True)
    status = Column(String, nullable=True, default="pending")  # pending/accepted/rejected
    created_at = Column(Text, nullable=False)
    expires_at = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_wc_watch", "watch_id"),
        Index("idx_wc_status", "status"),
        Index("idx_wc_expires", "expires_at"),
    )


def get_engine() -> Engine:
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_schema() -> None:
    """
    Створює таблиці, якщо вони ще не існують.
    (Міграції все одно треба робити через Alembic.)
    """
    Base.metadata.create_all(bind=_engine)
