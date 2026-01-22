"""DAO operations for links table."""
from __future__ import annotations

import time
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.utils.link_parser import sanitize_link
from app.DAL.schemas import LinkRecord, LinkRecordListAdapter


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def add_link(
    db: Session,
    channel_id: Optional[int],
    raw_url: str,
    kind: Optional[str],
    batch_msg_id: Optional[int],
) -> None:
    if not raw_url:
        return
    try:
        url_norm = sanitize_link(raw_url) or raw_url
    except Exception:
        url_norm = raw_url
    url_norm = str(url_norm).strip() or None
    now = _now_str()
    if url_norm:
        exists = db.query(m.Link.id).filter(m.Link.url_norm == url_norm).first()
        if exists:
            return
    db.add(
        m.Link(
            channel_id=channel_id,
            url_norm=url_norm,
            kind=kind,
            batch_msg_id=batch_msg_id,
            added_at=now,
        )
    )
    db.commit()


def list_links_for_channels(db: Session, channel_ids: List[int]) -> List[LinkRecord]:
    if not channel_ids:
        return []
    return LinkRecordListAdapter.validate_python(
        db.query(m.Link)
        .filter(m.Link.channel_id.in_(channel_ids))
        .all()
    )


def delete_links_by_channels(db: Session, channel_ids: List[int]) -> int:
    if not channel_ids:
        return 0
    return (
        db.query(m.Link)
        .filter(m.Link.channel_id.in_(channel_ids))
        .delete(synchronize_session=False)
    ) or 0


def find_channel_by_link(db: Session, raw_url: str) -> Optional[LinkRecord]:
    try:
        norm = sanitize_link(raw_url) or raw_url
    except Exception:
        norm = raw_url
    norm = str(norm).strip() or None
    if not norm:
        return None
    row = (
        db.query(m.Link.channel_id, m.Channel.title)
        .outerjoin(m.Channel, m.Channel.channel_id == m.Link.channel_id)
        .filter(m.Link.url_norm == norm, m.Link.channel_id.isnot(None))
        .order_by(m.Link.id.desc())
        .limit(1)
        .one_or_none()
    )
    if not row:
        return None
    channel_id_val, title_val = row
    if channel_id_val is None:
        return None
    return LinkRecord(channel_id=int(channel_id_val), title=title_val)
