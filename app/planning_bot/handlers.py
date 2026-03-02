from __future__ import annotations

from dataclasses import dataclass
from aiogram import Router
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    ChosenInlineResult,
    Message,
    MessageEntity,
)
from aiogram import Bot
import re
import logging
import time

from app.admin_bot.utils.messages import extract_links_from_message as admin_extract_links_from_message
from app.DAL.planning_requests_operations import create_planning_request
from app.planning_bot.models import (
    PlanningButton,
    PlanningRequestCreateModel,
    PlanningRequestKindEnum,
    PlanningRequestSourceEnum,
)
from app.planning_bot.config import (
    PLANNING_ADMIN_CHAT_ID,
    PLANNING_ADMIN_CHAT_IDS,
    PLANNING_INLINE_ALLOWED_IDS,
)
from app.planning_bot.order_links_navigation_handlers import (
    router as order_links_navigation_router,
)
from app.planning_bot.services.order_links_navigation_service import (
    attach_links_button_to_recent_order_message,
    has_pending_order_links_srm_input_for_user,
    register_recent_order_message_for_administrator,
)

router = Router(name="planning_bot")
router.include_router(order_links_navigation_router)
log = logging.getLogger("planning_bot.handlers")
BASE_PRICE = 60_000
PENDING_FORWARD_MESSAGE_MAX_AGE_SECONDS = 900


@dataclass
class PendingPostMatchingContext:
    source_chat_id: int | None
    source_message_id: int | None
    source_message_text: str | None
    source_message_entities: list[MessageEntity] | None
    administrator_name: str | None
    thousand_message_price: str | None
    created_at_epoch_seconds: int


pending_post_matching_context_by_user_id: dict[int, PendingPostMatchingContext] = {}


def _current_epoch_seconds() -> int:
    return int(time.time())


def _store_pending_forward_message_for_user(
    telegram_user_id: int | None,
    source_chat_id: int,
    source_message_id: int,
    source_message_text: str,
    source_message_entities: list[MessageEntity] | None,
) -> None:
    if telegram_user_id is None:
        return
    pending_post_matching_context = _get_pending_post_matching_context_for_user(telegram_user_id)
    pending_post_matching_context_by_user_id[telegram_user_id] = PendingPostMatchingContext(
        source_chat_id=source_chat_id,
        source_message_id=source_message_id,
        source_message_text=source_message_text,
        source_message_entities=source_message_entities or None,
        administrator_name=(
            pending_post_matching_context.administrator_name if pending_post_matching_context else None
        ),
        thousand_message_price=(
            pending_post_matching_context.thousand_message_price if pending_post_matching_context else None
        ),
        created_at_epoch_seconds=_current_epoch_seconds(),
    )


def _get_pending_post_matching_context_for_user(
    telegram_user_id: int | None,
) -> PendingPostMatchingContext | None:
    if telegram_user_id is None:
        return None

    pending_post_matching_context = pending_post_matching_context_by_user_id.get(telegram_user_id)
    if pending_post_matching_context is None:
        return None

    age_seconds = _current_epoch_seconds() - pending_post_matching_context.created_at_epoch_seconds
    if age_seconds > PENDING_FORWARD_MESSAGE_MAX_AGE_SECONDS:
        pending_post_matching_context_by_user_id.pop(telegram_user_id, None)
        return None

    return pending_post_matching_context


def _get_pending_forward_message_for_user(
    telegram_user_id: int | None,
) -> PendingPostMatchingContext | None:
    pending_post_matching_context = _get_pending_post_matching_context_for_user(telegram_user_id)
    if pending_post_matching_context is None:
        return None
    if (
        pending_post_matching_context.source_chat_id is None
        or pending_post_matching_context.source_message_id is None
        or pending_post_matching_context.source_message_text is None
    ):
        return None
    return pending_post_matching_context


