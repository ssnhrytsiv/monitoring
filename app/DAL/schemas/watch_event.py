"""Pydantic schemas for watch events DAL operations."""

from pydantic import BaseModel, ConfigDict, TypeAdapter


class WatchEventRecord(BaseModel):
    id: int
    watch_id: int
    event_type: str
    payload_json: str
    created_at: str

    model_config = ConfigDict(frozen=True, from_attributes=True)


WatchEventRecordListAdapter = TypeAdapter(list[WatchEventRecord])
