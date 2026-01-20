"""
DAO operations for post_template (templates of posts).
Функції приймають явний db: Session, без SessionLocal усередині.
"""
import time
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy.orm import Session

from app.db import models as m


@dataclass
class PostTemplateRecord:
    id: int
    text: str
    mode: str
    threshold: float
    created_at: int
    title: Optional[str]
    links: Optional[str]


def add_template_db(
    db: Session,
    text: str,
    mode: str = "exact",
    threshold: float = 1.0,
    title: Optional[str] = None,
    links: Optional[str] = None,
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
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return int(tpl.id)


def list_templates_db(db: Session, limit: int = 50) -> List[PostTemplateRecord]:
    rows = (
        db.query(m.PostTemplate)
        .order_by(m.PostTemplate.id.desc())
        .limit(int(limit))
        .all()
    )
    return [
        PostTemplateRecord(
            id=int(r.id),
            text=r.text,
            mode=r.mode,
            threshold=float(r.threshold),
            created_at=int(r.created_at),
            title=r.title,
            links=r.links,
        )
        for r in rows
    ]


def list_templates_full_db(db: Session, limit: int = 50) -> List[PostTemplateRecord]:
    return list_templates_db(db, limit=limit)


def get_template_by_id_db(db: Session, template_id: int) -> Optional[PostTemplateRecord]:
    r = (
        db.query(m.PostTemplate)
        .filter(m.PostTemplate.id == int(template_id))
        .limit(1)
        .one_or_none()
    )
    if not r:
        return None
    return PostTemplateRecord(
        id=int(r.id),
        text=r.text,
        mode=r.mode,
        threshold=float(r.threshold),
        created_at=int(r.created_at),
        title=r.title,
        links=r.links,
    )
