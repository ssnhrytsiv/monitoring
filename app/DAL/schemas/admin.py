from typing import Optional

from pydantic import BaseModel, ConfigDict, TypeAdapter


class AdminRecord(BaseModel):
    id: Optional[int] = None
    tg_id: Optional[int] = None
    username: Optional[str] = None
    display: Optional[str] = None
    is_new: Optional[int] = None
    cpm: Optional[float] = None
    price: Optional[float] = None
    subscribers: Optional[int] = None

    model_config = ConfigDict(frozen=True, from_attributes=True)


AdminRecordListAdapter = TypeAdapter(list[AdminRecord])
