from __future__ import annotations

import time
from typing import Optional
from sqlalchemy.orm import Session

from app.db import models as m


def log_conflict(
    db: Session,
    *,
    channel_id: int,
    owner: str,
    source_ref: Optional[str] = None,
    reason: str = "owner_conflict",
) -> None:
    now = int(time.time())
    db.add(
        m.OwnerConflict(
            owner=owner,
            channel_id=channel_id,
            source_ref=source_ref,
            reason=reason,
            created_at=now,
        )
    )
    db.commit()
