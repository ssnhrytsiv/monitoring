from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity

from app.DAL.planning_request_receiver_context_operations import (
    create_or_update_planning_request_receiver_context,
    delete_planning_request_receiver_context_by_message,
    get_latest_planning_request_receiver_context_by_receiver_and_administrator,
    get_planning_request_receiver_context_by_message,
    list_planning_request_receiver_contexts_by_receiver_chat_id,
    list_planning_request_receiver_contexts_by_planning_request_id,
)
from app.planning_bot.models import (
    PlanningRequestReceiverContextCreateModel,
    PlanningRequestReceiverLinkEntryModel,
)

log = logging.getLogger("planning_bot.order_links_navigation_service")

CALLBACK_DATA_OPEN_PREFIX = "planning_links_open:"
CALLBACK_DATA_BACK = "planning_links_back"
CALLBACK_DATA_SCHEDULE = "planning_links_schedule"
CALLBACK_DATA_SCHEDULE_PREFIX = "planning_links_schedule:"
CALLBACK_DATA_DELETE = "planning_links_delete"
CALLBACK_DATA_MANAGE_CARD = "planning_links_manage_card"
CALLBACK_DATA_CHECK_NETWORK = "planning_links_check_network"
CALLBACK_DATA_CHECK_NETWORK_SELECT_PREFIX = "planning_links_check_network_select:"
CALLBACK_DATA_CHECK_NETWORK_RUN = "planning_links_check_network_run"
CALLBACK_DATA_EDIT_SRM = "planning_links_edit_srm"
CALLBACK_DATA_EDIT_SRM_SELECT_PREFIX = "planning_links_edit_srm_select:"
CALLBACK_DATA_EDIT_SRM_SET_PREFIX = "planning_links_edit_srm_set:"
CALLBACK_DATA_EDIT_SRM_BACK_TO_SELECTION = "planning_links_edit_srm_back_to_selection"
ORDER_LINK_BUTTON_ATTACH_WINDOW_SECONDS = 300
MAX_ORIGINAL_LINKS_MESSAGE_TEXT_LENGTH = 3200
ORDER_LINKS_SRM_INPUT_MAX_AGE_SECONDS = 600


@dataclass
class OrderLinksButtonEntry:
    sequence_number: int
    srm_text: str
    original_links_message_text: str
    original_links_message_entities: list[MessageEntity] | None = None
    is_added_to_schedule: bool = False


@dataclass
class OrderLinksNavigationContext:
    receiver_chat_id: int
    order_message_id: int
    planning_request_id: int | None
    administrator_name: str
    order_message_text: str
    created_at_epoch_seconds: int
    order_links_button_entries: list[OrderLinksButtonEntry] = field(default_factory=list)


@dataclass
class PendingOrderLinksSrmInputContext:
    receiver_chat_id: int
    order_message_id: int
    sequence_number: int
    created_at_epoch_seconds: int


recent_order_links_navigation_context_by_message: dict[
    tuple[int, int],
    OrderLinksNavigationContext,
] = {}
recent_order_message_key_by_receiver_and_administrator: dict[
    tuple[int, str],
    tuple[int, int],
] = {}
recent_order_message_keys_by_planning_request_id: dict[int, set[tuple[int, int]]] = {}
pending_order_links_srm_input_by_user_id: dict[int, PendingOrderLinksSrmInputContext] = {}
selected_network_identifier_by_order_message_key: dict[tuple[int, int], int] = {}


def _current_epoch_seconds() -> int:
    return int(time.time())


def _normalize_administrator_name_for_matching(administrator_name: str | None) -> str:
    normalized_administrator_name = " ".join(str(administrator_name or "").split()).strip()
    if not normalized_administrator_name or normalized_administrator_name == "—":
        return ""
    return normalized_administrator_name.casefold()


