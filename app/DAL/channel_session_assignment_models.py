from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


def _normalize_required_integer_value(incoming_value: Any) -> int:
    if incoming_value is None:
        raise ValueError("Value is required")
    if isinstance(incoming_value, bool):
        raise ValueError("Boolean is not a valid integer value")
    if isinstance(incoming_value, int):
        return incoming_value
    normalized_text_value = str(incoming_value).strip()
    if not normalized_text_value:
        raise ValueError("Value is required")
    return int(normalized_text_value)


def _normalize_optional_integer_value(incoming_value: Any) -> int | None:
    if incoming_value is None:
        return None
    return _normalize_required_integer_value(incoming_value)


def _normalize_session_name_value(incoming_value: Any) -> str:
    normalized_session_name = str(incoming_value or "").strip()
    if not normalized_session_name:
        raise ValueError("session_name is required")
    if normalized_session_name.endswith(".session"):
        normalized_session_name = normalized_session_name[:-8]
    normalized_session_name = normalized_session_name.strip()
    if not normalized_session_name:
        raise ValueError("session_name is required")
    return normalized_session_name


def _normalize_optional_text_value(incoming_value: Any) -> str | None:
    if incoming_value is None:
        return None
    normalized_text_value = str(incoming_value).strip()
    if not normalized_text_value:
        return None
    return normalized_text_value


class ChannelSessionAssignmentBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_id: int
    session_name: str
    admin_id: int | None = None
    assignment_source: str | None = None

    @field_validator("channel_id", mode="before")
    @classmethod
    def validate_channel_id(cls, incoming_value: Any) -> int:
        return _normalize_required_integer_value(incoming_value)

    @field_validator("session_name", mode="before")
    @classmethod
    def validate_session_name(cls, incoming_value: Any) -> str:
        return _normalize_session_name_value(incoming_value)

    @field_validator("admin_id", mode="before")
    @classmethod
    def validate_admin_id(cls, incoming_value: Any) -> int | None:
        return _normalize_optional_integer_value(incoming_value)

    @field_validator("assignment_source", mode="before")
    @classmethod
    def validate_assignment_source(cls, incoming_value: Any) -> str | None:
        return _normalize_optional_text_value(incoming_value)


class ChannelSessionAssignmentUpsertModel(ChannelSessionAssignmentBaseModel):
    pass


class ChannelSessionAssignmentViewModel(ChannelSessionAssignmentBaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    assigned_at: int
    updated_at: int
    last_ok_at: int | None = None
    last_repair_at: int | None = None

    @field_validator("assigned_at", "updated_at", mode="before")
    @classmethod
    def validate_required_timestamp_fields(cls, incoming_value: Any) -> int:
        return _normalize_required_integer_value(incoming_value)

    @field_validator("last_ok_at", "last_repair_at", mode="before")
    @classmethod
    def validate_optional_timestamp_fields(cls, incoming_value: Any) -> int | None:
        return _normalize_optional_integer_value(incoming_value)
