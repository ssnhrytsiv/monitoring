from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from app.DAL.planning_requests_operations import delete_planning_request_by_id
from app.planning_bot.services.order_links_navigation_service import (
    CALLBACK_DATA_BACK,
    CALLBACK_DATA_DELETE,
    CALLBACK_DATA_EDIT_SRM,
    CALLBACK_DATA_EDIT_SRM_BACK_TO_SELECTION,
    CALLBACK_DATA_EDIT_SRM_SELECT_PREFIX,
    CALLBACK_DATA_EDIT_SRM_SET_PREFIX,
    CALLBACK_DATA_OPEN_PREFIX,
    CALLBACK_DATA_SCHEDULE,
    CALLBACK_DATA_SCHEDULE_PREFIX,
    build_order_links_edit_srm_input_keyboard,
    build_order_links_edit_srm_input_text,
    build_order_links_edit_srm_selected_keyboard,
    build_order_links_edit_srm_selected_text,
    build_order_links_edit_srm_selection_keyboard,
    build_order_links_edit_srm_selection_text,
    build_order_links_details_keyboard,
    build_order_links_details_text,
    build_order_message_text_with_status,
    build_order_links_original_keyboard,
    clear_pending_order_links_srm_input_for_user,
    get_order_links_button_entry_by_sequence_number,
    get_order_message_keys_by_planning_request_id,
    get_pending_order_links_srm_input_for_user,
    get_order_links_navigation_context_by_message,
    has_pending_order_links_srm_input_for_user,
    remove_order_navigation_contexts_by_message_keys,
    set_pending_order_links_srm_input_for_user,
    toggle_order_links_schedule_state,
    update_order_links_button_entry_srm_text,
)


router = Router(name="planning_order_links_navigation")
log = logging.getLogger("planning_bot.order_links_navigation")


@router.callback_query(F.data.startswith(CALLBACK_DATA_OPEN_PREFIX))
async def handle_order_links_open_button(callback_query: CallbackQuery) -> None:
    callback_query_message = callback_query.message
    if callback_query_message is None:
        await callback_query.answer("Повідомлення недоступне", show_alert=True)
        return

    callback_query_data = callback_query.data or ""
    try:
        sequence_number = int(callback_query_data.split(":")[-1])
    except Exception:
        await callback_query.answer("Некоректний номер", show_alert=True)
        return

    order_links_navigation_context = get_order_links_navigation_context_by_message(
        receiver_chat_id=callback_query_message.chat.id,
        order_message_id=callback_query_message.message_id,
    )
    if order_links_navigation_context is None:
        await callback_query.answer("Дані застаріли", show_alert=True)
        return

    order_links_button_entry = get_order_links_button_entry_by_sequence_number(
        order_links_navigation_context=order_links_navigation_context,
        sequence_number=sequence_number,
    )
    if order_links_button_entry is None:
        await callback_query.answer("Посилання не знайдено", show_alert=True)
        return

    details_text, details_entities = build_order_links_details_text(
        order_links_button_entry=order_links_button_entry,
    )

    try:
        await callback_query_message.edit_text(
            text=details_text,
            parse_mode=None,
            entities=details_entities,
            reply_markup=build_order_links_details_keyboard(order_links_button_entry),
        )
    except Exception:
        log.exception(
            "failed to open order links details: chat_id=%s message_id=%s sequence=%s",
            callback_query_message.chat.id,
            callback_query_message.message_id,
            sequence_number,
        )
        await callback_query.answer("Не вдалося відкрити", show_alert=True)
        return

    await callback_query.answer()


@router.callback_query(F.data == CALLBACK_DATA_EDIT_SRM)
async def handle_order_links_edit_srm_button(callback_query: CallbackQuery) -> None:
    callback_query_message = callback_query.message
    if callback_query_message is None:
        await callback_query.answer("Повідомлення недоступне", show_alert=True)
        return

    order_links_navigation_context = get_order_links_navigation_context_by_message(
        receiver_chat_id=callback_query_message.chat.id,
        order_message_id=callback_query_message.message_id,
    )
    if order_links_navigation_context is None:
        await callback_query.answer("Дані застаріли", show_alert=True)
        return
    if not order_links_navigation_context.order_links_button_entries:
        await callback_query.answer("Посилання не знайдено", show_alert=True)
        return

    try:
        await callback_query_message.edit_text(
            text=build_order_links_edit_srm_selection_text(order_links_navigation_context),
            parse_mode=None,
            reply_markup=build_order_links_edit_srm_selection_keyboard(order_links_navigation_context),
        )
    except Exception:
        log.exception(
            "failed to open srm editing selection: chat_id=%s message_id=%s",
            callback_query_message.chat.id,
            callback_query_message.message_id,
        )
        await callback_query.answer("Не вдалося відкрити", show_alert=True)
        return

    await callback_query.answer()


