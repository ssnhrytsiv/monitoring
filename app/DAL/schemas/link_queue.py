from typing import Optional

from pydantic import BaseModel, ConfigDict, TypeAdapter


class LinkQueueRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    url: str
    state: str
    tries: int
    added_ts: int
    next_try_ts: int
    last_error: Optional[str] = None
    batch_id: Optional[str] = None
    origin_msg: Optional[int] = None
    owner_admin_id: Optional[int] = None


LinkQueueRecordListAdapter = TypeAdapter(list[LinkQueueRecord])
