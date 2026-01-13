"""
DAO for bot_links table.
"""
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.admin_bot.db import models as m


def _now_ts() -> int:
    return int(time.time())


class BotLinksDAO:
    def __init__(self, db: Session):
        self.db = db

    def upsert_bot_link(
        self,
        username: str,
        raw_url: Optional[str],
        status: Optional[str],
        session: Optional[str],
        title: Optional[str],
        owner_display: Optional[str],
        owner_username: Optional[str],
        batch_id: Optional[str],
        last_error: Optional[str],
    ) -> None:
        if not username:
            return
        bot_link = self.db.query(m.BotLink).filter(m.BotLink.username == username).one_or_none()
        if bot_link:
            bot_link.raw_url = raw_url or bot_link.raw_url
            bot_link.status = status or bot_link.status
            bot_link.session = session or bot_link.session
            bot_link.title = title or bot_link.title
            bot_link.owner_display = owner_display or bot_link.owner_display
            bot_link.owner_username = owner_username or bot_link.owner_username
            bot_link.batch_id = batch_id or bot_link.batch_id
            bot_link.last_error = last_error or bot_link.last_error
            bot_link.last_ts = _now_ts()
        else:
            self.db.add(
                m.BotLink(
                    username=username,
                    raw_url=raw_url,
                    status=status,
                    session=session,
                    title=title,
                    owner_display=owner_display,
                    owner_username=owner_username,
                    batch_id=batch_id,
                    last_ts=_now_ts(),
                    last_error=last_error,
                )
            )
        self.db.commit()

    def get_bot_link(self, username: str) -> Optional[dict]:
        if not username:
            return None
        bot_link = self.db.query(m.BotLink).filter(m.BotLink.username == username).one_or_none()
        if not bot_link:
            return None
        return {
            "username": bot_link.username,
            "raw_url": bot_link.raw_url,
            "status": bot_link.status,
            "session": bot_link.session,
            "title": bot_link.title,
            "owner_display": bot_link.owner_display,
            "owner_username": bot_link.owner_username,
            "batch_id": bot_link.batch_id,
            "last_ts": bot_link.last_ts,
            "last_error": bot_link.last_error,
        }

    def delete_bot_link(self, username: str) -> bool:
        if not username:
            return False
        deleted = self.db.query(m.BotLink).filter(m.BotLink.username == username).delete()
        self.db.commit()
        return deleted > 0

    def list_bot_links(
        self, owner_display: Optional[str] = None, owner_username: Optional[str] = None
    ) -> list[dict]:
        q = self.db.query(m.BotLink)
        if owner_display:
            q = q.filter(m.BotLink.owner_display == owner_display)
        if owner_username:
            q = q.filter(m.BotLink.owner_username == owner_username)
        rows = q.order_by(m.BotLink.username.asc()).all()
        out = []
        for r in rows:
            out.append(
                {
                    "username": r.username,
                    "status": r.status,
                    "session": r.session,
                    "title": r.title,
                    "owner_display": r.owner_display,
                    "owner_username": r.owner_username,
                    "last_ts": r.last_ts,
                    "last_error": r.last_error,
                }
            )
        return out

    def get_bot_link_by_username(self, username: str) -> Optional[dict]:
        if not username:
            return None
        bot_link = (
            self.db.query(m.BotLink)
            .filter(m.BotLink.username == username)
            .order_by(m.BotLink.id.desc())
            .limit(1)
            .one_or_none()
        )
        if not bot_link:
            return None
        return {
            "username": bot_link.username,
            "status": bot_link.status,
            "session": bot_link.session,
            "title": bot_link.title,
            "owner_display": bot_link.owner_display,
            "owner_username": bot_link.owner_username,
            "batch_id": bot_link.batch_id,
            "last_ts": bot_link.last_ts,
            "last_error": bot_link.last_error,
            "raw_url": bot_link.raw_url,
        }


# Функціональні обгортки для сумісності
def upsert_bot_link(
    db: Session,
    username: str,
    raw_url: Optional[str],
    status: Optional[str],
    session: Optional[str],
    title: Optional[str],
    owner_display: Optional[str],
    owner_username: Optional[str],
    batch_id: Optional[str],
    last_error: Optional[str],
) -> None:
    return BotLinksDAO(db).upsert_bot_link(username, raw_url, status, session, title, owner_display, owner_username, batch_id, last_error)


def get_bot_link(db: Session, username: str) -> Optional[dict]:
    return BotLinksDAO(db).get_bot_link(username)


def delete_bot_link(db: Session, username: str) -> bool:
    return BotLinksDAO(db).delete_bot_link(username)


def list_bot_links(
    db: Session, owner_display: Optional[str] = None, owner_username: Optional[str] = None
) -> list[dict]:
    return BotLinksDAO(db).list_bot_links(owner_display=owner_display, owner_username=owner_username)


def get_bot_link_by_username(db: Session, username: str) -> Optional[dict]:
    return BotLinksDAO(db).get_bot_link_by_username(username)