@router.callback_query(F.data == CALLBACK_DATA_EDIT_SRM_BACK_TO_SELECTION)
async def handle_order_links_edit_srm_back_to_selection(callback_query: CallbackQuery) -> None:
    callback_query_message = callback_query.message
    if callback_query_message is None:
        await callback_query.answer("Повідомлення недоступне", show_alert=True)
        return

    order_links_navigation_context = get_order_links_navigation_context_by_message(
        receiver_chat_id=callback_query_message.chat.id,
        order_message_id=callback_query_message.message_id,
    )
    if order_links_navigation_context is None:
        await callback_query.answer("Дані застаріли", show_alert=True)
        return

    clear_pending_order_links_srm_input_for_user(callback_query.from_user.id if callback_query.from_user else None)

    try:
        await callback_query_message.edit_text(
            text=build_order_links_edit_srm_selection_text(order_links_navigation_context),
            parse_mode=None,
            reply_markup=build_order_links_edit_srm_selection_keyboard(order_links_navigation_context),
        )
    except Exception:
        log.exception(
            "failed to return to srm editing selection: chat_id=%s message_id=%s",
            callback_query_message.chat.id,
            callback_query_message.message_id,
        )
        await callback_query.answer("Не вдалося повернутись", show_alert=True)
        return

    await callback_query.answer()


@router.callback_query(F.data.startswith(CALLBACK_DATA_EDIT_SRM_SELECT_PREFIX))
async def handle_order_links_edit_srm_select_link(callback_query: CallbackQuery) -> None:
    callback_query_message = callback_query.message
    if callback_query_message is None:
        await callback_query.answer("Повідомлення недоступне", show_alert=True)
        return

    callback_query_data = callback_query.data or ""
    try:
        sequence_number = int(callback_query_data.split(":")[-1])
    except Exception:
        await callback_query.answer("Некоректний номер", show_alert=True)
        return

    order_links_navigation_context = get_order_links_navigation_context_by_message(
        receiver_chat_id=callback_query_message.chat.id,
        order_message_id=callback_query_message.message_id,
    )
    if order_links_navigation_context is None:
        await callback_query.answer("Дані застаріли", show_alert=True)
        return

    order_links_button_entry = get_order_links_button_entry_by_sequence_number(
        order_links_navigation_context=order_links_navigation_context,
        sequence_number=sequence_number,
    )
    if order_links_button_entry is None:
        await callback_query.answer("Посилання не знайдено", show_alert=True)
        return

    try:
        await callback_query_message.edit_text(
            text=build_order_links_edit_srm_selected_text(order_links_button_entry),
            parse_mode=None,
            reply_markup=build_order_links_edit_srm_selected_keyboard(sequence_number),
        )
    except Exception:
        log.exception(
            "failed to open selected link for srm editing: chat_id=%s message_id=%s sequence=%s",
            callback_query_message.chat.id,
            callback_query_message.message_id,
            sequence_number,
        )
        await callback_query.answer("Не вдалося відкрити", show_alert=True)
        return

    await callback_query.answer()


@router.callback_query(F.data.startswith(CALLBACK_DATA_EDIT_SRM_SET_PREFIX))
async def handle_order_links_edit_srm_set_new_value(callback_query: CallbackQuery) -> None:
    callback_query_message = callback_query.message
    if callback_query_message is None:
        await callback_query.answer("Повідомлення недоступне", show_alert=True)
        return

    callback_query_data = callback_query.data or ""
    try:
        sequence_number = int(callback_query_data.split(":")[-1])
    except Exception:
        await callback_query.answer("Некоректний номер", show_alert=True)
        return

    order_links_navigation_context = get_order_links_navigation_context_by_message(
        receiver_chat_id=callback_query_message.chat.id,
        order_message_id=callback_query_message.message_id,
    )
    if order_links_navigation_context is None:
        await callback_query.answer("Дані застаріли", show_alert=True)
        return

    order_links_button_entry = get_order_links_button_entry_by_sequence_number(
        order_links_navigation_context=order_links_navigation_context,
        sequence_number=sequence_number,
    )
    if order_links_button_entry is None:
        await callback_query.answer("Посилання не знайдено", show_alert=True)
        return

    set_pending_order_links_srm_input_for_user(
        telegram_user_id=callback_query.from_user.id if callback_query.from_user else None,
        receiver_chat_id=callback_query_message.chat.id,
        order_message_id=callback_query_message.message_id,
        sequence_number=sequence_number,
    )

    try:
        await callback_query_message.edit_text(
            text=build_order_links_edit_srm_input_text(order_links_button_entry),
            parse_mode=None,
            reply_markup=build_order_links_edit_srm_input_keyboard(),
        )
    except Exception:
        log.exception(
            "failed to open srm input mode: chat_id=%s message_id=%s sequence=%s",
            callback_query_message.chat.id,
            callback_query_message.message_id,
            sequence_number,
        )
        await callback_query.answer("Не вдалося відкрити", show_alert=True)
        return

    await callback_query.answer("Чекаю новий СРМ")


