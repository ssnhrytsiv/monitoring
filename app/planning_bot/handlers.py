from __future__ import annotations

from aiogram import Router
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    ChosenInlineResult,
    Message,
)
from aiogram.exceptions import TelegramBadRequest
from aiogram import Bot
import re
import logging

from app.admin_bot.utils.messages import extract_links_from_message as admin_extract_links_from_message
from app.planning_bot.models import PlanningButton
from app.planning_bot.config import (
    PLANNING_ADMIN_CHAT_ID,
    PLANNING_ADMIN_CHAT_IDS,
    PLANNING_INLINE_ALLOWED_IDS,
)

router = Router(name="planning_bot")
log = logging.getLogger("planning_bot.handlers")
BASE_PRICE = 60_000


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
    comment = " ".join(parts[2:]) if len(parts) > 2 else ""
    return client, price, count, comment


def _parse_links_admin_crm(text: str):
    raw_text = text or ""
    urls = _extract_links(raw_text)

    # Беремо токени без URL, прибираємо розділові знаки в кінці
    clean_tokens = []
    for tok in raw_text.split():
        if tok in urls:
            continue
        clean_tokens.append(tok.rstrip(".,;|"))

    admin = crm = "—"
    if clean_tokens:
        admin = clean_tokens[-1]
        if len(clean_tokens) > 1:
            crm = clean_tokens[-2]

    return urls, admin or "—", crm or "—"


def _parse_admin_crm_comment(text: str, urls: list[str]) -> tuple[str | None, str | None]:
    """
    Витягує адміна (1-2 слова) та CRM (цифри) тільки з «коментаря» до повідомлення,
    ігноруючи URL. Зупиняємось, коли зустрічаємо URL.
    """
    tokens = text.split()
    admin_tokens: list[str] = []
    crm_token: str | None = None
    url_set = set(urls or [])

    for tok in tokens:
        if tok in url_set:
            break
        if crm_token is None and tok.isdigit():
            crm_token = tok
            continue
        if len(admin_tokens) < 2 and crm_token is None:
            admin_tokens.append(tok)
            continue
        # якщо вже зібрали адміна і CRM — стоп
        if admin_tokens and crm_token:
            break

    admin_val = " ".join(admin_tokens).strip() if admin_tokens else None
    return admin_val or None, crm_token

def _inline_allowed(user_id: int | None) -> bool:
    return user_id is not None and user_id in PLANNING_INLINE_ALLOWED_IDS


