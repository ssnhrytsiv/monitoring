from __future__ import annotations

from sqlalchemy.engine import Engine

from app.admin_bot.db.session import Base, SessionLocal, engine
from app.admin_bot.db import models as m

# re-export models for backward compatibility
WatchGroup = m.WatchGroup
WatchPost = m.WatchPost
WatchEvent = m.WatchEvent
WatchCandidate = m.WatchCandidate


def get_engine() -> Engine:
    return engine


def init_schema() -> None:
    """
    Створює таблиці, якщо вони ще не існують.
    (Міграції все одно треба робити через Alembic.)
    """
    Base.metadata.create_all(bind=engine)
