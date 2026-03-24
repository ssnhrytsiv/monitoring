"""
DAO operations for post_template (templates of posts).

Містить класичний DAO і зручні обгортки з опціональною Session.
"""
import time
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.admin_bot.db import models as m
from app.DAL import SessionLocal


class PostTemplatesDAO:
    def __init__(self, db: Session):
        self.db = db

    def add_template(
        self,
        text: str,
        mode: str = "exact",
        threshold: float = 1.0,
        title: Optional[str] = None,
        links: Optional[str] = None,
        photo_id: Optional[str] = None,
        is_reply: bool = False,
    ) -> int:
        if not text:
            raise ValueError("text is empty")
        if mode not in ("exact", "fuzzy"):
            mode = "exact"
        if mode == "exact":
            threshold = 1.0
        else:
            try:
                threshold = float(threshold)
            except Exception:
                threshold = 0.7
            threshold = max(0.0, min(1.0, threshold))

        tpl = m.PostTemplate(
            text=text,
            mode=mode,
            threshold=float(threshold),
            created_at=int(time.time()),
            title=title,
            links=links,
            photo_id=photo_id,
            is_reply=bool(is_reply),
        )
        self.db.add(tpl)
        self.db.commit()
        self.db.refresh(tpl)
        return int(tpl.id)

    def list_templates(self, limit: int = 50) -> List[Tuple[int, str, str, float, int]]:
        rows = (
            self.db.query(m.PostTemplate)
            .order_by(m.PostTemplate.id.desc())
            .limit(int(limit))
            .all()
        )
        return [
            (int(r.id), r.text, r.mode, float(r.threshold), int(r.created_at))
            for r in rows
        ]

    def list_templates_full(
        self, limit: int = 50
    ) -> List[Tuple[int, str, str, float, int, Optional[str], Optional[str], Optional[str]]]:
        rows = (
            self.db.query(m.PostTemplate)
            .order_by(m.PostTemplate.id.desc())
            .limit(int(limit))
            .all()
        )
        return [
            (
                int(r.id),
                r.text,
                r.mode,
                float(r.threshold),
                int(r.created_at),
                r.title,
                r.links,
                r.photo_id,
            )
            for r in rows
        ]

    def get_template_by_id(
        self, template_id: int
    ) -> Optional[Tuple[int, str, str, float, int, Optional[str], Optional[str], Optional[str]]]:
        r = (
            self.db.query(m.PostTemplate)
            .filter(m.PostTemplate.id == int(template_id))
            .limit(1)
            .one_or_none()
        )
        if not r:
            return None
        return (
            int(r.id),
            r.text,
            r.mode,
            float(r.threshold),
            int(r.created_at),
            r.title,
            r.links,
            r.photo_id,
        )

    def find_template_exact(
        self,
        text: str,
        links: Optional[str] = None,
    ) -> Optional[Tuple[int, str, str, float, int, Optional[str], Optional[str], Optional[str]]]:
        if not text:
            return None
        query = self.db.query(m.PostTemplate).filter(m.PostTemplate.text == str(text))
        if links is None:
            query = query.filter(m.PostTemplate.links.is_(None))
        else:
            query = query.filter(m.PostTemplate.links == str(links))
        r = query.order_by(m.PostTemplate.id.desc()).limit(1).one_or_none()
        if not r:
            return None
        return (
            int(r.id),
            r.text,
            r.mode,
            float(r.threshold),
            int(r.created_at),
            r.title,
            r.links,
            r.photo_id,
        )

    def is_template_reply(self, template_id: int) -> bool:
        r = (
            self.db.query(m.PostTemplate.is_reply)
            .filter(m.PostTemplate.id == int(template_id))
            .limit(1)
            .one_or_none()
        )
        if not r:
            return False
        return bool(r[0])

    def set_template_reply(self, template_id: int, enabled: bool):
        template = (
            self.db.query(m.PostTemplate)
            .filter(m.PostTemplate.id == int(template_id))
            .limit(1)
            .one_or_none()
        )
        if not template:
            return None
        template.is_reply = bool(enabled)
        self.db.commit()
        self.db.refresh(template)
        return template


# Функціональні обгортки для сумісності (db опційна)

def add_template(
    text: str,
    mode: str = "exact",
    threshold: float = 1.0,
    title: Optional[str] = None,
    links: Optional[str] = None,
    photo_id: Optional[str] = None,
    is_reply: bool = False,
    db: Optional[Session] = None,
) -> int:
    if db is None:
        with SessionLocal() as session:
            return PostTemplatesDAO(session).add_template(text, mode, threshold, title, links, photo_id, is_reply)
    return PostTemplatesDAO(db).add_template(text, mode, threshold, title, links, photo_id, is_reply)


def list_templates(limit: int = 50, db: Optional[Session] = None):
    if db is None:
        with SessionLocal() as session:
            return PostTemplatesDAO(session).list_templates(limit=limit)
    return PostTemplatesDAO(db).list_templates(limit=limit)


def list_templates_full(limit: int = 50, db: Optional[Session] = None):
    if db is None:
        with SessionLocal() as session:
            return PostTemplatesDAO(session).list_templates_full(limit=limit)
    return PostTemplatesDAO(db).list_templates_full(limit=limit)


def get_template_by_id(template_id: int, db: Optional[Session] = None):
    if db is None:
        with SessionLocal() as session:
            return PostTemplatesDAO(session).get_template_by_id(template_id)
    return PostTemplatesDAO(db).get_template_by_id(template_id)


def find_template_exact(text: str, links: Optional[str] = None, db: Optional[Session] = None):
    if db is None:
        with SessionLocal() as session:
            return PostTemplatesDAO(session).find_template_exact(text=text, links=links)
    return PostTemplatesDAO(db).find_template_exact(text=text, links=links)


def is_template_reply(template_id: int, db: Optional[Session] = None) -> bool:
    if db is None:
        with SessionLocal() as session:
            return PostTemplatesDAO(session).is_template_reply(template_id)
    return PostTemplatesDAO(db).is_template_reply(template_id)


def set_template_reply(template_id: int, enabled: bool, db: Optional[Session] = None):
    if db is None:
        with SessionLocal() as session:
            return PostTemplatesDAO(session).set_template_reply(template_id, enabled)
    return PostTemplatesDAO(db).set_template_reply(template_id, enabled)