@router.callback_query(
    lambda callback_query: (callback_query.data or "") == CALLBACK_DATA_SCHEDULE
    or (callback_query.data or "").startswith(CALLBACK_DATA_SCHEDULE_PREFIX)
)
async def handle_order_links_schedule_button(callback_query: CallbackQuery) -> None:
    callback_query_message = callback_query.message
    if callback_query_message is None:
        await callback_query.answer("Повідомлення недоступне", show_alert=True)
        return

    order_links_navigation_context = get_order_links_navigation_context_by_message(
        receiver_chat_id=callback_query_message.chat.id,
        order_message_id=callback_query_message.message_id,
    )
    if order_links_navigation_context is None:
        await callback_query.answer("Дані застаріли", show_alert=True)
        return

    if not order_links_navigation_context.order_links_button_entries:
        await callback_query.answer("Посилання не знайдено", show_alert=True)
        return
    is_added_to_schedule = toggle_order_links_schedule_state(order_links_navigation_context)

    order_text_with_status, order_text_entities = build_order_message_text_with_status(
        order_links_navigation_context
    )

    try:
        await callback_query_message.edit_text(
            text=order_text_with_status,
            parse_mode=None,
            entities=order_text_entities,
            reply_markup=build_order_links_original_keyboard(order_links_navigation_context),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            await callback_query.answer()
            return
        log.exception(
            "failed to toggle order links schedule status: chat_id=%s message_id=%s",
            callback_query_message.chat.id,
            callback_query_message.message_id,
        )
        await callback_query.answer("Не вдалося оновити", show_alert=True)
        return
    except Exception:
        log.exception(
            "failed to toggle order links schedule status: chat_id=%s message_id=%s",
            callback_query_message.chat.id,
            callback_query_message.message_id,
        )
        await callback_query.answer("Не вдалося оновити", show_alert=True)
        return

    if is_added_to_schedule:
        await callback_query.answer("Добавлено в график")
        return
    await callback_query.answer("Убрано из графика")


@router.message(
    lambda message: has_pending_order_links_srm_input_for_user(
        message.from_user.id if message.from_user else None
    )
)
async def handle_order_links_edit_srm_numeric_input(message: Message) -> None:
    telegram_user_id = message.from_user.id if message.from_user else None
    pending_order_links_srm_input_context = get_pending_order_links_srm_input_for_user(telegram_user_id)
    if pending_order_links_srm_input_context is None:
        return

    new_srm_text = (message.text or "").strip()
    if not new_srm_text.isdigit():
        await message.reply("Введи новий СРМ тільки цифрами.")
        return

    order_links_navigation_context = get_order_links_navigation_context_by_message(
        receiver_chat_id=pending_order_links_srm_input_context.receiver_chat_id,
        order_message_id=pending_order_links_srm_input_context.order_message_id,
    )
    if order_links_navigation_context is None:
        clear_pending_order_links_srm_input_for_user(telegram_user_id)
        await message.reply("Дані застаріли, відкрий редагування ще раз.")
        return

    planning_request_id = order_links_navigation_context.planning_request_id
    order_message_keys: list[tuple[int, int]]
    if planning_request_id is None:
        order_message_keys = [
            (
                order_links_navigation_context.receiver_chat_id,
                order_links_navigation_context.order_message_id,
            )
        ]
    else:
        order_message_keys = get_order_message_keys_by_planning_request_id(planning_request_id)
        if not order_message_keys:
            order_message_keys = [
                (
                    order_links_navigation_context.receiver_chat_id,
                    order_links_navigation_context.order_message_id,
                )
            ]

    is_any_order_updated = False
    for receiver_chat_id, order_message_id in order_message_keys:
        target_order_links_navigation_context = get_order_links_navigation_context_by_message(
            receiver_chat_id=receiver_chat_id,
            order_message_id=order_message_id,
        )
        if target_order_links_navigation_context is None:
            continue

        is_updated = update_order_links_button_entry_srm_text(
            order_links_navigation_context=target_order_links_navigation_context,
            sequence_number=pending_order_links_srm_input_context.sequence_number,
            new_srm_text=new_srm_text,
        )
        if not is_updated:
            continue
        is_any_order_updated = True

        order_text_with_status, order_text_entities = build_order_message_text_with_status(
            target_order_links_navigation_context
        )
        try:
            await message.bot.edit_message_text(
                chat_id=receiver_chat_id,
                message_id=order_message_id,
                text=order_text_with_status,
                parse_mode=None,
                entities=order_text_entities,
                reply_markup=build_order_links_original_keyboard(target_order_links_navigation_context),
            )
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                continue
            log.exception(
                "failed to edit order after srm update: chat_id=%s message_id=%s",
                receiver_chat_id,
                order_message_id,
            )
        except Exception:
            log.exception(
                "failed to edit order after srm update: chat_id=%s message_id=%s",
                receiver_chat_id,
                order_message_id,
            )

    clear_pending_order_links_srm_input_for_user(telegram_user_id)
    try:
        await message.delete()
    except Exception:
        pass
    if is_any_order_updated:
        return
    await message.reply("Не вдалося оновити СРМ.")


@router.callback_query(F.data == CALLBACK_DATA_DELETE)
async def handle_order_links_delete_button(callback_query: CallbackQuery) -> None:
    callback_query_message = callback_query.message
    if callback_query_message is None:
        await callback_query.answer("Повідомлення недоступне", show_alert=True)
        return

    order_links_navigation_context = get_order_links_navigation_context_by_message(
        receiver_chat_id=callback_query_message.chat.id,
        order_message_id=callback_query_message.message_id,
    )
    if order_links_navigation_context is None:
        await callback_query.answer("Дані застаріли", show_alert=True)
        return

    planning_request_id = order_links_navigation_context.planning_request_id
    order_message_keys: list[tuple[int, int]]
    if planning_request_id is None:
        order_message_keys = [
            (order_links_navigation_context.receiver_chat_id, order_links_navigation_context.order_message_id)
        ]
    else:
        order_message_keys = get_order_message_keys_by_planning_request_id(planning_request_id)
        if not order_message_keys:
            order_message_keys = [
                (order_links_navigation_context.receiver_chat_id, order_links_navigation_context.order_message_id)
            ]

    deleted_from_database = False
    if planning_request_id is not None:
        try:
            deleted_from_database = delete_planning_request_by_id(planning_request_id)
        except Exception:
            log.exception(
                "failed to delete planning request in database: planning_request_id=%s",
                planning_request_id,
            )
            await callback_query.answer("Не вдалося видалити запис з бази", show_alert=True)
            return

    for receiver_chat_id, order_message_id in order_message_keys:
        try:
            await callback_query_message.bot.delete_message(
                chat_id=receiver_chat_id,
                message_id=order_message_id,
            )
        except TelegramBadRequest as exc:
            error_text = str(exc).lower()
            if "message to delete not found" in error_text:
                continue
            if "message can't be deleted" in error_text:
                continue
            log.exception(
                "failed to delete order message: chat_id=%s message_id=%s",
                receiver_chat_id,
                order_message_id,
            )
        except Exception:
            log.exception(
                "failed to delete order message: chat_id=%s message_id=%s",
                receiver_chat_id,
                order_message_id,
            )

    remove_order_navigation_contexts_by_message_keys(order_message_keys)

    if planning_request_id is None:
        await callback_query.answer("Сообщение удалено")
        return
    if deleted_from_database:
        await callback_query.answer("Запись удалена")
        return
    await callback_query.answer("Сообщения удалены, запись уже отсутствовала")


@router.callback_query(F.data == CALLBACK_DATA_BACK)
async def handle_order_links_back_button(callback_query: CallbackQuery) -> None:
    callback_query_message = callback_query.message
    if callback_query_message is None:
        await callback_query.answer("Повідомлення недоступне", show_alert=True)
        return

    order_links_navigation_context = get_order_links_navigation_context_by_message(
        receiver_chat_id=callback_query_message.chat.id,
        order_message_id=callback_query_message.message_id,
    )
    if order_links_navigation_context is None:
        await callback_query.answer("Дані застаріли", show_alert=True)
        return

    try:
        order_text_with_status, order_text_entities = build_order_message_text_with_status(
            order_links_navigation_context
        )
        await callback_query_message.edit_text(
            text=order_text_with_status,
            parse_mode=None,
            entities=order_text_entities,
            reply_markup=build_order_links_original_keyboard(order_links_navigation_context),
        )
    except Exception:
        log.exception(
            "failed to return from order links details: chat_id=%s message_id=%s",
            callback_query_message.chat.id,
            callback_query_message.message_id,
        )
        await callback_query.answer("Не вдалося повернутись", show_alert=True)
        return

    await callback_query.answer()