def _extract_administrator_name_from_order_message_text(
    order_message_text: str | None,
) -> str:
    normalized_order_message_text = str(order_message_text or "").strip()
    if not normalized_order_message_text:
        return ""

    for order_message_line in normalized_order_message_text.splitlines():
        line_value = order_message_line.strip()
        if not line_value:
            continue
        line_value_lowercase = line_value.casefold()
        if (
            line_value_lowercase.startswith("админ:")
            or line_value_lowercase.startswith("адмін:")
            or line_value_lowercase.startswith("admin:")
        ):
            _, _, administrator_name_value = line_value.partition(":")
            return " ".join(administrator_name_value.split()).strip()
    return ""


def _utf16_length(text_value: str) -> int:
    return len(text_value.encode("utf-16-le")) // 2


def _truncate_original_links_message_text_and_entities(
    original_links_message_text: str,
    original_links_message_entities: list[MessageEntity] | None,
) -> tuple[str, list[MessageEntity] | None]:
    text_value = original_links_message_text or ""
    if not text_value.strip():
        return "—", None

    if len(text_value) <= MAX_ORIGINAL_LINKS_MESSAGE_TEXT_LENGTH:
        return text_value, original_links_message_entities

    truncated_text = text_value[:MAX_ORIGINAL_LINKS_MESSAGE_TEXT_LENGTH].rstrip() + "…"
    if not original_links_message_entities:
        return truncated_text, None

    truncated_text_utf16_length = _utf16_length(truncated_text)
    filtered_entities: list[MessageEntity] = []
    for message_entity in original_links_message_entities:
        if message_entity.offset < 0 or message_entity.length <= 0:
            continue
        if (message_entity.offset + message_entity.length) <= truncated_text_utf16_length:
            filtered_entities.append(message_entity)
    return truncated_text, filtered_entities or None


def _serialize_message_entities_to_payload(
    original_links_message_entities: list[MessageEntity] | None,
) -> list[dict[str, object]] | None:
    if not original_links_message_entities:
        return None
    return [
        message_entity.model_dump(mode="json")
        for message_entity in original_links_message_entities
    ]


def _deserialize_message_entities_from_payload(
    original_links_message_entities_payload: list[dict[str, object]] | None,
) -> list[MessageEntity] | None:
    if not original_links_message_entities_payload:
        return None
    return [
        MessageEntity.model_validate(message_entity_payload)
        for message_entity_payload in original_links_message_entities_payload
    ]


def _serialize_order_links_button_entries_to_payload(
    order_links_button_entries: list[OrderLinksButtonEntry],
) -> list[PlanningRequestReceiverLinkEntryModel]:
    serialized_order_links_button_entries: list[PlanningRequestReceiverLinkEntryModel] = []
    for order_links_button_entry in order_links_button_entries:
        serialized_order_links_button_entries.append(
            PlanningRequestReceiverLinkEntryModel(
                sequence_number=order_links_button_entry.sequence_number,
                srm_text=order_links_button_entry.srm_text,
                original_links_message_text=order_links_button_entry.original_links_message_text,
                original_links_message_entities=_serialize_message_entities_to_payload(
                    order_links_button_entry.original_links_message_entities
                ),
                is_added_to_schedule=order_links_button_entry.is_added_to_schedule,
            )
        )
    return serialized_order_links_button_entries


def _deserialize_order_links_button_entries_from_payload(
    order_links_payload: list[PlanningRequestReceiverLinkEntryModel],
) -> list[OrderLinksButtonEntry]:
    deserialized_order_links_button_entries: list[OrderLinksButtonEntry] = []
    for order_links_payload_item in order_links_payload:
        deserialized_order_links_button_entries.append(
            OrderLinksButtonEntry(
                sequence_number=order_links_payload_item.sequence_number,
                srm_text=order_links_payload_item.srm_text,
                original_links_message_text=order_links_payload_item.original_links_message_text or "",
                original_links_message_entities=_deserialize_message_entities_from_payload(
                    order_links_payload_item.original_links_message_entities
                ),
                is_added_to_schedule=order_links_payload_item.is_added_to_schedule,
            )
        )
    return deserialized_order_links_button_entries


