from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.utils.project_paths import resolve_project_path

log = logging.getLogger("notificator.db")

# База для нотифікатора (історично post_watchdog.sqlite3)
DB_PATH = str(resolve_project_path(os.getenv("DB_PATH", "post_watchdog.sqlite3")))


def _mk_sqlite_url(path: str) -> str:
    return f"sqlite:///{resolve_project_path(path)}"


SQLALCHEMY_DATABASE_URI = _mk_sqlite_url(DB_PATH)

_engine: Engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    echo=False,
    pool_pre_ping=True,
    future=True,
)


@event.listens_for(_engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover
    try:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA busy_timeout=3000;")
        cur.close()
        log.debug("[notificator.db] SQLite PRAGMA applied (WAL, busy_timeout=3000)")
    except Exception as e:
        log.warning("[notificator.db] SQLite PRAGMA apply failed: %s", e)


SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


@contextmanager
def db_session() -> Iterator[Session]:
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = ["Base", "SessionLocal", "db_session"]
