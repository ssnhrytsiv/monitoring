"""
DAO for link_queue table (функціональний стиль).
Усі функції приймають явний db: Session.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import or_, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import models as m


@dataclass
class LinkQueueItem:
    id: int
    url: str
    tries: int
    origin_chat: Optional[int]
    origin_msg: Optional[int]
    owner_admin_id: Optional[int]
    owner_username: Optional[str]


def _now() -> int:
    return int(time.time())


def enqueue(
    db: Session,
    urls: List[str],
    batch_id: Optional[str],
    origin_chat: Optional[int],
    origin_msg: Optional[int],
    delay_sec: int = 0,
    owner_admin_id: Optional[int] = None,
    owner_username: Optional[str] = None,
    *,
    adopt_existing: bool = False,
    reset_next_try: bool = True,
) -> int:
    if not urls:
        return 0
    now = _now()
    added = 0
    owner_username_norm = owner_username.lstrip("@").lower() if owner_username else None

    for u in urls:
        try:
            db.add(
                m.LinkQueue(
                    url=u,
                    state="queued",
                    tries=0,
                    added_ts=now,
                    next_try_ts=now + max(0, int(delay_sec)),
                    last_error=None,
                    batch_id=batch_id,
                    origin_chat=origin_chat,
                    origin_msg=origin_msg,
                    owner_admin_id=owner_admin_id,
                    owner_username=owner_username_norm,
                )
            )
            db.commit()
            added += 1
            continue
        except IntegrityError:
            db.rollback()
            if not adopt_existing:
                continue
            # прибираємо дублікати, залишаючи найстаріший
            rows = (
                db.query(m.LinkQueue)
                .filter(m.LinkQueue.url == u)
                .order_by(m.LinkQueue.id.asc())
                .all()
            )
            keep_id = None
            if rows:
                keep_id = rows[0].id
                dup_ids = [r.id for r in rows[1:]]
                if dup_ids:
                    db.query(m.LinkQueue).filter(m.LinkQueue.id.in_(dup_ids)).delete(
                        synchronize_session=False
                    )
                    db.commit()
            next_try_ts = now + max(0, int(delay_sec)) if reset_next_try else None
            q = db.query(m.LinkQueue).filter(
                m.LinkQueue.id == keep_id if keep_id is not None else m.LinkQueue.url == u
            )
            update_data = {
                "batch_id": batch_id,
                "origin_chat": origin_chat,
                "origin_msg": origin_msg,
                "owner_admin_id": owner_admin_id,
                "owner_username": owner_username_norm,
                "state": "queued",
                "tries": 0,
                "last_error": None,
            }
            if next_try_ts is not None:
                update_data["next_try_ts"] = next_try_ts
            updated = q.update(update_data, synchronize_session=False)
            db.commit()
            if updated:
                added += 1
    return added


def fetch_due(
    db: Session,
    limit: int = 20,
    exclude_batch_prefixes: Optional[List[str]] = None,
) -> List[LinkQueueItem]:
    now = _now()
    prefixes = exclude_batch_prefixes or []
    q = (
        db.query(
            m.LinkQueue.id,
            m.LinkQueue.url,
            m.LinkQueue.tries,
            m.LinkQueue.origin_chat,
            m.LinkQueue.origin_msg,
            m.LinkQueue.owner_admin_id,
            m.LinkQueue.owner_username,
        )
        .filter(
            m.LinkQueue.state == "queued",
            m.LinkQueue.next_try_ts <= now,
        )
        .order_by(m.LinkQueue.added_ts.asc())
    )
    if prefixes:
        conds = [m.LinkQueue.batch_id.is_(None)]
        for pref in prefixes:
            conds.append(m.LinkQueue.batch_id.notlike(pref))
        q = q.filter(or_(*conds))
    rows = q.limit(limit).all()
    return [
        LinkQueueItem(
            id=int(r.id),
            url=r.url,
            tries=int(r.tries),
            origin_chat=r.origin_chat,
            origin_msg=r.origin_msg,
            owner_admin_id=r.owner_admin_id,
            owner_username=r.owner_username,
        )
        for r in rows
    ]


def fetch_batch_due(
    db: Session, batch_id: str, limit: int = 50
) -> List[LinkQueueItem]:
    now = _now()
    rows = (
        db.query(
            m.LinkQueue.id,
            m.LinkQueue.url,
            m.LinkQueue.tries,
            m.LinkQueue.origin_chat,
            m.LinkQueue.origin_msg,
            m.LinkQueue.owner_admin_id,
            m.LinkQueue.owner_username,
        )
        .filter(
            m.LinkQueue.state == "queued",
            m.LinkQueue.batch_id == batch_id,
            m.LinkQueue.next_try_ts <= now,
        )
        .order_by(m.LinkQueue.added_ts.asc(), m.LinkQueue.id.asc())
        .limit(limit)
        .all()
    )
    return [
        LinkQueueItem(
            id=int(r.id),
            url=r.url,
            tries=int(r.tries),
            origin_chat=r.origin_chat,
            origin_msg=r.origin_msg,
            owner_admin_id=r.owner_admin_id,
            owner_username=r.owner_username,
        )
        for r in rows
    ]


def count_processing(db: Session) -> int:
    row = db.query(m.LinkQueue).filter(m.LinkQueue.state == "processing").count()
    return int(row or 0)


def mark_processing(db: Session, item_id: int) -> None:
    db.query(m.LinkQueue).filter(m.LinkQueue.id == item_id).update({"state": "processing"})
    db.commit()


def mark_done(db: Session, item_id: int) -> None:
    db.query(m.LinkQueue).filter(m.LinkQueue.id == item_id).update({"state": "done", "last_error": None})
    db.commit()


def mark_failed(db: Session, item_id: int, error: str, backoff_sec: int, max_retries: int = 5) -> None:
    now = _now()
    link_row = db.query(m.LinkQueue).filter(m.LinkQueue.id == item_id).one_or_none()
    if not link_row:
        return
    tries = (link_row.tries or 0) + 1
    if tries >= max_retries:
        link_row.state = "failed"
        link_row.last_error = (error or "")[:500]
        link_row.tries = tries
    else:
        link_row.state = "queued"
        link_row.tries = tries
        link_row.last_error = (error or "")[:500]
        link_row.next_try_ts = now + max(5, int(backoff_sec))
    db.commit()


def delete_by_owner(
    db: Session,
    owner_admin_id: Optional[int] = None,
    owner_username: Optional[str] = None,
    urls: Optional[list[str]] = None,
) -> int:
    conditions = []
    if owner_admin_id is not None:
        conditions.append(m.LinkQueue.owner_admin_id == owner_admin_id)
    elif owner_username:
        conditions.append(m.LinkQueue.owner_username == owner_username.lstrip("@").lower())
    if urls:
        conditions.append(m.LinkQueue.url.in_(urls))
    if not conditions:
        return 0
    deleted = (
        db.query(m.LinkQueue)
        .filter(or_(*conditions))
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted or 0
