from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from app.admin_bot.db.session import SessionLocal
from app.admin_bot.db import models as m

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def _now_str() -> str:
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d %H:%M:%S")


def insert_watch_event(
    watch_id: int,
    event_type: str,
    payload_json: str,
    created_at: Optional[str] = None,
) -> None:
    db = SessionLocal()
    try:
        db.add(
            m.WatchEvent(
                watch_id=int(watch_id),
                event_type=str(event_type),
                payload_json=payload_json,
                created_at=created_at or _now_str(),
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def fetch_unsent_events(limit: int = 100) -> List[Tuple[int, int, str, str, str]]:
    db = SessionLocal()
    try:
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
    finally:
        db.close()
    return [
        (
            int(r.id),
            int(r.watch_id),
            str(r.event_type),
            str(r.payload_json or ""),
            str(r.created_at or ""),
        )
        for r in rows
    ]


def mark_event_sent(event_id: int, sent_to: int) -> None:
    db = SessionLocal()
    try:
        now_str = _now_str()
        db.execute(
            update(m.WatchEvent)
            .where(m.WatchEvent.id == int(event_id), m.WatchEvent.sent_at.is_(None))
            .values(sent_to=int(sent_to), sent_at=now_str)
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