def _clear_pending_forward_message_for_user(telegram_user_id: int | None) -> None:
    if telegram_user_id is None:
        return
    pending_post_matching_context = _get_pending_post_matching_context_for_user(telegram_user_id)
    if pending_post_matching_context is None:
        return
    if (
        pending_post_matching_context.administrator_name is None
        and pending_post_matching_context.thousand_message_price is None
    ):
        pending_post_matching_context_by_user_id.pop(telegram_user_id, None)
        return
    pending_post_matching_context.source_chat_id = None
    pending_post_matching_context.source_message_id = None
    pending_post_matching_context.source_message_text = None
    pending_post_matching_context.source_message_entities = None
    pending_post_matching_context.created_at_epoch_seconds = _current_epoch_seconds()


def _store_pending_forward_metadata_for_user(
    telegram_user_id: int | None,
    administrator_name: str,
    thousand_message_price: str,
) -> None:
    if telegram_user_id is None:
        return
    pending_post_matching_context = _get_pending_post_matching_context_for_user(telegram_user_id)
    pending_post_matching_context_by_user_id[telegram_user_id] = PendingPostMatchingContext(
        source_chat_id=(
            pending_post_matching_context.source_chat_id if pending_post_matching_context else None
        ),
        source_message_id=(
            pending_post_matching_context.source_message_id if pending_post_matching_context else None
        ),
        source_message_text=(
            pending_post_matching_context.source_message_text if pending_post_matching_context else None
        ),
        source_message_entities=(
            pending_post_matching_context.source_message_entities if pending_post_matching_context else None
        ),
        administrator_name=administrator_name,
        thousand_message_price=thousand_message_price,
        created_at_epoch_seconds=_current_epoch_seconds(),
    )


def _get_pending_forward_metadata_for_user(
    telegram_user_id: int | None,
) -> PendingPostMatchingContext | None:
    pending_post_matching_context = _get_pending_post_matching_context_for_user(telegram_user_id)
    if pending_post_matching_context is None:
        return None
    if (
        pending_post_matching_context.administrator_name is None
        and pending_post_matching_context.thousand_message_price is None
    ):
        return None
    return pending_post_matching_context


def _clear_pending_forward_metadata_for_user(telegram_user_id: int | None) -> None:
    if telegram_user_id is None:
        return
    pending_post_matching_context = _get_pending_post_matching_context_for_user(telegram_user_id)
    if pending_post_matching_context is None:
        return
    if (
        pending_post_matching_context.source_chat_id is None
        and pending_post_matching_context.source_message_id is None
        and pending_post_matching_context.source_message_text is None
    ):
        pending_post_matching_context_by_user_id.pop(telegram_user_id, None)
        return
    pending_post_matching_context.administrator_name = None
    pending_post_matching_context.thousand_message_price = None
    pending_post_matching_context.created_at_epoch_seconds = _current_epoch_seconds()


def _extract_message_id_from_send_result(send_result: object) -> int | None:
    message_id_value = getattr(send_result, "message_id", None)
    if isinstance(message_id_value, int):
        return message_id_value
    return None


def _fmt_money(value: int | float | str) -> str:
    try:
        num = float(value)
        return f"{num:,.0f}".replace(",", " ")
    except Exception:
        return str(value)


def _to_int(value: str):
    """
    Преобразует строку в число. Поддерживает суффикс k/к для тысяч.
    Примеры: '1к' -> 1000, '10k' -> 10000, '23к' -> 23000.
    """
    if value is None:
        return None
    try:
        v = value.strip().lower().replace(" ", "").replace(",", ".")
        if v.endswith("k") or v.endswith("к"):
            num_part = v[:-1] or "0"
            return int(float(num_part) * 1000)
        return int(float(v))
    except Exception:
        return None


def build_menu(buttons: list[PlanningButton]) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text=btn.text, callback_data=btn.callback)]
        for btn in buttons
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _extract_links(text: str) -> list[str]:
    pattern = re.compile(r"(https?://\S+|t\.me/\S+|@\w+)")
    return pattern.findall(text or "")


