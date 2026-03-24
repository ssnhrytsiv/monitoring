from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_optional_text_value(incoming_value: Any) -> str | None:
    if incoming_value is None:
        return None
    normalized_text_value = str(incoming_value).strip()
    if not normalized_text_value:
        return None
    if normalized_text_value.endswith(".session"):
        normalized_text_value = normalized_text_value[:-8].strip()
    return normalized_text_value or None


def _normalize_optional_integer_value(incoming_value: Any) -> int | None:
    if incoming_value is None:
        return None
    if isinstance(incoming_value, bool):
        raise ValueError("Boolean is not a valid integer value")
    if isinstance(incoming_value, int):
        return incoming_value
    normalized_text_value = str(incoming_value).strip()
    if not normalized_text_value:
        return None
    return int(normalized_text_value)


def _normalize_session_name_list(incoming_value: Any) -> list[str]:
    if incoming_value is None:
        return []
    if isinstance(incoming_value, str):
        values_for_iteration = [incoming_value]
    elif isinstance(incoming_value, (list, tuple, set)):
        values_for_iteration = list(incoming_value)
    else:
        values_for_iteration = [incoming_value]

    normalized_session_name_list: list[str] = []
    seen_session_name_set: set[str] = set()
    for value_for_iteration in values_for_iteration:
        normalized_session_name = _normalize_optional_text_value(value_for_iteration)
        if not normalized_session_name:
            continue
        if normalized_session_name in seen_session_name_set:
            continue
        seen_session_name_set.add(normalized_session_name)
        normalized_session_name_list.append(normalized_session_name)
    normalized_session_name_list.sort()
    return normalized_session_name_list


class ChannelSubscriptionAuditStatusEnum(str, Enum):
    SUBSCRIBED = "subscribed"
    MISSING = "missing"
    UNKNOWN = "unknown"


class ChannelSubscriptionAuditReasonEnum(str, Enum):
    EXPECTED_SESSION_PRESENT = "expected_session_present"
    EXPECTED_SESSION_PRESENT_WITH_DUPLICATES = "expected_session_present_with_duplicates"
    EXPECTED_SESSION_MISSING_PRESENT_ELSEWHERE = "expected_session_missing_present_elsewhere"
    EXPECTED_SESSION_MISSING_EVERYWHERE = "expected_session_missing_everywhere"
    EXPECTED_SESSION_SCAN_FAILED = "expected_session_scan_failed"
    UNASSIGNED_PRESENT_IN_POOL = "unassigned_present_in_pool"
    UNASSIGNED_MISSING_IN_POOL = "unassigned_missing_in_pool"
    UNASSIGNED_SCAN_INCOMPLETE = "unassigned_scan_incomplete"


class ChannelSubscriptionAuditDetailsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_reason: str = "periodic"
    status_reason: ChannelSubscriptionAuditReasonEnum
    expected_session: str | None = None
    present_sessions: list[str] = Field(default_factory=list)
    failed_sessions: list[str] = Field(default_factory=list)
    admin_id: int | None = None
    assignment_source: str | None = None
    assignment_updated_at: int | None = None

    @field_validator("audit_reason", mode="before")
    @classmethod
    def validate_audit_reason(cls, incoming_value: Any) -> str:
        normalized_text_value = str(incoming_value or "").strip()
        return normalized_text_value or "periodic"

    @field_validator("expected_session", "assignment_source", mode="before")
    @classmethod
    def validate_optional_text_fields(cls, incoming_value: Any) -> str | None:
        return _normalize_optional_text_value(incoming_value)

    @field_validator("present_sessions", "failed_sessions", mode="before")
    @classmethod
    def validate_session_name_lists(cls, incoming_value: Any) -> list[str]:
        return _normalize_session_name_list(incoming_value)

    @field_validator("admin_id", "assignment_updated_at", mode="before")
    @classmethod
    def validate_optional_integer_fields(cls, incoming_value: Any) -> int | None:
        return _normalize_optional_integer_value(incoming_value)


def parse_channel_subscription_audit_details(
    raw_status_details_text: str | None,
) -> ChannelSubscriptionAuditDetailsModel | None:
    if not raw_status_details_text:
        return None
    try:
        return ChannelSubscriptionAuditDetailsModel.model_validate_json(
            raw_status_details_text
        )
    except Exception:
        return None
