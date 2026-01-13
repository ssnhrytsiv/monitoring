"""Unified DB session factory for the project.

This module re-exports the single SQLAlchemy engine/session/Base that already
lives in ``app.admin_bot.db.session`` so the rest of the codebase can import from a
neutral ``app.db`` namespace and avoid multiple factories.
"""

from app.admin_bot.db.session import Base, SessionLocal, engine, get_session  # re-export

__all__ = ["Base", "SessionLocal", "engine", "get_session"]
