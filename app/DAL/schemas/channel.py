from __future__ import annotations

from pydantic import BaseModel, TypeAdapter
from typing import Optional


class ChannelOwner(BaseModel):
    channel_id: Optional[int] = None
    owner_admin_id: Optional[int] = None
    owner_display: Optional[str] = None
    owner_label: Optional[str] = None
    title: Optional[str] = None


ChannelOwnerListAdapter = TypeAdapter(list[ChannelOwner])


class ChannelRecord(BaseModel):
    channel_id: int
    username: Optional[str] = None
    title: Optional[str] = None
    owner_admin_id: Optional[int] = None
    last_status: Optional[str] = None
    order_index: Optional[int] = None
    updated_at: Optional[str] = None


ChannelRecordListAdapter = TypeAdapter(list[ChannelRecord])
