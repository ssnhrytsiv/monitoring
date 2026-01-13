from __future__ import annotations

import time
from typing import Optional
from sqlalchemy.orm import Session

from app.admin_bot.db import models as m


def upsert_channel_full(
    db: Session,
    *,
    channel_id: int,
    username: Optional[str] = None,
    title: Optional[str] = None,
    owner_display: Optional[str] = None,
    owner_username: Optional[str] = None,
    last_status: Optional[str] = None,
) -> m.Channel:
    """
    Локальний upsert для channels з основними полями.
    created_at оновлюємо лише при створенні, updated_at – завжди.
    """
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    ch = db.query(m.Channel).filter(m.Channel.channel_id == channel_id).one_or_none()
    if ch:
        if username and not ch.username:
            ch.username = username
        if title and not ch.title:
            ch.title = title
        if owner_display:
            ch.owner_display = owner_display
        if owner_username:
            ch.owner_username = owner_username
        if last_status:
            ch.last_status = last_status
        ch.updated_at = now
    else:
        ch = m.Channel(
            channel_id=channel_id,
            username=username,
            title=title,
            owner_display=owner_display,
            owner_username=owner_username,
            last_status=last_status,
            created_at=now,
            updated_at=now,
        )
        db.add(ch)
    db.commit()
    db.refresh(ch)
    return ch