def _cache_order_links_navigation_context(order_links_navigation_context: OrderLinksNavigationContext) -> None:
    order_message_key = (
        order_links_navigation_context.receiver_chat_id,
        order_links_navigation_context.order_message_id,
    )
    recent_order_links_navigation_context_by_message[order_message_key] = order_links_navigation_context

    normalized_administrator_name = _normalize_administrator_name_for_matching(
        order_links_navigation_context.administrator_name
    )
    if normalized_administrator_name:
        recent_order_message_key_by_receiver_and_administrator[
            (order_links_navigation_context.receiver_chat_id, normalized_administrator_name)
        ] = order_message_key

    if order_links_navigation_context.planning_request_id is not None:
        if order_links_navigation_context.planning_request_id not in recent_order_message_keys_by_planning_request_id:
            recent_order_message_keys_by_planning_request_id[
                order_links_navigation_context.planning_request_id
            ] = set()
        recent_order_message_keys_by_planning_request_id[
            order_links_navigation_context.planning_request_id
        ].add(order_message_key)


def _save_order_links_navigation_context_to_database(
    order_links_navigation_context: OrderLinksNavigationContext,
) -> None:
    try:
        create_or_update_planning_request_receiver_context(
            PlanningRequestReceiverContextCreateModel(
                planning_request_id=order_links_navigation_context.planning_request_id,
                receiver_chat_id=order_links_navigation_context.receiver_chat_id,
                order_message_id=order_links_navigation_context.order_message_id,
                administrator_name=order_links_navigation_context.administrator_name,
                order_message_text=order_links_navigation_context.order_message_text,
                order_links=_serialize_order_links_button_entries_to_payload(
                    order_links_navigation_context.order_links_button_entries
                ),
                is_added_to_schedule=is_order_added_to_schedule(order_links_navigation_context),
            )
        )
    except Exception:
        log.exception(
            "failed to persist order links navigation context: receiver_chat_id=%s order_message_id=%s",
            order_links_navigation_context.receiver_chat_id,
            order_links_navigation_context.order_message_id,
        )


def _load_order_links_navigation_context_from_database_by_message(
    receiver_chat_id: int,
    order_message_id: int,
) -> OrderLinksNavigationContext | None:
    try:
        planning_request_receiver_context_view_model = get_planning_request_receiver_context_by_message(
            receiver_chat_id=receiver_chat_id,
            order_message_id=order_message_id,
        )
    except Exception:
        log.exception(
            "failed to load order links navigation context from database: receiver_chat_id=%s order_message_id=%s",
            receiver_chat_id,
            order_message_id,
        )
        return None
    if planning_request_receiver_context_view_model is None:
        return None

    order_links_navigation_context = OrderLinksNavigationContext(
        receiver_chat_id=int(planning_request_receiver_context_view_model.receiver_chat_id),
        order_message_id=int(planning_request_receiver_context_view_model.order_message_id),
        planning_request_id=planning_request_receiver_context_view_model.planning_request_id,
        administrator_name=planning_request_receiver_context_view_model.administrator_name or "—",
        order_message_text=planning_request_receiver_context_view_model.order_message_text,
        created_at_epoch_seconds=planning_request_receiver_context_view_model.updated_at,
        order_links_button_entries=_deserialize_order_links_button_entries_from_payload(
            planning_request_receiver_context_view_model.order_links
        ),
    )
    _cache_order_links_navigation_context(order_links_navigation_context)
    return order_links_navigation_context


def build_order_links_original_keyboard(
    order_links_navigation_context: OrderLinksNavigationContext,
) -> InlineKeyboardMarkup | None:
    inline_keyboard_rows: list[list[InlineKeyboardButton]] = []
    for order_links_button_entry in order_links_navigation_context.order_links_button_entries:
        inline_keyboard_rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"{order_links_button_entry.sequence_number}. "
                        f"Открыть список ссылок | СРМ: {order_links_button_entry.srm_text}"
                    ),
                    callback_data=f"{CALLBACK_DATA_OPEN_PREFIX}{order_links_button_entry.sequence_number}",
                )
            ]
        )

    schedule_button_text = (
        "Добавлен в график"
        if is_order_added_to_schedule(order_links_navigation_context)
        else "Добавить в график"
    )
    schedule_button_style = (
        "success"
        if is_order_added_to_schedule(order_links_navigation_context)
        else "primary"
    )
    inline_keyboard_rows.append(
        [
            InlineKeyboardButton(
                text="Управление карткой",
                callback_data=CALLBACK_DATA_MANAGE_CARD,
            )
        ]
    )
    inline_keyboard_rows.append(
        [
            InlineKeyboardButton(
                text=schedule_button_text,
                callback_data=CALLBACK_DATA_SCHEDULE,
                style=schedule_button_style,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard_rows)


def build_order_links_initial_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Управление карткой",
                    callback_data=CALLBACK_DATA_MANAGE_CARD,
                )
            ],
            [
                InlineKeyboardButton(
                    text="Добавить в график",
                    callback_data=CALLBACK_DATA_SCHEDULE,
                    style="primary",
                )
            ],
        ]
    )


