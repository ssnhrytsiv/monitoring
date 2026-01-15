import os
import logging
import asyncio
from math import ceil
from typing import List

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from app.watch_bot.states import JoinChannels
from app.watch_bot.keyboards import main_menu_kb, back_to_menu_kb
from app.watch_bot.processing_guard import is_processing, set_processing
from app.utils.link_parser import sanitize_link

router = Router()
log = logging.getLogger("bot_join_channels")


def _control_chat_id():
    raw = os.getenv("CONTROL_CHAT") or os.getenv("CONTROL_PEER")
    if not raw:
        return None
    try:
        return int(str(raw).strip())
    except Exception:
        return None


def _join_actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 Задати адміністратора",
                    callback_data="join:set_owner"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Скасувати пакет",
                    callback_data="join:cancel_batch"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ В меню",
                    callback_data="menu:home"
                )
            ],
        ]
    )


async def _busy_reply(message: Message):
    await message.answer(
        "Зараз уже йде обробка пакету посилань.\n"
        "Дочекайся завершення підписки, тоді можна буде користуватися ботом далі. 🧑‍🔧"
    )


# --- лінки -------------------------------------------------------------------

import re

_LINK_RE = re.compile(r'(?i)\b((?:https?://|tg://|t\.me/)[^\s<>"\'\]\)]+)')

# той самий fallback‑regex, що й у monitor_links.py
_FALLBACK_TME_RE = re.compile(
    r'(?:(?:https?://)?t\.me/)(?:\+?[A-Za-z0-9_]+)',
    re.IGNORECASE
)


