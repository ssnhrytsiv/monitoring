from __future__ import annotations

from typing import List, Dict, Any

from sqlalchemy.orm import Session

from app.db import models as m


def find_conflicts(db: Session) -> List[Dict[str, Any]]:
    """
    У новій моделі один канал має одного власника (owner_admin_id), тому конфлікти відсутні.
    """
    return []


def resolve_conflict(db: Session, *, channel_id: int, keep_admin_id: int) -> int:
    """
    Конфліктів бути не повинно; встановлюємо owner_admin_id якщо відрізняється.
    """
    ch = db.query(m.Channel).filter(m.Channel.channel_id == channel_id).one_or_none()
    if not ch:
        return 0
    if ch.owner_admin_id != keep_admin_id:
        ch.owner_admin_id = keep_admin_id
        db.commit()
    return 0