def build_order_links_manage_card_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Редагувати СРМ",
                    callback_data=CALLBACK_DATA_EDIT_SRM,
                )
            ],
            [
                InlineKeyboardButton(
                    text="Удалить запись",
                    callback_data=CALLBACK_DATA_DELETE,
                    style="danger",
                )
            ],
            [InlineKeyboardButton(text="Назад", callback_data=CALLBACK_DATA_BACK)],
        ]
    )


def build_order_links_details_keyboard(_order_links_button_entry: OrderLinksButtonEntry) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Перевірити сітку", callback_data=CALLBACK_DATA_CHECK_NETWORK)],
            [InlineKeyboardButton(text="Назад", callback_data=CALLBACK_DATA_BACK)],
        ]
    )


def build_order_links_edit_srm_selection_text(
    order_links_navigation_context: OrderLinksNavigationContext,
) -> str:
    return (
        "Обери посилання для редагування СРМ.\n"
        f"Админ: {order_links_navigation_context.administrator_name}"
    )


def build_order_links_edit_srm_selection_keyboard(
    order_links_navigation_context: OrderLinksNavigationContext,
) -> InlineKeyboardMarkup:
    inline_keyboard_rows: list[list[InlineKeyboardButton]] = []
    for order_links_button_entry in order_links_navigation_context.order_links_button_entries:
        inline_keyboard_rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"Ссылки №{order_links_button_entry.sequence_number} "
                        f"срм {order_links_button_entry.srm_text}"
                    ),
                    callback_data=(
                        f"{CALLBACK_DATA_EDIT_SRM_SELECT_PREFIX}{order_links_button_entry.sequence_number}"
                    ),
                )
            ]
        )
    inline_keyboard_rows.append(
        [InlineKeyboardButton(text="Назад", callback_data=CALLBACK_DATA_BACK)]
    )
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard_rows)


def build_order_links_edit_srm_selected_text(order_links_button_entry: OrderLinksButtonEntry) -> str:
    return (
        f"Ссылки №{order_links_button_entry.sequence_number}\n"
        f"Поточний СРМ: {order_links_button_entry.srm_text}"
    )


def build_order_links_edit_srm_selected_keyboard(sequence_number: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Задати новий срм",
                    callback_data=f"{CALLBACK_DATA_EDIT_SRM_SET_PREFIX}{sequence_number}",
                )
            ],
            [InlineKeyboardButton(text="Назад", callback_data=CALLBACK_DATA_EDIT_SRM_BACK_TO_SELECTION)],
        ]
    )


def build_order_links_edit_srm_input_text(order_links_button_entry: OrderLinksButtonEntry) -> str:
    return (
        f"Ссылки №{order_links_button_entry.sequence_number}\n"
        f"Поточний СРМ: {order_links_button_entry.srm_text}\n"
        "Введи новий СРМ цифрами."
    )


def build_order_links_edit_srm_input_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data=CALLBACK_DATA_EDIT_SRM_BACK_TO_SELECTION)],
        ]
    )


def get_selected_network_identifier_for_order_message(
    receiver_chat_id: int,
    order_message_id: int,
) -> int | None:
    return selected_network_identifier_by_order_message_key.get(
        (receiver_chat_id, order_message_id)
    )


