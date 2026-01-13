from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session

from app.services.models import SessionLocal


@contextmanager
def get_session() -> Iterator[Session]:
    """
    Контекстний менеджер для роботи з БД у DAO/репозиторіях.
    """
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