def _extract_links_from_message(msg: Message) -> list[str]:
    # Використовуємо перевірений парсер із admin_bot (sanitize, entities, @mentions)
    return admin_extract_links_from_message(msg)


def _extract_message_text_and_entities(source_message: Message) -> tuple[str, list[MessageEntity] | None]:
    if source_message.text:
        return source_message.text, source_message.entities
    if source_message.caption:
        return source_message.caption, source_message.caption_entities
    return "", None


def _parse_query(text: str):
    parts = text.split()
    client_tokens: list[str] = []

    def is_price_token(tok: str) -> bool:
        return _to_int(tok) is not None

    # Клієнт може складатися з одного або двох слів, які не схожі на ціну
    while parts and not is_price_token(parts[0]) and len(client_tokens) < 2:
        client_tokens.append(parts.pop(0))

    client = " ".join(client_tokens) if client_tokens else "—"
    price = parts[0] if parts else ""
    count = parts[1] if len(parts) > 1 else ""
    spm = ""
    comment_start_index = 2
    if len(parts) > 2 and parts[2].isdigit():
        spm = parts[2]
        comment_start_index = 3
    comment = " ".join(parts[comment_start_index:]) if len(parts) > comment_start_index else ""
    return client, price, count, spm, comment


def _parse_links_admin_spm(text: str):
    raw_text = text or ""
    urls = _extract_links(raw_text)

    clean_tokens: list[str] = []
    url_tokens_set = {url_value.strip() for url_value in urls}
    for token_value in raw_text.split():
        if token_value.strip() in url_tokens_set:
            continue
        normalized_token_value = token_value.rstrip(".,;|")
        if not normalized_token_value:
            continue
        clean_tokens.append(normalized_token_value)

    if clean_tokens and clean_tokens[0].lower() == "links":
        clean_tokens = clean_tokens[1:]

    spm: str | None = None
    filtered_tokens_without_spm: list[str] = []
    for token_value in clean_tokens:
        if token_value.isdigit():
            spm = token_value
            continue
        filtered_tokens_without_spm.append(token_value)

    admin = " ".join(filtered_tokens_without_spm).strip() if filtered_tokens_without_spm else "—"
    spm_value = spm or "—"

    return urls, admin or "—", spm_value


def _parse_admin_spm_links_reply_command(text: str) -> tuple[str | None, str | None]:
    tokens = (text or "").split()
    if not tokens:
        return None, None
    if tokens[0].lower() != "links":
        return None, None

    extra_tokens = [token_value.strip() for token_value in tokens[1:] if token_value.strip()]
    if not extra_tokens:
        return None, None

    selected_admin, selected_spm = _parse_admin_spm_comment_metadata(" ".join(extra_tokens))
    if selected_admin or selected_spm:
        return selected_admin, selected_spm

    if extra_tokens and extra_tokens[0].lower().startswith("spm="):
        potential_spm = extra_tokens.pop(0).split("=", 1)[1].strip()
        if potential_spm.isdigit():
            selected_spm = potential_spm
        else:
            selected_spm = None
    else:
        selected_spm = None
        if extra_tokens and extra_tokens[0].isdigit():
            selected_spm = extra_tokens.pop(0)
        elif extra_tokens and extra_tokens[-1].isdigit():
            selected_spm = extra_tokens.pop()

    selected_admin = " ".join(extra_tokens).strip() if extra_tokens else None
    return selected_admin or None, selected_spm