def set_selected_network_identifier_for_order_message(
    receiver_chat_id: int,
    order_message_id: int,
    network_identifier: int,
) -> None:
    selected_network_identifier_by_order_message_key[
        (receiver_chat_id, order_message_id)
    ] = int(network_identifier)


def build_order_links_check_network_selection_text(
    administrator_name: str,
    network_selection_record_list: list[dict[str, object]],
    selected_network_identifier: int | None,
) -> str:
    selected_network_name = "—"
    if selected_network_identifier is not None:
        for network_selection_record in network_selection_record_list:
            network_identifier = int(network_selection_record.get("network_id") or 0)
            if network_identifier == int(selected_network_identifier):
                selected_network_name = str(
                    network_selection_record.get("network_name") or selected_network_identifier
                )
                break
    return (
        "Обери сітку для перевірки.\n"
        f"Адмін: {administrator_name}\n"
        f"Доступно сіток: {len(network_selection_record_list)}\n"
        f"Обрана сітка: {selected_network_name}"
    )


def build_order_links_check_network_selection_keyboard(
    network_selection_record_list: list[dict[str, object]],
    selected_network_identifier: int | None,
) -> InlineKeyboardMarkup:
    inline_keyboard_rows: list[list[InlineKeyboardButton]] = []
    for network_selection_record in network_selection_record_list:
        network_identifier = int(network_selection_record.get("network_id") or 0)
        network_name = str(network_selection_record.get("network_name") or "").strip()
        button_text = network_name
        if (
            selected_network_identifier is not None
            and int(selected_network_identifier) == network_identifier
        ):
            button_text = f"✅ {network_name}"
        inline_keyboard_rows.append(
            [
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=(
                        f"{CALLBACK_DATA_CHECK_NETWORK_SELECT_PREFIX}{network_identifier}"
                    ),
                )
            ]
        )
    if selected_network_identifier is not None:
        inline_keyboard_rows.append(
            [
                InlineKeyboardButton(
                    text="Запустити перевірку сітки",
                    callback_data=CALLBACK_DATA_CHECK_NETWORK_RUN,
                )
            ]
        )
    inline_keyboard_rows.append(
        [InlineKeyboardButton(text="Назад", callback_data=CALLBACK_DATA_BACK)]
    )
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard_rows)


def register_recent_order_message_for_administrator(
    receiver_chat_id: int,
    order_message_id: int | None,
    planning_request_id: int | None,
    administrator_name: str,
    order_message_text: str,
) -> None:
    if order_message_id is None:
        return

    normalized_administrator_name = _normalize_administrator_name_for_matching(administrator_name)
    if not normalized_administrator_name:
        return

    order_links_navigation_context = OrderLinksNavigationContext(
        receiver_chat_id=receiver_chat_id,
        order_message_id=order_message_id,
        planning_request_id=planning_request_id,
        administrator_name=administrator_name,
        order_message_text=order_message_text,
        created_at_epoch_seconds=_current_epoch_seconds(),
    )
    _cache_order_links_navigation_context(order_links_navigation_context)
    _save_order_links_navigation_context_to_database(order_links_navigation_context)


def get_order_message_keys_by_planning_request_id(planning_request_id: int) -> list[tuple[int, int]]:
    order_message_keys_in_memory = set(
        recent_order_message_keys_by_planning_request_id.get(planning_request_id, set())
    )
    try:
        planning_request_receiver_context_view_models = (
            list_planning_request_receiver_contexts_by_planning_request_id(planning_request_id)
        )
    except Exception:
        log.exception(
            "failed to load receiver contexts for planning_request_id=%s",
            planning_request_id,
        )
        return list(order_message_keys_in_memory)
    for planning_request_receiver_context_view_model in planning_request_receiver_context_view_models:
        order_links_navigation_context = OrderLinksNavigationContext(
            receiver_chat_id=int(planning_request_receiver_context_view_model.receiver_chat_id),
            order_message_id=int(planning_request_receiver_context_view_model.order_message_id),
            planning_request_id=planning_request_receiver_context_view_model.planning_request_id,
            administrator_name=planning_request_receiver_context_view_model.administrator_name or "—",
            order_message_text=planning_request_receiver_context_view_model.order_message_text,
            created_at_epoch_seconds=planning_request_receiver_context_view_model.updated_at,
            order_links_button_entries=_deserialize_order_links_button_entries_from_payload(
                planning_request_receiver_context_view_model.order_links
            ),
        )
        _cache_order_links_navigation_context(order_links_navigation_context)
        order_message_keys_in_memory.add(
            (
                order_links_navigation_context.receiver_chat_id,
                order_links_navigation_context.order_message_id,
            )
        )
    return list(order_message_keys_in_memory)


