# app/services/owner_conflict_guard.py
import hashlib
import time
from contextlib import contextmanager
from typing import Optional, Tuple

from app.db.session import SessionLocal
from app.db import models as m

_initialized = False


def _now() -> int:
    return int(time.time())


def _idem(owner: str, source_ref: str, action: str) -> str:
    s = f"{owner}|{source_ref}|{action}".encode("utf-8")
    return hashlib.sha256(s).hexdigest()


@contextmanager
def _db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init() -> None:
    """
    Ініціалізація guard: для ORM таблиці вже створені міграціями, тому тут лише прапорець.
    """
    global _initialized
    _initialized = True


def begin(owner: str, source_ref: str, action: str) -> Tuple[bool, str]:
    """
    Повертає (started, key). Якщо idempotency_key вже існує – повертає False.
    """
    key = _idem(owner, source_ref, action)
    with _db() as db:
        exists = db.query(m.OwnerAction).filter(m.OwnerAction.idempotency_key == key).one_or_none()
        if exists:
            return False, key
        db.add(
            m.OwnerAction(
                owner=owner,
                source_ref=source_ref,
                action=action,
                idempotency_key=key,
                status="in_progress",
                created_at=_now(),
                updated_at=_now(),
            )
        )
        db.commit()
        return True, key


def end(owner: str, source_ref: str, action: str, result: str) -> None:
    key = _idem(owner, source_ref, action)
    with _db() as db:
        db.query(m.OwnerAction).filter(m.OwnerAction.idempotency_key == key).update(
            {"status": result, "updated_at": _now()}
        )
        db.commit()


def note_conflict(owner: str, channel_id: Optional[int], source_ref: Optional[str], reason: str) -> None:
    with _db() as db:
        db.add(
            m.OwnerConflict(
                owner=owner,
                channel_id=channel_id,
                source_ref=source_ref,
                reason=reason,
                created_at=_now(),
            )
        )
        db.commit()
