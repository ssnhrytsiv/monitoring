"""Pydantic schemas for requested/invite check DAL operations."""

from pydantic import BaseModel, ConfigDict, TypeAdapter


class InviteCheckRecord(BaseModel):
    invite_hash: str
    session: str
    noted_at: int
    next_check_at: int
    tries: int

    model_config = ConfigDict(frozen=True, from_attributes=True)


class RequestedCheckRecord(BaseModel):
    session: str
    channel_id: int
    noted_at: int
    next_check_at: int
    tries: int

    model_config = ConfigDict(frozen=True, from_attributes=True)


InviteCheckRecordListAdapter = TypeAdapter(list[InviteCheckRecord])
RequestedCheckRecordListAdapter = TypeAdapter(list[RequestedCheckRecord])