def _parse_reply_links_metadata_command(text: str) -> tuple[bool, str | None, str | None]:
    text_value = (text or "").strip()
    if not text_value:
        return False, None, None

    if text_value.lower().startswith("links"):
        selected_admin, selected_spm = _parse_admin_spm_links_reply_command(text_value)
        return True, selected_admin, selected_spm

    selected_admin, selected_spm = _parse_admin_spm_comment_metadata(text_value)
    if selected_admin or selected_spm:
        return True, selected_admin, selected_spm

    token_values = [token_value.strip() for token_value in text_value.split() if token_value.strip()]
    if 2 <= len(token_values) <= 3 and token_values[-1].isdigit():
        selected_admin = " ".join(token_values[:-1]).strip()
        selected_spm = token_values[-1]
        return True, selected_admin or None, selected_spm

    return False, None, None


def _parse_admin_spm_comment_metadata(text: str) -> tuple[str | None, str | None]:
    """
    Витягує admin/spm тільки з явних маркерів у тексті:
      admin: Ім'я
      spm: 500
    """
    text_value = (text or "").strip()
    if not text_value:
        return None, None

    admin_match = re.search(
        r"(?im)\b(?:admin|админ|адмін)\s*[:=]\s*([^\n\r]+?)(?=\s+\b(?:spm|спм)\s*[:=]|\s*$)",
        text_value,
    )
    spm_match = re.search(r"(?im)\b(?:spm|спм)\s*[:=]\s*(\d+)\b", text_value)

    selected_admin = admin_match.group(1).strip() if admin_match else None
    selected_spm = spm_match.group(1).strip() if spm_match else None
    return selected_admin or None, selected_spm or None

def _inline_allowed(user_id: int | None) -> bool:
    return user_id is not None and user_id in PLANNING_INLINE_ALLOWED_IDS


def _resolve_inline_result_kind(result_identifier: str | None) -> PlanningRequestKindEnum:
    if result_identifier == "links_fix":
        return PlanningRequestKindEnum.LINKS_FIX
    return PlanningRequestKindEnum.ORDER


def _persist_planning_request(planning_request_create_model: PlanningRequestCreateModel) -> int | None:
    try:
        created_planning_request = create_planning_request(planning_request_create_model)
        return created_planning_request.id
    except Exception:
        log.exception(
            "failed to persist planning_request: source=%s kind=%s",
            planning_request_create_model.request_source,
            planning_request_create_model.request_kind,
        )
        return None


@router.inline_query()
async def inline_echo(iq: InlineQuery):
    if not _inline_allowed(iq.from_user.id if iq.from_user else None):
        await iq.answer([], cache_time=60, is_personal=True)
        return
    query_text = (iq.query or "").strip()
    # Очікуємо формат: "[клієнт] <ціна> <кількість_постів> [спм] <коментар>"
    client, price, count, spm, comment = _parse_query(query_text)
    links, admin_token_fallback, spm_token_fallback = _parse_links_admin_spm(query_text)
    admin_token_explicit, spm_token_explicit = _parse_admin_spm_comment_metadata(query_text)
    admin_token = admin_token_explicit or admin_token_fallback
    spm_token = spm_token_explicit or spm_token_fallback

    # Публічний текст, який побачить клієнт у чаті після вибору
    public_text = ""
    if price or count:
        public_lines = [f"Цена: {price or '—'}", f"Посты: {count or '—'}"]
        if spm:
            public_lines.append(f"СПМ: {spm}")
        public_text = "\n".join(public_lines)
    else:
        public_text = "Введи: <цена> <к-во постов> [спм] <комментарий>"

    desc_client = client if client != "—" else "клієнт?"
    desc_price = price if price else "цена?"
    desc_count = count if count else "к-во?"
    desc_spm = spm if spm else "спм?"
    dynamic_desc = f"{desc_client} • {desc_price} • {desc_count} • {desc_spm}"

    order_result = InlineQueryResultArticle(
        id="order",  # короткий id, дані беремо з chosen.inline_query.query
        title="Заявка на размещение",
        description=dynamic_desc,
        input_message_content=InputTextMessageContent(
            message_text=f"#забронированно\n{public_text}",
            parse_mode=None,
        ),
    )

    links_desc = f"Ссылки: из reply • СПМ: {spm_token if spm_token else '—'} • Админ: {admin_token if admin_token else '—'}"
    links_command_parts = ["links"]
    if admin_token and admin_token != "—":
        links_command_parts.append(f"admin: {admin_token}")
    if spm_token and spm_token != "—":
        links_command_parts.append(f"spm: {spm_token}")
    links_command_text = " ".join(links_command_parts)
    links_result = InlineQueryResultArticle(
        id="links_fix",
        title="Зафиксировать ссылки",
        description=links_desc,
        input_message_content=InputTextMessageContent(
            message_text=links_command_text,
            parse_mode=None,
        ),
    )

    log.debug(
        "inline_echo query='%s' -> client=%s price=%s count=%s spm=%s comment='%s' links=%s admin=%s links_spm=%s",
        query_text,
        client,
        price,
        count,
        spm,
        comment,
        links,
        admin_token,
        spm_token,
    )
    await iq.answer([order_result, links_result], cache_time=0, is_personal=True)


