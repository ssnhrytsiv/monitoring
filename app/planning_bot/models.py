from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

PLACEHOLDER_DASH = "—"


class PlanningButton(BaseModel):
    text: str
    callback: str


class PlanningRequestSourceEnum(str, Enum):
    INLINE_CHOSEN = "inline_chosen"
    DIRECT_MESSAGE = "direct_message"
    REPLY_MESSAGE = "reply_message"
    FORWARD_MESSAGE = "forward_message"


class PlanningRequestKindEnum(str, Enum):
    ORDER = "order"
    LINKS_FIX = "links_fix"
    DIRECT_REQUEST = "direct_request"
    LINKS_REPLY = "links_reply"
    FORWARD_LINKS = "forward_links"


def _normalize_optional_text_value(incoming_value: Any) -> str | None:
    if incoming_value is None:
        return None
    normalized_text_value = str(incoming_value).strip()
    if not normalized_text_value:
        return None
    if normalized_text_value == PLACEHOLDER_DASH:
        return None
    return normalized_text_value


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
    if normalized_text_value == PLACEHOLDER_DASH:
        return None
    return int(normalized_text_value)


def _normalize_links_value(
    incoming_value: Any,
    allow_none_value: bool,
) -> list[str] | None:
    if incoming_value is None:
        return None if allow_none_value else []

    values_for_iteration: list[Any]
    if isinstance(incoming_value, str):
        normalized_text_value = incoming_value.strip()
        if not normalized_text_value or normalized_text_value == PLACEHOLDER_DASH:
            return None if allow_none_value else []
        if normalized_text_value.startswith("["):
            try:
                parsed_json_value = json.loads(normalized_text_value)
                if isinstance(parsed_json_value, list):
                    values_for_iteration = parsed_json_value
                else:
                    values_for_iteration = [normalized_text_value]
            except Exception:
                values_for_iteration = [normalized_text_value]
        else:
            values_for_iteration = [normalized_text_value]
    elif isinstance(incoming_value, (list, tuple, set)):
        values_for_iteration = list(incoming_value)
    else:
        values_for_iteration = [incoming_value]

    normalized_links_values: list[str] = []
    seen_links_values: set[str] = set()
    for value_for_iteration in values_for_iteration:
        normalized_link_value = str(value_for_iteration or "").strip()
        if not normalized_link_value:
            continue
        if normalized_link_value == PLACEHOLDER_DASH:
            continue
        if normalized_link_value in seen_links_values:
            continue
        seen_links_values.add(normalized_link_value)
        normalized_links_values.append(normalized_link_value)
    return normalized_links_values


class PlanningRequestBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_source: PlanningRequestSourceEnum | None = None
    request_kind: PlanningRequestKindEnum | None = None
    source_query_text: str | None = None
    source_message_text: str | None = None
    source_message_id: int | None = None
    telegram_user_id: int | None = None
    telegram_username: str | None = None
    telegram_first_name: str | None = None
    telegram_last_name: str | None = None
    client_name: str | None = None
    administrator_name: str | None = None
    client_reference_number: str | None = None
    price_amount: int | None = None
    posts_count: int | None = None
    thousand_message_price: int | None = None
    comment_text: str | None = None
    links: list[str] | None = None

    @field_validator(
        "source_query_text",
        "source_message_text",
        "telegram_username",
        "telegram_first_name",
        "telegram_last_name",
        "client_name",
        "administrator_name",
        "client_reference_number",
        "comment_text",
        mode="before",
    )
    @classmethod
    def validate_optional_text_fields(cls, incoming_value: Any) -> str | None:
        return _normalize_optional_text_value(incoming_value)

    @field_validator(
        "source_message_id",
        "telegram_user_id",
        "price_amount",
        "posts_count",
        "thousand_message_price",
        mode="before",
    )
    @classmethod
    def validate_optional_integer_fields(cls, incoming_value: Any) -> int | None:
        return _normalize_optional_integer_value(incoming_value)


class PlanningRequestCreateModel(PlanningRequestBaseModel):
    request_source: PlanningRequestSourceEnum
    request_kind: PlanningRequestKindEnum
    links: list[str] = Field(default_factory=list)

    @field_validator("links", mode="before")
    @classmethod
    def validate_links_field(cls, incoming_value: Any) -> list[str]:
        normalized_links_value = _normalize_links_value(
            incoming_value=incoming_value,
            allow_none_value=False,
        )
        return normalized_links_value or []


class PlanningRequestUpdateModel(PlanningRequestBaseModel):
    @field_validator("links", mode="before")
    @classmethod
    def validate_links_field(cls, incoming_value: Any) -> list[str] | None:
        return _normalize_links_value(
            incoming_value=incoming_value,
            allow_none_value=True,
        )


class PlanningRequestViewModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: int
    request_source: PlanningRequestSourceEnum
    request_kind: PlanningRequestKindEnum
    source_query_text: str | None = None
    source_message_text: str | None = None
    source_message_id: int | None = None
    telegram_user_id: int | None = None
    telegram_username: str | None = None
    telegram_first_name: str | None = None
    telegram_last_name: str | None = None
    client_name: str | None = None
    administrator_name: str | None = None
    client_reference_number: str | None = None
    price_amount: int | None = None
    posts_count: int | None = None
    thousand_message_price: int | None = None
    comment_text: str | None = None
    links: list[str] = Field(default_factory=list)
    created_at: int
    updated_at: int

    @field_validator("links", mode="before")
    @classmethod
    def validate_links_field(cls, incoming_value: Any) -> list[str]:
        normalized_links_value = _normalize_links_value(
            incoming_value=incoming_value,
            allow_none_value=False,
        )
        return normalized_links_value or []


