from __future__ import annotations

import time
from sqlalchemy.orm import Session

from admin_bot.db import models as m


def upsert_membership(db: Session, channel_id: int, account: str, status: str) -> None:
    """
    Зберігає статус підписки для пари (channel_id, account).
    """
    now = int(time.time())
    row = db.query(m.Membership).filter(
        m.Membership.channel_id == channel_id,
        m.Membership.account == account,
    ).one_or_none()
    if row:
        row.status = status
        row.ts = now
    else:
        db.add(m.Membership(channel_id=channel_id, account=account, status=status, ts=now))
    db.commit()
