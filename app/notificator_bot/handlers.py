from __future__ import annotations

import uuid
from typing import List

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from sqlalchemy.exc import IntegrityError

from app.DAL.notifier_message_pages_operations import (
    bind_notification_page_session_to_message,
    count_notification_pages_for_message_session,
    create_notification_page_session_records,
    delete_notification_page_records_for_message,
    delete_notification_page_session_records,
    get_notification_page_text_for_message,
)


NOTIFICATION_PAGE_CALLBACK_PREFIX = "notifier_page"


async def inline_handler(inline_query: InlineQuery) -> None:
    query = inline_query.query.strip()
    if not query:
        title = "Статусы вотчей"
        message = "Скоро тут будуть швидкі команди для статусів."
    else:
        title = f"Запит: {query}"
        message = f"Ви надіслали: {query}\n(інлайн-режим тестовий)"

    result = InlineQueryResultArticle(
        id="status_1",
        title=title,
        input_message_content=InputTextMessageContent(message_text=message),
        description="Тестова відповідь нотіфікатора",
    )
    await inline_query.answer([result], cache_time=1, is_personal=True)


def discard_notification_page_session(notification_page_session_identifier: str) -> None:
    delete_notification_page_session_records(notification_page_session_identifier)


def create_notification_page_session(notification_page_texts: List[str]) -> str:
    for _ in range(3):
        notification_page_session_identifier = uuid.uuid4().hex
        try:
            create_notification_page_session_records(
                notification_page_session_identifier,
                notification_page_texts,
            )
            return notification_page_session_identifier
        except IntegrityError:
            continue
    raise RuntimeError("Failed to create unique notification page session identifier")


def attach_notification_page_session_to_message(
    chat_id: int,
    message_id: int,
    notification_page_session_identifier: str,
) -> None:
    delete_notification_page_records_for_message(chat_id, message_id)
    bind_notification_page_session_to_message(
        notification_page_session_identifier,
        chat_id,
        message_id,
    )


def remove_notification_page_session_for_message(chat_id: int, message_id: int) -> None:
    delete_notification_page_records_for_message(chat_id, message_id)


def build_notification_navigation_markup(
    notification_page_session_identifier: str,
    current_page_number: int,
    total_page_count: int,
) -> InlineKeyboardMarkup | None:
    if total_page_count <= 1:
        return None

    navigation_buttons: List[InlineKeyboardButton] = []
    if current_page_number > 0:
        previous_page_number = current_page_number - 1
        navigation_buttons.append(
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=(
                    f"{NOTIFICATION_PAGE_CALLBACK_PREFIX}:{notification_page_session_identifier}:{previous_page_number}"
                ),
            )
        )

    if current_page_number < total_page_count - 1:
        next_page_number = current_page_number + 1
        navigation_buttons.append(
            InlineKeyboardButton(
                text="Вперед ➡️",
                callback_data=f"{NOTIFICATION_PAGE_CALLBACK_PREFIX}:{notification_page_session_identifier}:{next_page_number}",
            )
        )

    if not navigation_buttons:
        return None

    return InlineKeyboardMarkup(inline_keyboard=[navigation_buttons])


async def notification_page_navigation_handler(callback_query: CallbackQuery) -> None:
    callback_data = callback_query.data or ""
    callback_parts = callback_data.split(":", 2)
    if len(callback_parts) != 3:
        await callback_query.answer()
        return

    _, notification_page_session_identifier, requested_page_number_raw = callback_parts

    message = callback_query.message
    if message is None:
        await callback_query.answer()
        return

    chat_id = int(message.chat.id)
    message_id = int(message.message_id)
    total_page_count = count_notification_pages_for_message_session(
        notification_page_session_identifier,
        chat_id,
        message_id,
    )
    if total_page_count <= 0:
        await callback_query.answer("Сторінки вже недоступні")
        return

    try:
        requested_page_number = int(requested_page_number_raw)
    except ValueError:
        await callback_query.answer()
        return

    target_page_number = min(max(0, requested_page_number), total_page_count - 1)
    target_page_text = get_notification_page_text_for_message(
        notification_page_session_identifier,
        chat_id,
        message_id,
        target_page_number,
    )
    if target_page_text is None:
        await callback_query.answer("Сторінки вже недоступні")
        return

    navigation_markup = build_notification_navigation_markup(
        notification_page_session_identifier,
        target_page_number,
        total_page_count,
    )

    try:
        await message.edit_text(
            text=target_page_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=navigation_markup,
        )
    except TelegramBadRequest as exception:
        if "message is not modified" not in str(exception).lower():
            raise

    await callback_query.answer(f"{target_page_number + 1}/{total_page_count}")