def _unique_preserve(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in items:
        if not x:
            continue
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _collect_links_from_aiogram(src: Message, plain_text: str) -> List[str]:
    """
    Збирає всі t.me/tg:///@username посилання з повідомлення:
      1) entities (text_link / url)
      2) regex по plain-тексту
      3) html_text через link_parser
      4) normalize через sanitize_link + обрізання HTML-хвостів.
    """
    links: List[str] = []

    # 1) entities (text_link / url)
    entities = getattr(src, "entities", None) or getattr(src, "caption_entities", None) or []
    for e in entities:
        try:
            et = getattr(e, "type", None)
            if et == "text_link":
                u = getattr(e, "url", "") or ""
                if u:
                    links.append(u)
            elif et == "url":
                off = int(getattr(e, "offset", 0))
                ln = int(getattr(e, "length", 0))
                piece = plain_text[off:off + ln].strip()
                if piece:
                    links.append(piece)
        except Exception:
            continue

    # 2) "голі" URL у звичайному тексті
    for m_ in _LINK_RE.finditer(plain_text or ""):
        u = m_.group(1)
        if u:
            links.append(u)

    # 3) додатково — парсимо html_text через link_parser (там дістаються приховані t.me)
    html_text = (
        getattr(src, "html_text", None)
        or getattr(src, "text_html", None)
        or getattr(src, "html_caption", None)
        or getattr(src, "caption_html", None)
        or ""
    )
    try:
        from app.utils.link_parser import extract_links_any
        base_text = html_text or plain_text
        extra = extract_links_any(base_text) or []
    except Exception:
        extra = []

    if extra:
        merged: List[str] = list(links)
        for full in extra:
            full_s = str(full).strip()
            if not full_s:
                continue
            if full_s in merged:
                continue
            replaced = False
            # не віддаємо перевагу «довшому» рядку (може містити HTML-хвіст)
            for cur in merged:
                if not cur:
                    continue
                if full_s.startswith(cur) and len(full_s) > len(cur):
                    replaced = True
                    break
            if not replaced:
                merged.append(full_s)
        links = merged

    # 4) нормалізація + відрізання HTML-хвостів
    norm_links: List[str] = []
    for u in links:
        s = str(u).strip()
        if not s:
            continue

        # базова нормалізація (tg://, @user, tps:// → https://t.me/...)
        try:
            s = sanitize_link(s)
        except Exception:
            pass

        # якщо після t.me/... є шмат типу "">Текст</a — обрізаємо його
        low = s.lower()
        tpos = low.find("t.me/")
        if tpos != -1:
            cut = len(s)
            for ch in ('"', '<'):
                idx = s.find(ch, tpos)
                if idx != -1:
                    cut = min(cut, idx)
            if cut != len(s):
                s = s[:cut].rstrip('.,;:)]}>')
                try:
                    s = sanitize_link(s)
                except Exception:
                    pass

        if s:
            norm_links.append(s)

    return _unique_preserve(norm_links)


# --- handlers ----------------------------------------------------------------


@router.callback_query(F.data == "menu:add_join_channels")
async def menu_add_join_channels(cb: CallbackQuery, state: FSMContext):
    user_id = cb.from_user.id
    if is_processing(user_id):
        await _busy_reply(cb.message)
        return

    await state.set_state(JoinChannels.channel_input)
    try:
        await cb.message.edit_text(
            "Надішли повідомлення або пост, який містить канали/інвайти для підписки.\n"
            "Я перешлю його в CONTROL чат, а далі все зробить юзербот (monitor_links).",
            reply_markup=back_to_menu_kb()
        )
    except TelegramBadRequest:
        await cb.message.answer(
            "Надішли повідомлення або пост, який містить канали/інвайти для підписки.\n"
            "Я перешлю його в CONTROL чат, а далі все зробить юзербот (monitor_links).",
            reply_markup=back_to_menu_kb()
        )


@router.message(JoinChannels.channel_input)
async def join_channels_input(m: Message, state: FSMContext):
    user = m.from_user
    user_id = user.id if user else None
    if user_id is not None and is_processing(user_id):
        await _busy_reply(m)
        return

    control_id = _control_chat_id()
    if not control_id:
        await state.clear()
        await m.answer(
            "CONTROL_CHAT/CONTROL_PEER не налаштований у .env.\n"
            "Додай його і перезапусти бота.",
            reply_markup=main_menu_kb()
        )
        return

    try:
        await m.bot.send_message(control_id, "/monitor_links_on")
        await asyncio.sleep(0.3)

        # 1) збираємо всі лінки з повідомлення
        plain_text = m.text or m.caption or ""
        raw_links = _collect_links_from_aiogram(m, plain_text)

        # 2) фільтр під monitor_links: тільки t.me-URL, без дублікатів
        norm_links: List[str] = []
        seen = set()
        for u in raw_links:
            s = str(u).strip()
            if not s:
                continue
            if not _FALLBACK_TME_RE.search(s):
                continue
            if s in seen:
                continue
            seen.add(s)
            norm_links.append(s)

        # 3) будуємо payload ТІЛЬКИ з посилань
        uid_part = f"[BOT_UID:{user_id}]" if user_id is not None else "[BOT_UID:unknown]"
        if norm_links:
            links_block = "\n".join(norm_links)
            payload = uid_part + "\n" + links_block
        else:
            # fallback: якщо лінків не знайшли — хоч щось перешлемо
            payload = uid_part + "\n" + (plain_text or "")

        # 4) зберігаємо список лінків у state (для підрахунку часу)
        await state.update_data(
            raw_join_text=payload,      # тепер це фактичний текст, що пішов у CONTROL
            raw_join_links=norm_links,  # чистий список t.me-URL
        )

        log.info(
            "join_channels.forward_send",
            extra={
                "control_id": control_id,
                "user_id": user_id,
                "links_count": len(norm_links),
                "payload_len": len(payload),
                "raw_links": raw_links,
            },
        )

        await m.bot.send_message(control_id, payload)
        log.info(
            "join_channels.forward",
            extra={
                "user_id": user_id,
                "control_id": control_id,
                "text_len": len(payload),
                "links_count": len(norm_links),
            },
        )
    except Exception as e:
        log.exception("copy_message to control failed: %r", e)
        await state.clear()
        await m.answer(
            "Не вдалося відправити повідомлення в CONTROL чат. Перевір логи.",
            reply_markup=main_menu_kb()
        )
        return

    if user_id is not None:
        # фіксуємо, що для цього юзера йде обробка пакету
        set_processing(user_id, True)

    await state.set_state(JoinChannels.await_action)

    await m.answer(
        "✅ Посилання відправлено в CONTROL чат.\n"
        "Юзербот прийме їх і чекатиме ownerʼа.\n\n"
        "Поки йде підписка, інші дії в боті для тебе тимчасово недоступні.\n\n"
        "Ти можеш:\n"
        "• натиснути «👤 Задати адміністратора» — я попрошу ім’я/@username і відправлю в CONTROL чат команду /owner_set;\n"
        "• натиснути «❌ Скасувати пакет» — я відправлю в CONTROL чат /batch_cancel.\n",
        reply_markup=_join_actions_kb()
    )


@router.callback_query(JoinChannels.await_action, F.data == "join:cancel_batch")
async def join_cancel_batch(cb: CallbackQuery, state: FSMContext):
    user_id = cb.from_user.id
    control_id = _control_chat_id()
    if control_id:
        try:
            await cb.bot.send_message(control_id, "/batch_cancel")
        except Exception as e:
            log.exception("send /batch_cancel failed: %r", e)

    await state.clear()
    set_processing(user_id, False)
    try:
        await cb.message.edit_text(
            "🛑 Пакет скасовано. Повертаюсь у меню.",
            reply_markup=main_menu_kb()
        )
    except TelegramBadRequest:
        await cb.message.answer(
            "🛑 Пакет скасовано. Повертаюсь у меню.",
            reply_markup=main_menu_kb()
        )


@router.callback_query(JoinChannels.await_action, F.data == "join:set_owner")
async def join_set_owner(cb: CallbackQuery, state: FSMContext):
    user_id = cb.from_user.id
    if is_processing(user_id) is False:
        await cb.message.answer(
            "Зараз немає активного пакету для цього чату. Натисни «Додати канали для підписки» ще раз.",
            reply_markup=main_menu_kb()
        )
        await state.clear()
        return

    await state.set_state(JoinChannels.owner_input)
    try:
        await cb.message.edit_text(
            "Введи імʼя або @username адміністратора (без команди).\n"
            "Я відправлю це в CONTROL чат як команду <code>/owner_set ...</code>.",
            reply_markup=back_to_menu_kb()
        )
    except TelegramBadRequest:
        await cb.message.answer(
            "Введи імʼя або @username адміністратора (без команди).\n"
            "Я відправлю це в CONTROL чат як команду <code>/owner_set ...</code>.",
            reply_markup=back_to_menu_kb()
        )


@router.message(JoinChannels.owner_input)
async def join_owner_input(m: Message, state: FSMContext):
    owner = (m.text or "").strip()
    if not owner:
        await m.answer("Введи непорожнє імʼя або @username адміністратора.")
        return

    control_id = _control_chat_id()
    if not control_id:
        await state.clear()
        await m.answer(
            "CONTROL_CHAT/CONTROL_PEER не налаштований у .env.\n"
            "Додай його і перезапусти бота.",
            reply_markup=main_menu_kb()
        )
        return

    # 1) Відправляємо /owner_set
    try:
        await m.bot.send_message(control_id, f"/owner_set {owner}")
    except Exception as e:
        log.exception("send /owner_set failed: %r", e)
        await state.clear()
        await m.answer(
            "Не вдалося відправити /owner_set в CONTROL чат. Перевір логи.",
            reply_markup=main_menu_kb()
        )
        return

    # 2) З невеликою затримкою автоматично вимикаємо monitor_links
    async def _delayed_monitor_off():
        try:
            await asyncio.sleep(2)
            await m.bot.send_message(control_id, "/monitor_links_off")
        except Exception as e:
            log.exception("send /monitor_links_off failed: %r", e)

    try:
        asyncio.create_task(_delayed_monitor_off())
    except RuntimeError:
        m.bot.loop.create_task(_delayed_monitor_off())

    # 3) Беремо список лінків із state і рахуємо їх кількість
    data = await state.get_data()
    links = data.get("raw_join_links") or []
    try:
        links_count = len(links)
    except Exception:
        links_count = 0

    total_seconds = links_count * 40 if links_count > 0 else 60
    minutes = ceil(total_seconds / 60.0)
    if minutes < 1:
        minutes = 1
    wait_text = f"Час очікування: ~{minutes} хв."

    await state.clear()

    msg = await m.answer(
        f"✅ Адміністратора задано як <code>{owner}</code>.\n"
        f"{wait_text}\n"
        "Юзербот у CONTROL чаті продовжить обробку пакету.",
        reply_markup=main_menu_kb()
    )

    user = m.from_user
    user_id = user.id if user else None
    if user_id is not None:
        set_processing(user_id, True, msg_id=msg.message_id)
        try:
            await msg.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
