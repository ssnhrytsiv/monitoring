from typing import Optional

from pydantic import BaseModel, ConfigDict


class WatchPostDetailsRecord(BaseModel):
    id: int
    template_id: Optional[int] = None
    status: Optional[str] = None
    time_window_end: Optional[str] = None
    created_by: Optional[int] = None
    channel_id: Optional[int] = None
    source_url: Optional[str] = None
    project: Optional[str] = None
    matched_session: Optional[str] = None
    created_via: Optional[str] = None
    matched_at: Optional[str] = None
    deleted_at: Optional[str] = None
    updated_at: Optional[str] = None
    group_id: Optional[int] = None
    final_views: Optional[int] = None
    expected_links_json: Optional[str] = None
    expected_text_hash: Optional[str] = None
    time_window_start: Optional[str] = None
    admin_id: Optional[int] = None

    model_config = ConfigDict(frozen=True, from_attributes=True)