@router.inline_query()
async def inline_echo(iq: InlineQuery):
    if not _inline_allowed(iq.from_user.id if iq.from_user else None):
        await iq.answer([], cache_time=60, is_personal=True)
        return
    query_text = (iq.query or "").strip()
    # Очікуємо формат: "[клієнт] <ціна> <кількість_постів> <коментар>"
    client, price, count, comment = _parse_query(query_text)
    links, admin, crm = _parse_links_admin_crm(query_text)

    # Публічний текст, який побачить клієнт у чаті після вибору
    public_text = ""
    if price or count:
        public_text = f"Цена: {price or '—'}\nПосты: {count or '—'}"
    else:
        public_text = "Введи: <цена> <к-во постов> <комментарий>"

    desc_client = client if client != "—" else "клієнт?"
    desc_price = price if price else "цена?"
    desc_count = count if count else "к-во?"
    dynamic_desc = f"{desc_client} • {desc_price} • {desc_count}"

    order_result = InlineQueryResultArticle(
        id="order",  # короткий id, дані беремо з chosen.inline_query.query
        title="Заявка на размещение",
        description=dynamic_desc,
        input_message_content=InputTextMessageContent(
            message_text=f"#забронированно\n{public_text}",
            parse_mode=None,
        ),
    )

    links_count = len(links)
    links_desc = f"Ссылок: {links_count} • CRM: {crm if crm else '—'} • Админ: {admin if admin else '—'}"
    links_result = InlineQueryResultArticle(
        id="links_fix",
        title="Зафиксировать ссылки",
        description=links_desc,
        input_message_content=InputTextMessageContent(
            message_text="Ссылки зафиксированы",
            parse_mode=None,
        ),
    )

    log.debug(
        "inline_echo query='%s' -> client=%s price=%s count=%s comment='%s' links=%s admin=%s crm=%s",
        query_text,
        client,
        price,
        count,
        comment,
        links,
        admin,
        crm,
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
    client, price, count, comment = _parse_query(query_text)
    price = price or "—"
    count = count or "—"
    comment = comment or "—"

    links, admin_token, crm_token = _parse_links_admin_crm(query_text)
    links_text = "\n".join(links) if links else "—"
    admin_token = admin_token or "—"
    crm_token = crm_token or "—"

    user = chosen.from_user
    username = user.username if user else None
    first_name = user.first_name if user else None
    user_id = user.id if user else None
    user_repr = (
        f"{first_name or ''} @{username}" if username else (first_name or str(user_id))
    )

    unit_price_int = _to_int(price)
    count_int = _to_int(count)
    unit_price_fmt = _fmt_money(price) if price else "—"
    total_fmt = _fmt_money(unit_price_int * count_int) if unit_price_int is not None and count_int is not None else "—"

    if chosen.result_id == "links_fix":
        lines = [
            f"Пользователь: {client}",
            f"Отправитель: {user_repr}",
            f"Админ: {admin_token}",
            f"CRM: {crm_token}",
            "Ссылки:",
            links_text,
        ]
    else:
        lines = [
            f"Пользователь: {client}",
            f"Отправитель: {user_repr}",
            f"Цена: {unit_price_fmt}",
            f"Кол-во постов: {count}",
            f"Общая сумма: {unit_price_fmt} * {count} = {total_fmt}",
            f"Комментарий: {comment}",
            f"Ссылки: {links_text}",
        ]
    text = "\n".join(lines)

    for admin_id in PLANNING_ADMIN_CHAT_IDS:
        try:
            await bot.send_message(chat_id=admin_id, text=text)
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
)
async def handle_direct_message(message: Message):
    """
    Фолбек: якщо користувач просто відправив текст (без натискання на картку),
    парсимо його й шлемо адміну ту саму заявку.
    """
    if not PLANNING_ADMIN_CHAT_IDS:
        log.warning("PLANNING_ADMIN_CHAT_ID is not set; skip direct message handling")
        return

    text_raw = (message.text or "").strip()
    # чекаємо формат: [клієнт] <ціна> <к-сть> <коментар>
    if text_raw.startswith("@"):
        text_raw = text_raw.split(" ", 1)[1] if " " in text_raw else ""

    client, price, count, comment = _parse_query(text_raw)
    price = price or "—"
    count = count or "—"
    comment = comment or "—"
    urls_parsed, admin_token, crm_token = _parse_links_admin_crm(text_raw)
    entity_links = _extract_links_from_message(message)
    # об'єднуємо та унікалізуємо в порядку появи
    links_combined: list[str] = []
    seen = set()
    for l in (urls_parsed or []) + (entity_links or []):
        if not l:
            continue
        if l in seen:
            continue
        seen.add(l)
        links_combined.append(l)
    links_text = "\n".join(links_combined) if links_combined else "—"
    log.debug(
        "direct message links parsed: urls_parsed=%s entity_links=%s combined=%s",
        urls_parsed,
        entity_links,
        links_combined,
    )
    admin_token = admin_token or "—"
    crm_token = crm_token or "—"

    user = message.from_user
    username = user.username if user else None
    first_name = user.first_name if user else None
    user_id = user.id if user else None
    user_repr = f"{first_name or ''} @{username}" if username else (first_name or str(user_id))

    unit_price_int = _to_int(price)
    count_int = _to_int(count)
    unit_price_fmt = _fmt_money(price) if price else "—"
    total_fmt = _fmt_money(unit_price_int * count_int) if unit_price_int is not None and count_int is not None else "—"

    lines = [
        "Новая заявка (direct)",
        f"Пользователь: {client}",
        f"Отправитель: {user_repr}",
        f"Админ: {admin_token}",
        f"CRM: {crm_token}",
        f"Цена: {unit_price_fmt}",
        f"Кол-во постов: {count}",
        f"Общая сумма: {unit_price_fmt} * {count} = {total_fmt}",
        f"Комментарий: {comment}",
        f"Ссылки: {links_text}",
        f"Msg id: {message.message_id}",
    ]
    admin_text = "\n".join(lines)

    for admin_id in PLANNING_ADMIN_CHAT_IDS:
        try:
            await message.bot.send_message(chat_id=admin_id, text=admin_text)
            log.info("Direct request sent to admin chat_id=%s from %s", admin_id, user_repr)
        except Exception as exc:
            log.exception("Failed to send direct planning request to %s: %s", admin_id, exc)


