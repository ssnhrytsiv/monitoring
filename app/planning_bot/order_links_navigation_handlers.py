from __future__ import annotations

import html
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from app.DAL.planning_requests_operations import (
    delete_planning_request_by_id,
    get_planning_request_by_id,
)
from app.DAL.planning_network_selection_operations import (
    get_network_selection_record_for_admin,
    list_network_channel_subscription_audit_record_list,
    list_network_selection_records_for_admin,
    resolve_admin_identifier_by_administrator_name,
)
from app.services import account_pool
from app.planning_bot.services.order_links_navigation_service import (
    CALLBACK_DATA_BACK,
    CALLBACK_DATA_CHECK_NETWORK,
    CALLBACK_DATA_CHECK_NETWORK_RUN,
    CALLBACK_DATA_CHECK_NETWORK_SELECT_PREFIX,
    CALLBACK_DATA_DELETE,
    CALLBACK_DATA_EDIT_SRM,
    CALLBACK_DATA_EDIT_SRM_BACK_TO_SELECTION,
    CALLBACK_DATA_EDIT_SRM_SELECT_PREFIX,
    CALLBACK_DATA_EDIT_SRM_SET_PREFIX,
    CALLBACK_DATA_MANAGE_CARD,
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
    build_order_links_check_network_selection_keyboard,
    build_order_links_check_network_selection_text,
    build_order_links_manage_card_keyboard,
    build_order_message_text_with_status,
    build_order_links_original_keyboard,
    clear_pending_order_links_srm_input_for_user,
    get_order_links_button_entry_by_sequence_number,
    get_order_message_keys_by_planning_request_id,
    get_pending_order_links_srm_input_for_user,
    get_selected_network_identifier_for_order_message,
    get_order_links_navigation_context_by_message,
    has_pending_order_links_srm_input_for_user,
    remove_order_navigation_contexts_by_message_keys,
    set_pending_order_links_srm_input_for_user,
    set_selected_network_identifier_for_order_message,
    toggle_order_links_schedule_state,
    update_order_links_button_entry_srm_text,
)


router = Router(name="planning_order_links_navigation")
log = logging.getLogger("planning_bot.order_links_navigation")


