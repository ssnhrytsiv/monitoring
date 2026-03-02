"""
Data Access Layer package.

Тут збиратимуться DAO/репозиторії, що працюють зі спільним SessionLocal/ORM.
"""

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session

from app.db.session import SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    database_session: Session = SessionLocal()
    try:
        yield database_session
        database_session.commit()
    except Exception:
        database_session.rollback()
        raise
    finally:
        database_session.close()

__all__ = ["SessionLocal", "session_scope"]