@router.chosen_inline_result()
async def inline_chosen(chosen: ChosenInlineResult, bot: Bot):
    if not _inline_allowed(chosen.from_user.id if chosen.from_user else None):
        return
    # Логування факту вибору
    log.debug(
        "inline_chosen query='%s' from=%s admin_chat_id=%s",
        (chosen.query or "").strip(),
        chosen.from_user.id if chosen.from_user else None,
        PLANNING_ADMIN_CHAT_ID,
    )

    if not PLANNING_ADMIN_CHAT_IDS:
        log.warning("PLANNING_ADMIN_CHAT_ID is not set; skip sending admin notification")
        return
    # Беремо дані з оригінального запиту користувача
    query_text = (chosen.query or "").strip()
    client, price, count, spm, comment = _parse_query(query_text)
    price = price or "—"
    count = count or "—"
    spm = spm or "—"
    comment = comment or "—"

    links, admin_token, spm_token_for_links = _parse_links_admin_spm(query_text)
    links_text = "\n".join(links) if links else "—"
    admin_token = admin_token or "—"
    spm_token_for_links = spm_token_for_links or "—"

    user = chosen.from_user
    username = user.username if user else None
    first_name = user.first_name if user else None
    last_name = user.last_name if user else None
    user_id = user.id if user else None
    user_repr = (
        f"{first_name or ''} @{username}" if username else (first_name or str(user_id))
    )

    unit_price_int = _to_int(price)
    count_int = _to_int(count)
    unit_price_fmt = _fmt_money(price) if price else "—"
    total_fmt = _fmt_money(unit_price_int * count_int) if unit_price_int is not None and count_int is not None else "—"

    if chosen.result_id == "links_fix":
        log.debug(
            "inline_chosen links_fix selected; waiting for message/reply handler query='%s' user_id=%s",
            query_text,
            user_id,
        )
        return

    selected_result_kind = _resolve_inline_result_kind(chosen.result_id)
    is_links_fix_result = selected_result_kind == PlanningRequestKindEnum.LINKS_FIX

    order_lines_before_links = [
        f"Админ: {client}",
        f"Цена: {unit_price_fmt}",
        f"Кол-во постов: {count}",
        f"СПМ: {spm}",
        f"Общая сумма: {unit_price_fmt} * {count} = {total_fmt}",
        f"Комментарий: {comment}",
    ]
    lines = [*order_lines_before_links, f"Ссылки: {links_text}"]
    text = "\n".join(lines)

    planning_request_create_model = PlanningRequestCreateModel(
        request_source=PlanningRequestSourceEnum.INLINE_CHOSEN,
        request_kind=selected_result_kind,
        source_query_text=query_text or None,
        source_message_text=text,
        source_message_id=None,
        telegram_user_id=user_id,
        telegram_username=username,
        telegram_first_name=first_name,
        telegram_last_name=last_name,
        client_name=None if is_links_fix_result else client,
        administrator_name=admin_token,
        client_reference_number=None,
        price_amount=None if is_links_fix_result else unit_price_int,
        posts_count=None if is_links_fix_result else count_int,
        thousand_message_price=_to_int(spm_token_for_links) if is_links_fix_result else _to_int(spm),
        comment_text=None if is_links_fix_result else comment,
        links=links,
    )
    planning_request_id = _persist_planning_request(planning_request_create_model)

    for admin_id in PLANNING_ADMIN_CHAT_IDS:
        try:
            sent_order_message = await bot.send_message(chat_id=admin_id, text=text)
            register_recent_order_message_for_administrator(
                receiver_chat_id=admin_id,
                order_message_id=_extract_message_id_from_send_result(sent_order_message),
                planning_request_id=planning_request_id,
                administrator_name=client,
                order_message_text=text,
            )
            log.info("Sent planning request to admin chat_id=%s from %s", admin_id, user_repr)
        except Exception as exc:
            log.exception("Failed to send planning request to admin %s: %s", admin_id, exc)


