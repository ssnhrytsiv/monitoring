"""DAO for bot_links table (функціональний стиль)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, List

from sqlalchemy.orm import Session

from app.db import models as m


def _now_ts() -> int:
    return int(time.time())


@dataclass
class BotLinkRecord:
    username: str
    raw_url: Optional[str]
    status: Optional[str]
    session: Optional[str]
    title: Optional[str]
    owner_admin_id: Optional[int]
    owner_username: Optional[str]
    batch_id: Optional[str]
    last_ts: Optional[int]
    last_error: Optional[str]


def upsert_bot_link(
    db: Session,
    username: str,
    raw_url: Optional[str],
    status: Optional[str],
    session: Optional[str],
    title: Optional[str],
    owner_admin_id: Optional[int],
    owner_username: Optional[str],
    batch_id: Optional[str],
    last_error: Optional[str],
) -> None:
    if not username:
        return
    bot_link = db.query(m.BotLink).filter(m.BotLink.username == username).one_or_none()
    if bot_link:
        bot_link.raw_url = raw_url or bot_link.raw_url
        bot_link.status = status or bot_link.status
        bot_link.session = session or bot_link.session
        bot_link.title = title or bot_link.title
        bot_link.owner_admin_id = owner_admin_id or bot_link.owner_admin_id
        bot_link.owner_username = owner_username or bot_link.owner_username
        bot_link.batch_id = batch_id or bot_link.batch_id
        bot_link.last_error = last_error or bot_link.last_error
        bot_link.last_ts = _now_ts()
    else:
        db.add(
            m.BotLink(
                username=username,
                raw_url=raw_url,
                status=status,
                session=session,
                title=title,
                owner_admin_id=owner_admin_id,
                owner_username=owner_username,
                batch_id=batch_id,
                last_ts=_now_ts(),
                last_error=last_error,
            )
        )
    db.commit()


def get_bot_link(db: Session, username: str) -> Optional[BotLinkRecord]:
    if not username:
        return None
    bot_link = db.query(m.BotLink).filter(m.BotLink.username == username).one_or_none()
    if not bot_link:
        return None
    return BotLinkRecord(
        username=bot_link.username,
        raw_url=bot_link.raw_url,
        status=bot_link.status,
        session=bot_link.session,
        title=bot_link.title,
        owner_admin_id=bot_link.owner_admin_id,
        owner_username=bot_link.owner_username,
        batch_id=bot_link.batch_id,
        last_ts=bot_link.last_ts,
        last_error=bot_link.last_error,
    )


def delete_bot_link(db: Session, username: str) -> bool:
    if not username:
        return False
    deleted = db.query(m.BotLink).filter(m.BotLink.username == username).delete()
    db.commit()
    return deleted > 0


def list_bot_links(
    db: Session,
    owner_admin_id: Optional[int] = None,
    owner_username: Optional[str] = None,
) -> List[BotLinkRecord]:
    q = db.query(m.BotLink)
    if owner_admin_id is not None:
        q = q.filter(m.BotLink.owner_admin_id == owner_admin_id)
    if owner_username:
        q = q.filter(m.BotLink.owner_username == owner_username)
    rows = q.order_by(m.BotLink.username.asc()).all()
    return [
        BotLinkRecord(
            username=r.username,
            raw_url=r.raw_url,
            status=r.status,
            session=r.session,
            title=r.title,
            owner_admin_id=r.owner_admin_id,
            owner_username=r.owner_username,
            batch_id=r.batch_id,
            last_ts=r.last_ts,
            last_error=r.last_error,
        )
        for r in rows
    ]


def get_bot_link_by_username(db: Session, username: str) -> Optional[BotLinkRecord]:
    if not username:
        return None
    bot_link = (
        db.query(m.BotLink)
        .filter(m.BotLink.username == username)
        .order_by(m.BotLink.id.desc())
        .limit(1)
        .one_or_none()
    )
    if not bot_link:
        return None
    return BotLinkRecord(
        username=bot_link.username,
        raw_url=bot_link.raw_url,
        status=bot_link.status,
        session=bot_link.session,
        title=bot_link.title,
        owner_admin_id=bot_link.owner_admin_id,
        owner_username=bot_link.owner_username,
        batch_id=bot_link.batch_id,
        last_ts=bot_link.last_ts,
        last_error=bot_link.last_error,
    )