def _format_audit_datetime(timestamp_seconds: int | None) -> str:
    if timestamp_seconds is None:
        return "—"
    try:
        return datetime.fromtimestamp(int(timestamp_seconds)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "—"


def _build_network_subscription_check_report_text(
    administrator_name: str,
    network_name: str,
    network_channel_subscription_audit_record_list: list[dict[str, object]],
    failed_session_name_list: list[str],
) -> str:
    total_channel_count = len(network_channel_subscription_audit_record_list)
    missing_channel_record_list = [
        network_channel_subscription_audit_record
        for network_channel_subscription_audit_record in network_channel_subscription_audit_record_list
        if str(
            network_channel_subscription_audit_record.get("audit_status") or ""
        ).lower()
        == "missing"
    ]
    unknown_channel_record_list = [
        network_channel_subscription_audit_record
        for network_channel_subscription_audit_record in network_channel_subscription_audit_record_list
        if str(
            network_channel_subscription_audit_record.get("audit_status") or ""
        ).lower()
        in {"unknown", ""}
    ]

    report_line_list: list[str] = [
        "<b>Перевірка сітки завершена</b>",
        f"Адмін: <b>{html.escape(str(administrator_name or '—'))}</b>",
        f"Сітка: <b>{html.escape(str(network_name or '—'))}</b>",
        (
            "Каналів: "
            f"{total_channel_count} "
            f"(missing: {len(missing_channel_record_list)}, unknown: {len(unknown_channel_record_list)})"
        ),
    ]
    if failed_session_name_list:
        report_line_list.append(
            "Сканування з помилками сесій: "
            + ", ".join(html.escape(str(session_name)) for session_name in failed_session_name_list)
        )

    if not network_channel_subscription_audit_record_list:
        report_line_list.append("У вибраній сітці немає каналів.")
        return "\n".join(report_line_list)

    report_line_list.append("")
    report_line_list.append("Канали:")

    maximum_text_length = 3900
    for channel_record_index, network_channel_subscription_audit_record in enumerate(
        network_channel_subscription_audit_record_list
    ):
        channel_label = html.escape(
            str(
                network_channel_subscription_audit_record.get("channel_label")
                or network_channel_subscription_audit_record.get("channel_id")
                or "—"
            )
        )
        channel_url = str(network_channel_subscription_audit_record.get("channel_url") or "").strip()
        channel_label_with_hyperlink = channel_label
        if channel_url:
            channel_label_with_hyperlink = (
                f'<a href="{html.escape(channel_url)}">{channel_label}</a>'
            )

        audit_status = str(network_channel_subscription_audit_record.get("audit_status") or "").lower()
        checked_at_value = _format_audit_datetime(
            network_channel_subscription_audit_record.get("checked_at")
            if network_channel_subscription_audit_record.get("checked_at") is not None
            else None
        )
        missing_detected_at_value = _format_audit_datetime(
            network_channel_subscription_audit_record.get("missing_detected_at")
            if network_channel_subscription_audit_record.get("missing_detected_at") is not None
            else None
        )

        if audit_status == "missing":
            channel_report_line = (
                f"• {channel_label_with_hyperlink} — <b>Нужна ссылка на этот канал ❗</b>\n"
                f"  Missing з: <code>{missing_detected_at_value}</code>\n"
                f"  Перевірено: <code>{checked_at_value}</code>"
            )
        elif audit_status in {"unknown", ""}:
            channel_report_line = (
                f"• {channel_label_with_hyperlink} — <b>Статус невідомий</b>\n"
                f"  Перевірено: <code>{checked_at_value}</code>"
            )
        else:
            channel_report_line = f"• {channel_label_with_hyperlink}"

        projected_text = "\n".join([*report_line_list, channel_report_line])
        if len(projected_text) > maximum_text_length:
            hidden_channel_count = total_channel_count - channel_record_index
            if hidden_channel_count > 0:
                report_line_list.append(
                    f"... ще {hidden_channel_count} канал(ів), скороти вибір для детального перегляду."
                )
            break
        report_line_list.append(channel_report_line)

    return "\n".join(report_line_list)


def _resolve_admin_identifier_for_order_message(
    administrator_name: str,
    planning_request_id: int | None,
) -> int | None:
    administrator_name_candidates: list[str] = []
    normalized_administrator_name_from_context = " ".join(
        str(administrator_name or "").split()
    ).strip()
    if normalized_administrator_name_from_context:
        administrator_name_candidates.append(normalized_administrator_name_from_context)

    if planning_request_id is not None:
        try:
            planning_request_view_model = get_planning_request_by_id(planning_request_id)
        except Exception:
            log.exception(
                "failed to load planning request for admin resolve: planning_request_id=%s",
                planning_request_id,
            )
            planning_request_view_model = None
        if planning_request_view_model is not None:
            normalized_administrator_name_from_planning_request = " ".join(
                str(planning_request_view_model.administrator_name or "").split()
            ).strip()
            if (
                normalized_administrator_name_from_planning_request
                and normalized_administrator_name_from_planning_request
                not in administrator_name_candidates
            ):
                administrator_name_candidates.append(
                    normalized_administrator_name_from_planning_request
                )

    for administrator_name_candidate in administrator_name_candidates:
        try:
            administrator_identifier = resolve_admin_identifier_by_administrator_name(
                administrator_name_candidate
            )
        except Exception:
            log.exception(
                "failed to resolve admin by administrator_name=%s",
                administrator_name_candidate,
            )
            continue
        if administrator_identifier is not None:
            return administrator_identifier

    return None


@router.callback_query(F.data == CALLBACK_DATA_MANAGE_CARD)
async def handle_order_links_manage_card_button(callback_query: CallbackQuery) -> None:
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

    order_text_with_status, order_text_entities = build_order_message_text_with_status(
        order_links_navigation_context
    )
    try:
        await callback_query_message.edit_text(
            text=order_text_with_status,
            parse_mode=None,
            entities=order_text_entities,
            reply_markup=build_order_links_manage_card_keyboard(),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            await callback_query.answer()
            return
        log.exception(
            "failed to open order links manage card view: chat_id=%s message_id=%s",
            callback_query_message.chat.id,
            callback_query_message.message_id,
        )
        await callback_query.answer("Не вдалося відкрити", show_alert=True)
        return
    except Exception:
        log.exception(
            "failed to open order links manage card view: chat_id=%s message_id=%s",
            callback_query_message.chat.id,
            callback_query_message.message_id,
        )
        await callback_query.answer("Не вдалося відкрити", show_alert=True)
        return

    await callback_query.answer()


@router.callback_query(F.data == CALLBACK_DATA_CHECK_NETWORK)
async def handle_order_links_check_network_button(callback_query: CallbackQuery) -> None:
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

    admin_identifier = _resolve_admin_identifier_for_order_message(
        order_links_navigation_context.administrator_name,
        order_links_navigation_context.planning_request_id,
    )
    if admin_identifier is None:
        await callback_query.answer("Адміна не знайдено", show_alert=True)
        return

    try:
        network_selection_record_list = list_network_selection_records_for_admin(
            admin_identifier=admin_identifier
        )
    except Exception:
        log.exception(
            "failed to list networks for admin_identifier=%s",
            admin_identifier,
        )
        await callback_query.answer("Не вдалося завантажити сітки", show_alert=True)
        return

    if not network_selection_record_list:
        await callback_query.answer("У адміна немає сіток", show_alert=True)
        return

    selected_network_identifier = get_selected_network_identifier_for_order_message(
        receiver_chat_id=callback_query_message.chat.id,
        order_message_id=callback_query_message.message_id,
    )
    if selected_network_identifier is None:
        selected_network_identifier = int(
            network_selection_record_list[0].get("network_id") or 0
        )
        if selected_network_identifier:
            set_selected_network_identifier_for_order_message(
                receiver_chat_id=callback_query_message.chat.id,
                order_message_id=callback_query_message.message_id,
                network_identifier=selected_network_identifier,
            )

    try:
        await callback_query_message.edit_text(
            text=build_order_links_check_network_selection_text(
                administrator_name=order_links_navigation_context.administrator_name,
                network_selection_record_list=network_selection_record_list,
                selected_network_identifier=selected_network_identifier,
            ),
            parse_mode=None,
            reply_markup=build_order_links_check_network_selection_keyboard(
                network_selection_record_list=network_selection_record_list,
                selected_network_identifier=selected_network_identifier,
            ),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            await callback_query.answer()
            return
        log.exception(
            "failed to open network selection for check: chat_id=%s message_id=%s",
            callback_query_message.chat.id,
            callback_query_message.message_id,
        )
        await callback_query.answer("Не вдалося відкрити", show_alert=True)
        return
    except Exception:
        log.exception(
            "failed to open network selection for check: chat_id=%s message_id=%s",
            callback_query_message.chat.id,
            callback_query_message.message_id,
        )
        await callback_query.answer("Не вдалося відкрити", show_alert=True)
        return

    await callback_query.answer()


@router.callback_query(F.data.startswith(CALLBACK_DATA_CHECK_NETWORK_SELECT_PREFIX))
async def handle_order_links_check_network_select_button(
    callback_query: CallbackQuery,
) -> None:
    callback_query_message = callback_query.message
    if callback_query_message is None:
        await callback_query.answer("Повідомлення недоступне", show_alert=True)
        return

    callback_query_data = callback_query.data or ""
    try:
        selected_network_identifier = int(callback_query_data.split(":")[-1])
    except Exception:
        await callback_query.answer("Некоректна сітка", show_alert=True)
        return

    order_links_navigation_context = get_order_links_navigation_context_by_message(
        receiver_chat_id=callback_query_message.chat.id,
        order_message_id=callback_query_message.message_id,
    )
    if order_links_navigation_context is None:
        await callback_query.answer("Дані застаріли", show_alert=True)
        return

    admin_identifier = _resolve_admin_identifier_for_order_message(
        order_links_navigation_context.administrator_name,
        order_links_navigation_context.planning_request_id,
    )
    if admin_identifier is None:
        await callback_query.answer("Адміна не знайдено", show_alert=True)
        return

    selected_network_record = get_network_selection_record_for_admin(
        admin_identifier=admin_identifier,
        network_identifier=selected_network_identifier,
    )
    if selected_network_record is None:
        await callback_query.answer("Сітка не знайдена", show_alert=True)
        return

    try:
        network_selection_record_list = list_network_selection_records_for_admin(
            admin_identifier=admin_identifier
        )
    except Exception:
        log.exception(
            "failed to reload networks for admin_identifier=%s",
            admin_identifier,
        )
        await callback_query.answer("Не вдалося оновити список сіток", show_alert=True)
        return

    set_selected_network_identifier_for_order_message(
        receiver_chat_id=callback_query_message.chat.id,
        order_message_id=callback_query_message.message_id,
        network_identifier=selected_network_identifier,
    )

    try:
        await callback_query_message.edit_text(
            text=build_order_links_check_network_selection_text(
                administrator_name=order_links_navigation_context.administrator_name,
                network_selection_record_list=network_selection_record_list,
                selected_network_identifier=selected_network_identifier,
            ),
            parse_mode=None,
            reply_markup=build_order_links_check_network_selection_keyboard(
                network_selection_record_list=network_selection_record_list,
                selected_network_identifier=selected_network_identifier,
            ),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            await callback_query.answer()
            return
        log.exception(
            "failed to set selected network for check: chat_id=%s message_id=%s network_id=%s",
            callback_query_message.chat.id,
            callback_query_message.message_id,
            selected_network_identifier,
        )
        await callback_query.answer("Не вдалося вибрати сітку", show_alert=True)
        return
    except Exception:
        log.exception(
            "failed to set selected network for check: chat_id=%s message_id=%s network_id=%s",
            callback_query_message.chat.id,
            callback_query_message.message_id,
            selected_network_identifier,
        )
        await callback_query.answer("Не вдалося вибрати сітку", show_alert=True)
        return

    selected_network_name = str(
        selected_network_record.get("network_name") or selected_network_identifier
    )
    await callback_query.answer(f"Обрана сітка: {selected_network_name}")


@router.callback_query(F.data == CALLBACK_DATA_CHECK_NETWORK_RUN)
async def handle_order_links_check_network_run_button(callback_query: CallbackQuery) -> None:
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

    admin_identifier = _resolve_admin_identifier_for_order_message(
        order_links_navigation_context.administrator_name,
        order_links_navigation_context.planning_request_id,
    )
    if admin_identifier is None:
        await callback_query.answer("Адміна не знайдено", show_alert=True)
        return

    try:
        network_selection_record_list = list_network_selection_records_for_admin(
            admin_identifier=admin_identifier
        )
    except Exception:
        log.exception(
            "failed to load network list before run check: admin_identifier=%s",
            admin_identifier,
        )
        await callback_query.answer("Не вдалося завантажити сітки", show_alert=True)
        return
    if not network_selection_record_list:
        await callback_query.answer("У адміна немає сіток", show_alert=True)
        return

    selected_network_identifier = get_selected_network_identifier_for_order_message(
        receiver_chat_id=callback_query_message.chat.id,
        order_message_id=callback_query_message.message_id,
    )
    if selected_network_identifier is None:
        selected_network_identifier = int(
            network_selection_record_list[0].get("network_id") or 0
        )
        if selected_network_identifier:
            set_selected_network_identifier_for_order_message(
                receiver_chat_id=callback_query_message.chat.id,
                order_message_id=callback_query_message.message_id,
                network_identifier=selected_network_identifier,
            )
    if selected_network_identifier is None:
        await callback_query.answer("Обери сітку для перевірки", show_alert=True)
        return

    selected_network_record = get_network_selection_record_for_admin(
        admin_identifier=admin_identifier,
        network_identifier=selected_network_identifier,
    )
    if selected_network_record is None:
        await callback_query.answer("Сітка не знайдена", show_alert=True)
        return

    if account_pool.is_subscription_audit_refresh_running():
        await callback_query.answer(
            "Перевірка вже виконується, спробуй трохи пізніше.",
            show_alert=True,
        )
        return

    seconds_until_next_allowed = (
        account_pool.get_subscription_audit_refresh_seconds_until_next_allowed()
    )
    if seconds_until_next_allowed > 0:
        await callback_query.answer(
            f"Нова перевірка буде доступна через {seconds_until_next_allowed} с.",
            show_alert=True,
        )
        return

    await callback_query.answer("Запускаю перевірку сітки...")
    try:
        channel_subscription_audit_refresh_result = (
            await account_pool.refresh_channel_subscription_audit_snapshot_now(
                audit_reason="planning_network_check"
            )
        )
    except Exception:
        log.exception(
            "failed to refresh channel subscription audit before network check: network_identifier=%s",
            selected_network_identifier,
        )
        channel_subscription_audit_refresh_result = {
            "failed_session_name_list": [],
        }
    if bool(
        channel_subscription_audit_refresh_result.get(
            "is_skipped_due_to_running_refresh"
        )
    ):
        return
    if bool(
        channel_subscription_audit_refresh_result.get(
            "is_skipped_due_to_cooldown"
        )
    ):
        return

    try:
        network_channel_subscription_audit_record_list = (
            list_network_channel_subscription_audit_record_list(
                network_identifier=selected_network_identifier
            )
        )
    except Exception:
        log.exception(
            "failed to load network channel audit records: network_identifier=%s",
            selected_network_identifier,
        )
        await callback_query.answer("Не вдалося сформувати звіт", show_alert=True)
        return

    failed_session_name_list = [
        str(session_name).strip()
        for session_name in (
            channel_subscription_audit_refresh_result.get("failed_session_name_list", [])
            if isinstance(channel_subscription_audit_refresh_result, dict)
            else []
        )
        if str(session_name).strip()
    ]
    report_text = _build_network_subscription_check_report_text(
        administrator_name=order_links_navigation_context.administrator_name,
        network_name=str(selected_network_record.get("network_name") or "—"),
        network_channel_subscription_audit_record_list=network_channel_subscription_audit_record_list,
        failed_session_name_list=failed_session_name_list,
    )
    try:
        await callback_query_message.edit_text(
            text=report_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=build_order_links_check_network_selection_keyboard(
                network_selection_record_list=network_selection_record_list,
                selected_network_identifier=selected_network_identifier,
            ),
        )
    except TelegramBadRequest as exception:
        if "message is not modified" in str(exception):
            return
        log.exception(
            "failed to edit message with network check report: chat_id=%s message_id=%s network_identifier=%s",
            callback_query_message.chat.id,
            callback_query_message.message_id,
            selected_network_identifier,
        )
        return
    except Exception:
        log.exception(
            "failed to edit message with network check report: chat_id=%s message_id=%s network_identifier=%s",
            callback_query_message.chat.id,
            callback_query_message.message_id,
            selected_network_identifier,
        )
        return


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
