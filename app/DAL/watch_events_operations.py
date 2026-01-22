from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select, update

from app.db import models as m
from app.utils.time_utils import moscow_now_str
from app.DAL.schemas.watch_event import WatchEventRecord, WatchEventRecordListAdapter
from app.db.session import session_scope


def _now_str() -> str:
    return moscow_now_str()


def insert_watch_event(
    watch_id: int,
    event_type: str,
    payload_json: str,
    created_at: Optional[str] = None,
) -> None:
    with session_scope() as db:
        db.add(
            m.WatchEvent(
                watch_id=int(watch_id),
                event_type=str(event_type),
                payload_json=payload_json,
                created_at=created_at or _now_str(),
            )
        )


def fetch_unsent_events(limit: int = 100) -> List[WatchEventRecord]:
    with session_scope() as db:
        rows = db.execute(
            select(
                m.WatchEvent.id,
                m.WatchEvent.watch_id,
                m.WatchEvent.event_type,
                m.WatchEvent.payload_json,
                m.WatchEvent.created_at,
            )
            .where(m.WatchEvent.sent_at.is_(None))
            .order_by(m.WatchEvent.id.asc())
            .limit(int(limit))
        ).all()
        return WatchEventRecordListAdapter.validate_python(rows)


def mark_event_sent(event_id: int, sent_to: int) -> None:
    now_str = _now_str()
    with session_scope() as db:
        db.execute(
            update(m.WatchEvent)
            .where(m.WatchEvent.id == int(event_id), m.WatchEvent.sent_at.is_(None))
            .values(sent_to=int(sent_to), sent_at=now_str)
        )
