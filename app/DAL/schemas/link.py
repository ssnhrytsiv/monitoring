from typing import Optional

from pydantic import BaseModel, ConfigDict, TypeAdapter


class LinkRecord(BaseModel):
    id: Optional[int] = None
    channel_id: Optional[int] = None
    url_norm: Optional[str] = None
    kind: Optional[str] = None
    batch_msg_id: Optional[int] = None
    added_at: Optional[str] = None
    title: Optional[str] = None

    model_config = ConfigDict(frozen=True, from_attributes=True)


LinkRecordListAdapter = TypeAdapter(list[LinkRecord])