@router.message(
    lambda m: not (
        getattr(m, "forward_origin", None)
        or getattr(m, "forward_date", None)
        or getattr(m, "forward_from", None)
        or getattr(m, "forward_sender_name", None)
        or getattr(m, "reply_to_message", None)
    )
    and not has_pending_order_links_srm_input_for_user(
        m.from_user.id if getattr(m, "from_user", None) else None
    )
)
async def handle_direct_message(message: Message):
    """
    Direct-повідомлення використовуються тільки для метаданих до pending форварду
    (адмін/спм). Створення заявок з довільного direct-тексту вимкнено.
    """
    if not PLANNING_ADMIN_CHAT_IDS:
        log.warning("PLANNING_ADMIN_CHAT_ID is not set; skip direct message handling")
        return

    text_raw = (message.text or "").strip()
    # чекаємо формат: [клієнт] <ціна> <к-сть> [спм] <коментар>
    if text_raw.startswith("@"):
        text_raw = text_raw.split(" ", 1)[1] if " " in text_raw else ""
    if text_raw.lower().startswith("links"):
        return

    user = message.from_user
    username = user.username if user else None
    first_name = user.first_name if user else None
    last_name = user.last_name if user else None
    user_id = user.id if user else None
    user_repr = f"{first_name or ''} @{username}" if username else (first_name or str(user_id))

    pending_forward_message_context = _get_pending_forward_message_for_user(user_id)
    should_process_reply_command, selected_admin, selected_spm = _parse_reply_links_metadata_command(text_raw)
    if should_process_reply_command:
        admin_token = selected_admin or "—"
        spm_token = selected_spm or "—"

        if pending_forward_message_context is None:
            _store_pending_forward_metadata_for_user(
                telegram_user_id=user_id,
                administrator_name=admin_token,
                thousand_message_price=spm_token,
            )
            try:
                await message.reply("Метадані збережено. Тепер перешли повідомлення з посиланнями.")
            except Exception:
                pass
            return

        for admin_id in PLANNING_ADMIN_CHAT_IDS:
            try:
                await attach_links_button_to_recent_order_message(
                    bot=message.bot,
                    receiver_chat_id=admin_id,
                    administrator_name=admin_token,
                    srm_text=spm_token,
                    original_links_message_text=pending_forward_message_context.source_message_text,
                    original_links_message_entities=pending_forward_message_context.source_message_entities,
                )
                log.info(
                    "Pending forward links attached to order in admin chat_id=%s from %s",
                    admin_id,
                    user_repr,
                )
            except Exception as exc:
                log.exception("Failed to attach pending forward links to order in %s: %s", admin_id, exc)

        planning_request_create_model = PlanningRequestCreateModel(
            request_source=PlanningRequestSourceEnum.FORWARD_MESSAGE,
            request_kind=PlanningRequestKindEnum.FORWARD_LINKS,
            source_query_text=text_raw or None,
            source_message_text=pending_forward_message_context.source_message_text or None,
            source_message_id=pending_forward_message_context.source_message_id,
            telegram_user_id=user_id,
            telegram_username=username,
            telegram_first_name=first_name,
            telegram_last_name=last_name,
            client_name=None,
            administrator_name=admin_token,
            client_reference_number=None,
            price_amount=None,
            posts_count=None,
            thousand_message_price=_to_int(spm_token),
            comment_text=None,
            links=[],
        )
        _persist_planning_request(planning_request_create_model)
        _clear_pending_forward_message_for_user(user_id)
        _clear_pending_forward_metadata_for_user(user_id)

        try:
            await message.reply("Сообщение переслано")
        except Exception:
            pass
        return
    return


