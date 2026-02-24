import time
import logging
from contextlib import contextmanager
from typing import List, Optional, Tuple

from app.DAL import SessionLocal
from app.DAL.link_queue_operations import LinkQueueDAO

log = logging.getLogger("services.link_queue")


@contextmanager
def _dao():
    db = SessionLocal()
    try:
        yield LinkQueueDAO(db)
    finally:
        db.close()


def enqueue(
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
    with _dao() as dao:
        return dao.enqueue(
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
    limit: int = 20,
    exclude_batch_prefixes: Optional[List[str]] = None,
) -> List[Tuple[int, str, int, Optional[int], Optional[int], Optional[str], Optional[str]]]:
    with _dao() as dao:
        return dao.fetch_due(limit=limit, exclude_batch_prefixes=exclude_batch_prefixes)


def fetch_batch_due(batch_id: str, limit: int = 50) -> List[Tuple[int, str, int, Optional[int], Optional[int], Optional[str], Optional[str]]]:
    with _dao() as dao:
        return dao.fetch_batch_due(batch_id, limit=limit)


def count_processing() -> int:
    with _dao() as dao:
        return dao.count_processing()


def count_processing_recent(max_processing_age_seconds: int) -> int:
    with _dao() as dao:
        return dao.count_processing_recent(max_processing_age_seconds)


def mark_processing(item_id: int):
    with _dao() as dao:
        return dao.mark_processing(item_id)


def mark_done(item_id: int):
    with _dao() as dao:
        return dao.mark_done(item_id)


def mark_failed(item_id: int, error: str, backoff_sec: int, max_retries: int = 5):
    with _dao() as dao:
        return dao.mark_failed(item_id, error, backoff_sec, max_retries)


def delete_by_owner(
    owner_display: Optional[str] = None,
    owner_username: Optional[str] = None,
    urls: Optional[list[str]] = None,
) -> int:
    with _dao() as dao:
        return dao.delete_by_owner(owner_display=owner_display, owner_username=owner_username, urls=urls)