@router.message(lambda m: bool(m.reply_to_message))
async def handle_links_reply(message: Message):
    """
    Якщо повідомлення починається з 'links' і це reply на інше повідомлення,
    то витягуємо всі посилання з реплая (у т.ч. з entities), плюс CRM/Адмін з тексту.
    """
    log.debug(
        "reply handler start msg_id=%s reply_msg_id=%s",
        message.message_id,
        message.reply_to_message.message_id if message.reply_to_message else None,
    )
    if not PLANNING_ADMIN_CHAT_IDS:
        return

    text_raw = (message.text or "").strip()
    tokens = text_raw.split()
    if not tokens or tokens[0].lower() != "links":
        return
    if not message.reply_to_message:
        return

    # CRM/адмін — два останніх не-URL токени, якщо є
    extra_tokens = [t for t in tokens[1:]]  # все після 'links'
    urls_reply = []

    # Витягуємо лінки з реплая: з entities/caption_entities + plain text
    def extract_from_entities(msg: Message):
        links_local = []
        entities = msg.entities or []
        for ent in entities:
            if ent.url:
                links_local.append(ent.url)
            elif ent.type in ("text_link",):
                if ent.url:
                    links_local.append(ent.url)
            else:
                # спробуємо дістати текстовий фрагмент і пошукати в ньому URL
                try:
                    frag = ent.extract_from(msg.text or "")
                    links_local.extend(_extract_links(frag))
                except Exception:
                    continue
        return links_local

    urls_reply.extend(extract_from_entities(message.reply_to_message))
    urls_reply.extend(_extract_links(message.reply_to_message.text or ""))
    urls_reply.extend(_extract_links(message.reply_to_message.caption or ""))

    # crm/admin
    admin_token = crm_token = "—"
    if extra_tokens:
        # відкидаємо url з хвоста
        tail = [t for t in extra_tokens if t not in urls_reply]
        if tail:
            admin_token = tail[-1]
            if len(tail) > 1:
                crm_token = tail[-2]

    # унікалізуємо лінки, зберігаючи порядок
    seen = set()
    uniq_links = []
    for l in urls_reply:
        if l in seen:
            continue
        seen.add(l)
        uniq_links.append(l)

    links_text = "\n".join(f"{idx+1}) {l}" for idx, l in enumerate(uniq_links)) if uniq_links else "—"
    log.debug(
        "reply links parsed: urls=%s uniq=%s admin_token=%s crm_token=%s",
        urls_reply,
        uniq_links,
        admin_token,
        crm_token,
    )

    user = message.from_user
    username = user.username if user else None
    first_name = user.first_name if user else None
    user_id = user.id if user else None
    user_repr = f"{first_name or ''} @{username}" if username else (first_name or str(user_id))

    lines = [
        "Зафиксированные ссылки (reply)",
        f"Отправитель: {user_repr}",
        f"Админ: {admin_token}",
        f"CRM: {crm_token}",
        "Ссылки:",
        links_text,
    ]
    text = "\n".join(lines)

    for admin_id in PLANNING_ADMIN_CHAT_IDS:
        try:
            await message.bot.send_message(chat_id=admin_id, text=text)
            log.info("Reply links sent to admin chat_id=%s from %s", admin_id, user_repr)
        except Exception as exc:
            log.exception("Failed to send reply links to %s: %s", admin_id, exc)
    try:
        await message.reply("Ссылки зафиксированы")
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
    Якщо надіслали боту forward (forward_origin/forward_date), парсимо лінки з нього
    і опціонально беремо CRM/Адмін із тексту форварду.
    """
    if not PLANNING_ADMIN_CHAT_IDS:
        return

    # Декоратор уже відфільтрував не-форварди

    text_raw = (message.text or message.caption or "").strip()
    log.debug(
        "forward handler start: msg_id=%s forward_origin=%s forward_date=%s text_raw='%s'",
        message.message_id,
        getattr(message, "forward_origin", None),
        getattr(message, "forward_date", None),
        text_raw,
    )
    urls = _extract_links_from_message(message)

    # Парсимо адміна/CRM лише з коментаря до форварду (caption/text).
    # Якщо користувач не додав свій текст — не підставляємо нічого (щоб не тягнути «хвости» з оригінального forward).
    comment_text = (message.caption or message.text or "").strip()
    admin_token, crm_token = _parse_admin_crm_comment(comment_text, urls) if comment_text else (None, None)
    admin_token = admin_token or "—"
    crm_token = crm_token or "—"

    user = message.from_user
    username = user.username if user else None
    first_name = user.first_name if user else None
    user_id = user.id if user else None
    user_repr = f"{first_name or ''} @{username}" if username else (first_name or str(user_id))

    log.debug(
        "forward links parsed: urls=%s admin=%s crm=%s text_raw='%s'",
        urls,
        admin_token,
        crm_token,
        text_raw,
    )

    for admin_id in PLANNING_ADMIN_CHAT_IDS:
        try:
            header = f"Админ: {admin_token}\nCRM: {crm_token}"
            await message.bot.send_message(chat_id=admin_id, text=header)
            await message.copy_to(admin_id)
            log.info("Forward message sent to admin chat_id=%s from %s", admin_id, user_repr)
        except Exception as exc:
            log.exception("Failed to send forward links to %s: %s", admin_id, exc)
    try:
        await message.reply("Ссылки зафиксированы")
    except Exception:
        pass
