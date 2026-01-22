"""Pydantic schemas used by DAL functions."""

from app.DAL.schemas.requested import (
    InviteCheckRecord,
    InviteCheckRecordListAdapter,
    RequestedCheckRecord,
    RequestedCheckRecordListAdapter,
)
from app.DAL.schemas.invite_cache import (
    InviteCacheRecord,
    InviteCacheRecordListAdapter,
)
from app.DAL.schemas.link import LinkRecord, LinkRecordListAdapter
from app.DAL.schemas.admin import AdminRecord, AdminRecordListAdapter
from app.DAL.schemas.watch_post import WatchPostDetailsRecord
from app.DAL.schemas.link_queue import LinkQueueRecord, LinkQueueRecordListAdapter
from app.DAL.schemas.link_cache import (
    LinkCacheRecord,
    LinkCacheRecordListAdapter,
    LinkCachePatch,
)

__all__ = [
    "InviteCheckRecord",
    "RequestedCheckRecord",
    "InviteCheckRecordListAdapter",
    "RequestedCheckRecordListAdapter",
    "InviteCacheRecord",
    "InviteCacheRecordListAdapter",
    "LinkRecord",
    "LinkRecordListAdapter",
    "AdminRecord",
    "AdminRecordListAdapter",
    "WatchPostDetailsRecord",
    "LinkQueueRecord",
    "LinkQueueRecordListAdapter",
    "LinkCacheRecord",
    "LinkCacheRecordListAdapter",
    "LinkCachePatch",
]