def _normalize_optional_boolean_value(incoming_value: Any) -> bool | None:
    if incoming_value is None:
        return None
    if isinstance(incoming_value, bool):
        return incoming_value
    if isinstance(incoming_value, int):
        return incoming_value != 0
    normalized_text_value = str(incoming_value).strip().lower()
    if not normalized_text_value:
        return None
    if normalized_text_value in {"1", "true", "yes"}:
        return True
    if normalized_text_value in {"0", "false", "no"}:
        return False
    raise ValueError("Boolean value expected")


def _normalize_order_links_payload(
    incoming_value: Any,
    allow_none_value: bool,
) -> list[dict[str, Any]] | None:
    if incoming_value is None:
        return None if allow_none_value else []
    if isinstance(incoming_value, str):
        normalized_text_value = incoming_value.strip()
        if not normalized_text_value:
            return None if allow_none_value else []
        parsed_json_value = json.loads(normalized_text_value)
        if not isinstance(parsed_json_value, list):
            raise ValueError("order_links JSON must be list")
        values_for_iteration = parsed_json_value
    elif isinstance(incoming_value, (list, tuple)):
        values_for_iteration = list(incoming_value)
    else:
        raise ValueError("order_links must be list or JSON string")

    normalized_values: list[dict[str, Any]] = []
    for value_for_iteration in values_for_iteration:
        if isinstance(value_for_iteration, PlanningRequestReceiverLinkEntryModel):
            normalized_values.append(value_for_iteration.model_dump(mode="json"))
            continue
        if isinstance(value_for_iteration, dict):
            normalized_values.append(dict(value_for_iteration))
            continue
        raise ValueError("order_links item must be object")
    return normalized_values


class PlanningRequestReceiverLinkEntryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence_number: int
    srm_text: str = PLACEHOLDER_DASH
    original_links_message_text: str | None = None
    original_links_message_entities: list[dict[str, Any]] | None = None
    is_added_to_schedule: bool = False

    @field_validator("srm_text", mode="before")
    @classmethod
    def validate_srm_text(cls, incoming_value: Any) -> str:
        normalized_text_value = str(incoming_value or "").strip()
        return normalized_text_value or PLACEHOLDER_DASH

    @field_validator("is_added_to_schedule", mode="before")
    @classmethod
    def validate_is_added_to_schedule(cls, incoming_value: Any) -> bool:
        normalized_boolean_value = _normalize_optional_boolean_value(incoming_value)
        return bool(normalized_boolean_value)


class PlanningRequestReceiverContextBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planning_request_id: int | None = None
    receiver_chat_id: int | None = None
    order_message_id: int | None = None
    administrator_name: str | None = None
    order_message_text: str | None = None
    order_links: list[PlanningRequestReceiverLinkEntryModel] | None = None
    is_added_to_schedule: bool | None = None

    @field_validator(
        "planning_request_id",
        "receiver_chat_id",
        "order_message_id",
        mode="before",
    )
    @classmethod
    def validate_optional_integer_fields_for_receiver_context(cls, incoming_value: Any) -> int | None:
        return _normalize_optional_integer_value(incoming_value)

    @field_validator(
        "administrator_name",
        "order_message_text",
        mode="before",
    )
    @classmethod
    def validate_optional_text_fields_for_receiver_context(cls, incoming_value: Any) -> str | None:
        return _normalize_optional_text_value(incoming_value)

    @field_validator("order_links", mode="before")
    @classmethod
    def validate_order_links_field(
        cls,
        incoming_value: Any,
    ) -> list[PlanningRequestReceiverLinkEntryModel] | None:
        normalized_order_links_payload = _normalize_order_links_payload(
            incoming_value=incoming_value,
            allow_none_value=True,
        )
        if normalized_order_links_payload is None:
            return None
        return [
            PlanningRequestReceiverLinkEntryModel.model_validate(order_link_payload)
            for order_link_payload in normalized_order_links_payload
        ]

    @field_validator("is_added_to_schedule", mode="before")
    @classmethod
    def validate_optional_is_added_to_schedule(cls, incoming_value: Any) -> bool | None:
        return _normalize_optional_boolean_value(incoming_value)


class PlanningRequestReceiverContextCreateModel(PlanningRequestReceiverContextBaseModel):
    receiver_chat_id: int
    order_message_id: int
    order_message_text: str
    order_links: list[PlanningRequestReceiverLinkEntryModel] = Field(default_factory=list)
    is_added_to_schedule: bool = False


class PlanningRequestReceiverContextUpdateModel(PlanningRequestReceiverContextBaseModel):
    pass


class PlanningRequestReceiverContextViewModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: int
    planning_request_id: int | None = None
    receiver_chat_id: int
    order_message_id: int
    administrator_name: str | None = None
    order_message_text: str
    order_links: list[PlanningRequestReceiverLinkEntryModel] = Field(default_factory=list)
    is_added_to_schedule: bool = False
    created_at: int
    updated_at: int

    @field_validator("order_links", mode="before")
    @classmethod
    def validate_order_links_for_view_model(
        cls,
        incoming_value: Any,
    ) -> list[PlanningRequestReceiverLinkEntryModel]:
        normalized_order_links_payload = _normalize_order_links_payload(
            incoming_value=incoming_value,
            allow_none_value=False,
        )
        normalized_order_links_payload = normalized_order_links_payload or []
        return [
            PlanningRequestReceiverLinkEntryModel.model_validate(order_link_payload)
            for order_link_payload in normalized_order_links_payload
        ]

    @field_validator("is_added_to_schedule", mode="before")
    @classmethod
    def validate_is_added_to_schedule_for_view_model(cls, incoming_value: Any) -> bool:
        normalized_boolean_value = _normalize_optional_boolean_value(incoming_value)
        return bool(normalized_boolean_value)
