from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import session_scope
from app.DAL.schemas import LinkCacheRecord, LinkCacheRecordListAdapter, LinkCachePatch
from app.utils.link_parser import sanitize_link

try:
    from app.utils.time_utils import moscow_timestamp
except Exception:
    moscow_timestamp = None  # type: ignore


def _now_ts() -> int:
    if moscow_timestamp:
        try:
            return int(moscow_timestamp())
        except Exception:
            pass
    import time

    return int(time.time())


def _normalize_url(url: str) -> Optional[str]:
    if not url:
        return None
    try:
        cleaned = sanitize_link(url) or url
    except Exception:
        cleaned = url
    cleaned = str(cleaned).strip()
    return cleaned or None


def get_link_cache_record(url_norm: str) -> Optional[LinkCacheRecord]:
    url_val = _normalize_url(url_norm)
    if not url_val:
        return None
    with session_scope() as db:
        row = db.query(m.LinkCache).filter(m.LinkCache.url_norm == url_val).one_or_none()
        if not row:
            return None
        return LinkCacheRecord.model_validate(row)


def list_link_cache_records(url_norm_list: List[str]) -> List[LinkCacheRecord]:
    urls = [_normalize_url(u) for u in url_norm_list if u]
    urls = [u for u in urls if u]
    if not urls:
        return []
    with session_scope() as db:
        rows = (
            db.query(m.LinkCache)
            .filter(m.LinkCache.url_norm.in_(urls))
            .all()
        )
        return LinkCacheRecordListAdapter.validate_python(rows)


def update_link_cache_status(
    patch: LinkCachePatch,
) -> None:
    if not patch.url_norm or not patch.kind or not patch.status or not patch.account:
        return
    data = patch.model_dump()
    data["join_time"] = int(patch.join_time) if patch.join_time is not None else _now_ts()
    with session_scope() as db:
        existing = db.query(m.LinkCache).filter(m.LinkCache.url_norm == patch.url_norm).one_or_none()
        if existing:
            for field, value in data.items():
                setattr(existing, field, value)
        else:
            db.add(m.LinkCache(**data))


def upsert_link_cache_record(record: LinkCacheRecord) -> None:
    patch = LinkCachePatch(
        url_norm=record.url_norm,
        kind=record.kind,
        status=record.status,
        account=record.account or "",
        join_time=record.join_time,
        channel_id=record.channel_id,
        title=record.title,
        last_error=record.last_error,
    )
    update_link_cache_status(patch)


def mark_link_cache_duplicate(
    url_norm: str,
    *,
    account: str,
    join_time: Optional[int] = None,
    channel_id: Optional[int] = None,
) -> None:
    patch = LinkCachePatch(
        url_norm=url_norm,
        kind="public",
        status="duplicate",
        account=account,
        join_time=join_time,
        channel_id=channel_id,
        title=None,
        last_error=None,
    )
    update_link_cache_status(patch)


def delete_link_cache_older_than(older_than_join_time: int) -> int:
    with session_scope() as db:
        deleted = (
            db.query(m.LinkCache)
            .filter(m.LinkCache.join_time < int(older_than_join_time))
            .delete(synchronize_session=False)
        )
        return deleted or 0
