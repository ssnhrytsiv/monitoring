from pydantic import BaseModel, ConfigDict, TypeAdapter
from typing import Optional


class InviteCacheRecord(BaseModel):
    invite_hash: str
    channel_id: Optional[int]
    title: Optional[str]
    status: Optional[str]
    session: Optional[str]
    last_error: Optional[str]

    model_config = ConfigDict(frozen=True, from_attributes=True)


InviteCacheRecordListAdapter = TypeAdapter(list[InviteCacheRecord])