@router.message(lambda m: bool(m.reply_to_message))
async def handle_links_reply(message: Message):
    """
    Якщо повідомлення починається з 'links' і це reply на інше повідомлення,
    пересилаємо оригінальне reply-повідомлення 1:1 та додаємо метадані (Адмін/СПМ).
    """
    log.debug(
        "reply handler start msg_id=%s reply_msg_id=%s",
        message.message_id,
        message.reply_to_message.message_id if message.reply_to_message else None,
    )
    if not PLANNING_ADMIN_CHAT_IDS:
        return

    text_raw = (message.text or "").strip()
    should_process_reply_command, selected_admin, selected_spm = _parse_reply_links_metadata_command(text_raw)
    if not should_process_reply_command:
        return
    if not message.reply_to_message:
        return

    admin_token = selected_admin or "—"
    spm_token = selected_spm or "—"
    original_links_message_text, original_links_message_entities = _extract_message_text_and_entities(
        message.reply_to_message
    )
    log.debug(
        "reply links metadata: admin_token=%s spm_token=%s",
        admin_token,
        spm_token,
    )

    user = message.from_user
    username = user.username if user else None
    first_name = user.first_name if user else None
    last_name = user.last_name if user else None
    user_id = user.id if user else None
    user_repr = f"{first_name or ''} @{username}" if username else (first_name or str(user_id))

    for admin_id in PLANNING_ADMIN_CHAT_IDS:
        try:
            await attach_links_button_to_recent_order_message(
                bot=message.bot,
                receiver_chat_id=admin_id,
                administrator_name=admin_token,
                srm_text=spm_token,
                original_links_message_text=original_links_message_text,
                original_links_message_entities=original_links_message_entities,
            )
            log.info("Reply links attached to order in admin chat_id=%s from %s", admin_id, user_repr)
        except Exception as exc:
            log.exception("Failed to attach reply links to order in %s: %s", admin_id, exc)

    planning_request_create_model = PlanningRequestCreateModel(
        request_source=PlanningRequestSourceEnum.REPLY_MESSAGE,
        request_kind=PlanningRequestKindEnum.LINKS_REPLY,
        source_query_text=text_raw or None,
        source_message_text=original_links_message_text or None,
        source_message_id=message.message_id,
        telegram_user_id=user_id,
        telegram_username=username,
        telegram_first_name=first_name,
        telegram_last_name=last_name,
        client_name=None,
        administrator_name=admin_token,
        client_reference_number=None,
        price_amount=None,
        posts_count=None,
        thousand_message_price=_to_int(spm_token),
        comment_text=None,
        links=[],
    )
    _persist_planning_request(planning_request_create_model)

    try:
        await message.reply("Сообщение переслано")
    except Exception:
        pass


