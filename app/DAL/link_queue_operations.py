"""
DAO for link_queue table.
"""
import time
from typing import List, Optional, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.admin_bot.db import models as m


class LinkQueueDAO:
    def __init__(self, db: Session):
        self.db = db

    def enqueue(
        self,
        urls: List[str],
        batch_id: Optional[str],
        origin_chat: Optional[int],
        origin_msg: Optional[int],
        delay_sec: int = 0,
        owner_display: Optional[str] = None,
        owner_username: Optional[str] = None,
        *,
        adopt_existing: bool = False,
        reset_next_try: bool = True,
    ) -> int:
        if not urls:
            return 0
        now = int(time.time())
        added = 0
        owner_username_norm = owner_username.lstrip("@").lower() if owner_username else None

        for u in urls:
            # Працюємо окремою транзакцією на кожен URL, щоб наступний не скасовував попередні.
            try:
                obj = m.LinkQueue(
                    url=u,
                    state="queued",
                    tries=0,
                    added_ts=now,
                    next_try_ts=now + max(0, int(delay_sec)),
                    last_error=None,
                    batch_id=batch_id,
                    origin_chat=origin_chat,
                    origin_msg=origin_msg,
                    owner_display=owner_display,
                    owner_username=owner_username_norm,
                )
                self.db.add(obj)
                self.db.commit()
                added += 1
                continue
            except IntegrityError:
                self.db.rollback()
                if not adopt_existing:
                    continue
                # Якщо вже є дублі (історичні) — залишаємо найстаріший, решту чистимо,
                # щоб уникнути UNIQUE conflict при оновленні.
                rows = (
                    self.db.query(m.LinkQueue)
                    .filter(m.LinkQueue.url == u)
                    .order_by(m.LinkQueue.id.asc())
                    .all()
                )
                keep_id = None
                if rows:
                    keep_id = rows[0].id
                    dup_ids = [r.id for r in rows[1:]]
                    if dup_ids:
                        self.db.query(m.LinkQueue).filter(m.LinkQueue.id.in_(dup_ids)).delete(
                            synchronize_session=False
                        )
                        self.db.commit()
                next_try_ts = now + max(0, int(delay_sec)) if reset_next_try else None
                q = self.db.query(m.LinkQueue).filter(
                    m.LinkQueue.id == keep_id if keep_id is not None else m.LinkQueue.url == u
                )
                update_data = {
                    "batch_id": batch_id,
                    "origin_chat": origin_chat,
                    "origin_msg": origin_msg,
                    "owner_display": owner_display,
                    "owner_username": owner_username_norm,
                    "state": "queued",
                    "tries": 0,
                    "last_error": None,
                }
                if next_try_ts is not None:
                    update_data["next_try_ts"] = next_try_ts
                updated = q.update(update_data, synchronize_session=False)
                self.db.commit()
                if updated:
                    added += 1
        return added
        return added

    def fetch_due(
        self,
        limit: int = 20,
        exclude_batch_prefixes: Optional[List[str]] = None,
    ) -> List[Tuple[int, str, int, Optional[int], Optional[int], Optional[str], Optional[str]]]:
        now = int(time.time())
        prefixes = exclude_batch_prefixes or []
        q = (
            self.db.query(
                m.LinkQueue.id,
                m.LinkQueue.url,
                m.LinkQueue.tries,
                m.LinkQueue.origin_chat,
                m.LinkQueue.origin_msg,
                m.LinkQueue.owner_display,
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
        return [(int(r[0]), r[1], int(r[2]), r[3], r[4], r[5], r[6]) for r in rows]

    def fetch_batch_due(
        self, batch_id: str, limit: int = 50
    ) -> List[Tuple[int, str, int, Optional[int], Optional[int], Optional[str], Optional[str]]]:
        now = int(time.time())
        rows = (
            self.db.query(
                m.LinkQueue.id,
                m.LinkQueue.url,
                m.LinkQueue.tries,
                m.LinkQueue.origin_chat,
                m.LinkQueue.origin_msg,
                m.LinkQueue.owner_display,
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
        return [(int(r[0]), r[1], int(r[2]), r[3], r[4], r[5], r[6]) for r in rows]

    def count_processing(self) -> int:
        row = self.db.query(m.LinkQueue).filter(m.LinkQueue.state == "processing").count()
        return int(row or 0)

    def mark_processing(self, item_id: int) -> None:
        self.db.query(m.LinkQueue).filter(m.LinkQueue.id == item_id).update({"state": "processing"})
        self.db.commit()

    def mark_done(self, item_id: int) -> None:
        self.db.query(m.LinkQueue).filter(m.LinkQueue.id == item_id).update(
            {"state": "done", "last_error": None}
        )
        self.db.commit()

    def mark_failed(self, item_id: int, error: str, backoff_sec: int, max_retries: int = 5) -> None:
        now = int(time.time())
        link_row = self.db.query(m.LinkQueue).filter(m.LinkQueue.id == item_id).one_or_none()
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
        self.db.commit()

    def delete_by_owner(
        self,
        owner_display: Optional[str] = None,
        owner_username: Optional[str] = None,
        urls: Optional[list[str]] = None,
    ) -> int:
        conditions = []
        if owner_display:
            conditions.append(m.LinkQueue.owner_display == owner_display)
        if owner_username:
            conditions.append(m.LinkQueue.owner_username == owner_username)
        if urls:
            conditions.append(m.LinkQueue.url.in_(urls))
        if not conditions:
            return 0
        deleted = (
            self.db.query(m.LinkQueue)
            .filter(or_(*conditions))
            .delete(synchronize_session=False)
        )
        self.db.commit()
        return deleted or 0


# Функціональні обгортки для сумісності (потребують зовнішньої сесії)
def enqueue(
    db: Session,
    urls: List[str],
    batch_id: Optional[str],
    origin_chat: Optional[int],
    origin_msg: Optional[int],
    delay_sec: int = 0,
    owner_display: Optional[str] = None,
    owner_username: Optional[str] = None,
    *,
    adopt_existing: bool = False,
    reset_next_try: bool = True,
) -> int:
    return LinkQueueDAO(db).enqueue(
        urls,
        batch_id,
        origin_chat,
        origin_msg,
        delay_sec,
        owner_display,
        owner_username,
        adopt_existing=adopt_existing,
        reset_next_try=reset_next_try,
    )


def fetch_due(
    db: Session,
    limit: int = 20,
    exclude_batch_prefixes: Optional[List[str]] = None,
) -> List[Tuple[int, str, int, Optional[int], Optional[int], Optional[str], Optional[str]]]:
    return LinkQueueDAO(db).fetch_due(limit=limit, exclude_batch_prefixes=exclude_batch_prefixes)


def fetch_batch_due(
    db: Session, batch_id: str, limit: int = 50
) -> List[Tuple[int, str, int, Optional[int], Optional[int], Optional[str], Optional[str]]]:
    return LinkQueueDAO(db).fetch_batch_due(batch_id, limit=limit)


def count_processing(db: Session) -> int:
    return LinkQueueDAO(db).count_processing()


def mark_processing(db: Session, item_id: int):
    return LinkQueueDAO(db).mark_processing(item_id)


def mark_done(db: Session, item_id: int):
    return LinkQueueDAO(db).mark_done(item_id)


def mark_failed(db: Session, item_id: int, error: str, backoff_sec: int, max_retries: int = 5):
    return LinkQueueDAO(db).mark_failed(item_id, error, backoff_sec, max_retries)


def delete_by_owner(
    db: Session,
    owner_display: Optional[str] = None,
    owner_username: Optional[str] = None,
    urls: Optional[list[str]] = None,
) -> int:
    return LinkQueueDAO(db).delete_by_owner(owner_display=owner_display, owner_username=owner_username, urls=urls)
