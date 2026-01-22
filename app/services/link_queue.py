import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app.DAL import session_scope
from app.DAL import link_queue_operations as lq
from app.DAL.schemas import LinkQueueRecord

log = logging.getLogger("services.link_queue")


def enqueue(
    urls: List[str],
    batch_id: Optional[str],
    origin_msg: Optional[int],
    delay_sec: int = 0,
    owner_admin_id: Optional[int] = None,
    *,
    adopt_existing: bool = False,
    reset_next_try: bool = True,
) -> int:
    with session_scope() as db:
        return lq.enqueue(
            db,
            urls,
            batch_id,
            origin_msg,
            delay_sec,
            owner_admin_id,
            adopt_existing=adopt_existing,
            reset_next_try=reset_next_try,
        )


def fetch_due(
    limit: int = 20,
    exclude_batch_prefixes: Optional[List[str]] = None,
) -> List[LinkQueueRecord]:
    with session_scope() as db:
        return lq.fetch_due(db, limit=limit, exclude_batch_prefixes=exclude_batch_prefixes)


def fetch_batch_due(
    batch_id: str, limit: int = 50
) -> List[LinkQueueRecord]:
    with session_scope() as db:
        return lq.fetch_batch_due(db, batch_id, limit=limit)


def count_processing() -> int:
    with session_scope() as db:
        return lq.count_processing(db)


def mark_processing(item_id: int):
    with session_scope() as db:
        return lq.mark_processing(db, item_id)


def mark_done(item_id: int):
    with session_scope() as db:
        return lq.mark_done(db, item_id)


def mark_failed(item_id: int, error: str, backoff_sec: int, max_retries: int = 5):
    with session_scope() as db:
        return lq.mark_failed(db, item_id, error, backoff_sec, max_retries)


def delete_by_owner(
    owner_admin_id: Optional[int] = None,
    urls: Optional[list[str]] = None,
) -> int:
    with session_scope() as db_sess:
        return lq.delete_by_owner(
            db_sess,
            owner_admin_id=owner_admin_id,
            urls=urls,
        )