@router.message(
    lambda m: (
        getattr(m, "forward_origin", None)
        or getattr(m, "forward_date", None)
        or getattr(m, "forward_from", None)
        or getattr(m, "forward_sender_name", None)
    )
)
async def handle_forward_links(message: Message):
    """
    Якщо надіслали боту forward (forward_origin/forward_date),
    пересилаємо оригінальне повідомлення 1:1 та додаємо метадані (Адмін/СПМ).
    """
    if not PLANNING_ADMIN_CHAT_IDS:
        return

    text_raw = (message.text or message.caption or "").strip()
    original_links_message_text, original_links_message_entities = _extract_message_text_and_entities(message)
    log.debug(
        "forward handler start: msg_id=%s forward_origin=%s forward_date=%s text_raw='%s'",
        message.message_id,
        getattr(message, "forward_origin", None),
        getattr(message, "forward_date", None),
        text_raw,
    )
    admin_token, spm_token = _parse_admin_spm_comment_metadata(text_raw)
    if not admin_token and not spm_token:
        forward_sender_user_id = message.from_user.id if message.from_user else None
        pending_forward_metadata_context = _get_pending_forward_metadata_for_user(forward_sender_user_id)
        if pending_forward_metadata_context is not None:
            admin_token = pending_forward_metadata_context.administrator_name
            spm_token = pending_forward_metadata_context.thousand_message_price

    if not admin_token and not spm_token:
        forward_sender_user_id = message.from_user.id if message.from_user else None
        _store_pending_forward_message_for_user(
            telegram_user_id=forward_sender_user_id,
            source_chat_id=message.chat.id,
            source_message_id=message.message_id,
            source_message_text=original_links_message_text,
            source_message_entities=original_links_message_entities,
        )
        instruction_text = (
            "Задай метадані reply-повідомленням на цей форвард:\n"
            "links admin: <Адмін> spm: <СПМ>\n"
            "Або: admin: <Адмін> spm: <СПМ>\n"
            "Або окремим повідомленням: <Адмін> <СПМ>"
        )
        try:
            await message.reply(instruction_text)
        except Exception:
            pass
        log.debug("forward message pending metadata: msg_id=%s", message.message_id)
        return

    admin_token = admin_token or "—"
    spm_token = spm_token or "—"

    user = message.from_user
    username = user.username if user else None
    first_name = user.first_name if user else None
    last_name = user.last_name if user else None
    user_id = user.id if user else None
    user_repr = f"{first_name or ''} @{username}" if username else (first_name or str(user_id))

    log.debug(
        "forward links metadata: admin=%s spm=%s text_raw='%s'",
        admin_token,
        spm_token,
        text_raw,
    )

    for admin_id in PLANNING_ADMIN_CHAT_IDS:
        try:
            await attach_links_button_to_recent_order_message(
                bot=message.bot,
                receiver_chat_id=admin_id,
                administrator_name=admin_token,
                srm_text=spm_token,
                original_links_message_text=original_links_message_text,
                original_links_message_entities=original_links_message_entities,
            )
            log.info("Forward links attached to order in admin chat_id=%s from %s", admin_id, user_repr)
        except Exception as exc:
            log.exception("Failed to attach forward links to order in %s: %s", admin_id, exc)

    planning_request_create_model = PlanningRequestCreateModel(
        request_source=PlanningRequestSourceEnum.FORWARD_MESSAGE,
        request_kind=PlanningRequestKindEnum.FORWARD_LINKS,
        source_query_text=text_raw or None,
        source_message_text=text_raw or None,
        source_message_id=message.message_id,
        telegram_user_id=user_id,
        telegram_username=username,
        telegram_first_name=first_name,
        telegram_last_name=last_name,
        client_name=None,
        administrator_name=admin_token,
        client_reference_number=None,
        price_amount=None,
        posts_count=None,
        thousand_message_price=_to_int(spm_token),
        comment_text=None,
        links=[],
    )
    _persist_planning_request(planning_request_create_model)
    _clear_pending_forward_message_for_user(user_id)
    _clear_pending_forward_metadata_for_user(user_id)

    try:
        await message.reply("Сообщение переслано")
    except Exception:
        pass
