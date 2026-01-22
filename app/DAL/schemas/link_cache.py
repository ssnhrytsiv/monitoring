from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, TypeAdapter


class LinkCachePatch(BaseModel):
    # PATCH: only url_norm required; everything else optional
    model_config = ConfigDict(frozen=True, extra="forbid")

    url_norm: str

    kind: Optional[Literal["public", "invite", "bot"]] = None
    status: Optional[str] = None
    account: Optional[str] = None
    join_time: Optional[int] = None
    channel_id: Optional[int] = None
    title: Optional[str] = None
    last_error: Optional[str] = None


class LinkCacheRecord(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    url_norm: str
    kind: Literal["public", "invite", "bot"]
    status: str
    account: Optional[str] = None
    channel_id: Optional[int] = None
    title: Optional[str] = None
    last_error: Optional[str] = None
    join_time: int


LinkCacheRecordListAdapter = TypeAdapter(list[LinkCacheRecord])