def remove_order_navigation_contexts_by_message_keys(order_message_keys: list[tuple[int, int]]) -> None:
    for order_message_key in order_message_keys:
        selected_network_identifier_by_order_message_key.pop(order_message_key, None)
        try:
            delete_planning_request_receiver_context_by_message(
                receiver_chat_id=order_message_key[0],
                order_message_id=order_message_key[1],
            )
        except Exception:
            log.exception(
                "failed to delete receiver context from database: receiver_chat_id=%s order_message_id=%s",
                order_message_key[0],
                order_message_key[1],
            )

        order_links_navigation_context = recent_order_links_navigation_context_by_message.pop(
            order_message_key,
            None,
        )
        if order_links_navigation_context is None:
            continue

        normalized_administrator_name = _normalize_administrator_name_for_matching(
            order_links_navigation_context.administrator_name
        )
        if normalized_administrator_name:
            mapped_message_key = recent_order_message_key_by_receiver_and_administrator.get(
                (order_links_navigation_context.receiver_chat_id, normalized_administrator_name)
            )
            if mapped_message_key == order_message_key:
                recent_order_message_key_by_receiver_and_administrator.pop(
                    (order_links_navigation_context.receiver_chat_id, normalized_administrator_name),
                    None,
                )

        if order_links_navigation_context.planning_request_id is None:
            continue
        order_message_keys_for_planning_request = recent_order_message_keys_by_planning_request_id.get(
            order_links_navigation_context.planning_request_id
        )
        if not order_message_keys_for_planning_request:
            continue
        order_message_keys_for_planning_request.discard(order_message_key)
        if not order_message_keys_for_planning_request:
            recent_order_message_keys_by_planning_request_id.pop(
                order_links_navigation_context.planning_request_id,
                None,
            )


def get_order_links_navigation_context_by_message(
    receiver_chat_id: int,
    order_message_id: int,
) -> OrderLinksNavigationContext | None:
    order_links_navigation_context = recent_order_links_navigation_context_by_message.get(
        (receiver_chat_id, order_message_id)
    )
    if order_links_navigation_context is not None:
        return order_links_navigation_context
    return _load_order_links_navigation_context_from_database_by_message(
        receiver_chat_id=receiver_chat_id,
        order_message_id=order_message_id,
    )


def get_order_links_button_entry_by_sequence_number(
    order_links_navigation_context: OrderLinksNavigationContext,
    sequence_number: int,
) -> OrderLinksButtonEntry | None:
    for order_links_button_entry in order_links_navigation_context.order_links_button_entries:
        if order_links_button_entry.sequence_number == sequence_number:
            return order_links_button_entry
    return None


def update_order_links_button_entry_srm_text(
    order_links_navigation_context: OrderLinksNavigationContext,
    sequence_number: int,
    new_srm_text: str,
) -> bool:
    order_links_button_entry = get_order_links_button_entry_by_sequence_number(
        order_links_navigation_context=order_links_navigation_context,
        sequence_number=sequence_number,
    )
    if order_links_button_entry is None:
        return False
    normalized_srm_text = (new_srm_text or "").strip()
    if not normalized_srm_text:
        return False
    order_links_button_entry.srm_text = normalized_srm_text
    _save_order_links_navigation_context_to_database(order_links_navigation_context)
    return True


def set_pending_order_links_srm_input_for_user(
    telegram_user_id: int | None,
    receiver_chat_id: int,
    order_message_id: int,
    sequence_number: int,
) -> None:
    if telegram_user_id is None:
        return
    pending_order_links_srm_input_by_user_id[telegram_user_id] = PendingOrderLinksSrmInputContext(
        receiver_chat_id=receiver_chat_id,
        order_message_id=order_message_id,
        sequence_number=sequence_number,
        created_at_epoch_seconds=_current_epoch_seconds(),
    )


def get_pending_order_links_srm_input_for_user(
    telegram_user_id: int | None,
) -> PendingOrderLinksSrmInputContext | None:
    if telegram_user_id is None:
        return None

    pending_order_links_srm_input_context = pending_order_links_srm_input_by_user_id.get(telegram_user_id)
    if pending_order_links_srm_input_context is None:
        return None

    age_seconds = _current_epoch_seconds() - pending_order_links_srm_input_context.created_at_epoch_seconds
    if age_seconds > ORDER_LINKS_SRM_INPUT_MAX_AGE_SECONDS:
        pending_order_links_srm_input_by_user_id.pop(telegram_user_id, None)
        return None

    return pending_order_links_srm_input_context


def has_pending_order_links_srm_input_for_user(telegram_user_id: int | None) -> bool:
    return get_pending_order_links_srm_input_for_user(telegram_user_id) is not None


def clear_pending_order_links_srm_input_for_user(telegram_user_id: int | None) -> None:
    if telegram_user_id is None:
        return
    pending_order_links_srm_input_by_user_id.pop(telegram_user_id, None)


def build_order_links_details_text(
    order_links_button_entry: OrderLinksButtonEntry,
) -> tuple[str, list[MessageEntity] | None]:
    details_text, details_entities = _truncate_original_links_message_text_and_entities(
        original_links_message_text=order_links_button_entry.original_links_message_text,
        original_links_message_entities=order_links_button_entry.original_links_message_entities,
    )

    if not order_links_button_entry.is_added_to_schedule:
        return details_text, details_entities

    added_label_text = "ДОБАВЛЕНО"
    details_text_with_status = f"{details_text}\n\n{added_label_text} ✅"
    details_entities_with_status = list(details_entities or [])
    details_entities_with_status.append(
        MessageEntity(
            type="bold",
            offset=_utf16_length(f"{details_text}\n\n"),
            length=_utf16_length(added_label_text),
        )
    )
    return details_text_with_status, details_entities_with_status


def build_order_message_text_with_status(
    order_links_navigation_context: OrderLinksNavigationContext,
) -> tuple[str, list[MessageEntity] | None]:
    if not is_order_added_to_schedule(order_links_navigation_context):
        return order_links_navigation_context.order_message_text, None

    added_label_text = "ДОБАВЛЕНО"
    order_text_with_status = f"{order_links_navigation_context.order_message_text}\n\n{added_label_text} ✅"
    order_text_entities = [
        MessageEntity(
            type="bold",
            offset=_utf16_length(f"{order_links_navigation_context.order_message_text}\n\n"),
            length=_utf16_length(added_label_text),
        )
    ]
    return order_text_with_status, order_text_entities


def is_order_added_to_schedule(order_links_navigation_context: OrderLinksNavigationContext) -> bool:
    return any(
        order_links_button_entry.is_added_to_schedule
        for order_links_button_entry in order_links_navigation_context.order_links_button_entries
    )


def toggle_order_links_schedule_state(
    order_links_navigation_context: OrderLinksNavigationContext,
) -> bool:
    new_schedule_state = not is_order_added_to_schedule(order_links_navigation_context)
    for order_links_button_entry in order_links_navigation_context.order_links_button_entries:
        order_links_button_entry.is_added_to_schedule = new_schedule_state
    _save_order_links_navigation_context_to_database(order_links_navigation_context)
    return new_schedule_state


async def attach_links_button_to_recent_order_message(
    bot: Bot,
    receiver_chat_id: int,
    administrator_name: str,
    srm_text: str,
    original_links_message_text: str | None,
    original_links_message_entities: list[MessageEntity] | None = None,
) -> None:
    normalized_administrator_name = _normalize_administrator_name_for_matching(administrator_name)
    if not normalized_administrator_name:
        return

    order_message_key = recent_order_message_key_by_receiver_and_administrator.get(
        (receiver_chat_id, normalized_administrator_name)
    )
    if order_message_key is None:
        try:
            latest_receiver_context_view_model = (
                get_latest_planning_request_receiver_context_by_receiver_and_administrator(
                    receiver_chat_id=receiver_chat_id,
                    administrator_name=administrator_name,
                )
            )
            if latest_receiver_context_view_model is None:
                receiver_context_candidates = list_planning_request_receiver_contexts_by_receiver_chat_id(
                    receiver_chat_id=receiver_chat_id,
                    limit=100,
                )
                for receiver_context_candidate in receiver_context_candidates:
                    candidate_administrator_name = _normalize_administrator_name_for_matching(
                        receiver_context_candidate.administrator_name
                    )
                    candidate_administrator_name_from_message_text = (
                        _normalize_administrator_name_for_matching(
                            _extract_administrator_name_from_order_message_text(
                                receiver_context_candidate.order_message_text
                            )
                        )
                    )
                    if (
                        candidate_administrator_name == normalized_administrator_name
                        or candidate_administrator_name_from_message_text
                        == normalized_administrator_name
                    ):
                        latest_receiver_context_view_model = receiver_context_candidate
                        break
        except Exception:
            log.exception(
                "failed to resolve latest receiver context by administrator: receiver_chat_id=%s administrator_name=%s",
                receiver_chat_id,
                administrator_name,
            )
            return
        if latest_receiver_context_view_model is None:
            return
        order_links_navigation_context = OrderLinksNavigationContext(
            receiver_chat_id=int(latest_receiver_context_view_model.receiver_chat_id),
            order_message_id=int(latest_receiver_context_view_model.order_message_id),
            planning_request_id=latest_receiver_context_view_model.planning_request_id,
            administrator_name=latest_receiver_context_view_model.administrator_name or administrator_name,
            order_message_text=latest_receiver_context_view_model.order_message_text,
            created_at_epoch_seconds=latest_receiver_context_view_model.updated_at,
            order_links_button_entries=_deserialize_order_links_button_entries_from_payload(
                latest_receiver_context_view_model.order_links
            ),
        )
        _cache_order_links_navigation_context(order_links_navigation_context)
        order_message_key = (order_links_navigation_context.receiver_chat_id, order_links_navigation_context.order_message_id)

    order_links_navigation_context = recent_order_links_navigation_context_by_message.get(order_message_key)
    if order_links_navigation_context is None:
        order_links_navigation_context = _load_order_links_navigation_context_from_database_by_message(
            receiver_chat_id=order_message_key[0],
            order_message_id=order_message_key[1],
        )
        if order_links_navigation_context is None:
            return

    age_seconds = _current_epoch_seconds() - order_links_navigation_context.created_at_epoch_seconds
    if age_seconds > ORDER_LINK_BUTTON_ATTACH_WINDOW_SECONDS:
        remove_order_navigation_contexts_by_message_keys([order_message_key])
        return

    srm_text_value = (srm_text or "").strip() or "—"
    existing_schedule_state = is_order_added_to_schedule(order_links_navigation_context)
    order_links_navigation_context.order_links_button_entries.append(
        OrderLinksButtonEntry(
            sequence_number=len(order_links_navigation_context.order_links_button_entries) + 1,
            srm_text=srm_text_value,
            original_links_message_text=original_links_message_text or "",
            original_links_message_entities=original_links_message_entities or None,
            is_added_to_schedule=existing_schedule_state,
        )
    )
    order_links_navigation_context.created_at_epoch_seconds = _current_epoch_seconds()
    _save_order_links_navigation_context_to_database(order_links_navigation_context)
    order_text_with_status, order_text_entities = build_order_message_text_with_status(
        order_links_navigation_context
    )

    await bot.edit_message_text(
        chat_id=order_links_navigation_context.receiver_chat_id,
        message_id=order_links_navigation_context.order_message_id,
        text=order_text_with_status,
        parse_mode=None,
        entities=order_text_entities,
        reply_markup=build_order_links_original_keyboard(order_links_navigation_context),
    )
