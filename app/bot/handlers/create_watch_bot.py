import logging
import re
from typing import Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from app.bot.states import BotWatch
from app.bot.keyboards import main_menu_kb, back_to_menu_kb, yes_no_kb
from app.services.time_utils import msk_now
from app.utils.tg_links import extract_bot_username
from app.services import bot_watch_db, bot_template_db
from app.utils.tg_links import sanitize_link

router = Router()
log = logging.getLogger("bot_create_watch_bot")


def _try_int(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _is_forward_message(m: Message) -> bool:
    if getattr(m, "forward_origin", None) is not None:
        return True
    if getattr(m, "forward_from_chat", None) is not None:
        return True
    if getattr(m, "forward_from", None) is not None:
        return True
    if getattr(m, "forward_sender_name", None):
        return True
    if getattr(m, "forward_date", None):
        return True
    if getattr(m, "forward_from_message_id", None):
        return True
    if getattr(m, "is_automatic_forward", None):
        return True
    if getattr(m, "is_forward", None):
        return True
    return False


def _first_line_title(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return "bot_template"
    first_line = text.splitlines()[0].strip()
    return first_line[:80] if first_line else text[:80]


async def _create_bot_template_from_source(src: Message) -> Optional[tuple[int, str]]:
    html_text = (
        getattr(src, "html_text", None)
        or getattr(src, "text_html", None)
        or getattr(src, "html_caption", None)
        or getattr(src, "caption_html", None)
    )
    plain_text = (getattr(src, "text", None) or getattr(src, "caption", None) or "").strip()
    base_text = (html_text or plain_text or "").strip()
    if not base_text:
        return None
    # Витягуємо посилання (спрощено)
    links_json = None
    try:
        from app.utils.link_parser import extract_links_any

        links = extract_links_any(base_text) or []
        norm_links = []
        for u in links:
            try:
                norm_links.append(sanitize_link(u))
            except Exception:
                norm_links.append(u)
        import json

        links_json = json.dumps(norm_links, ensure_ascii=False) if norm_links else None
    except Exception:
        links_json = None

    title = _first_line_title(plain_text or base_text)
    try:
        tid = bot_template_db.add_template(text=base_text, title=title, links=links_json)
        return tid, base_text
    except Exception as e:
        log.exception("create_bot_template failed: %s", e)
        return None


@router.callback_query(F.data == "menu:add_bot_watch")
async def menu_add_bot_watch(cb: CallbackQuery, state: FSMContext):
    await state.set_state(BotWatch.bot_input)
    await cb.message.edit_text(
        "Надішли лінк/username бота (t.me/... або @username), якого треба відстежити. "
        "Після цього я попрошу текст очікуваної відповіді.",
        reply_markup=back_to_menu_kb()
    )


@router.message(BotWatch.bot_input)
async def bot_watch_bot_input(m: Message, state: FSMContext):
    raw = (m.text or "").strip()
    username = extract_bot_username(raw)
    if not username:
        await m.answer("Це не схоже на бота (username має закінчуватись на bot/_bot). Надішли інший лінк/username.")
        return
    await state.update_data(bot_username=username)
    await state.set_state(BotWatch.expected_input)
    await m.answer(
        f"Бот: @{username}. Надішли повідомлення від бота (reply/forward або текст), яке очікуєш отримати.",
        reply_markup=back_to_menu_kb()
    )


@router.message(BotWatch.expected_input)
async def bot_watch_expected_input(m: Message, state: FSMContext):
    has_reply = m.reply_to_message is not None

    # 1) Якщо користувач надіслав числовий template_id (і це не форвард/реплай) — пробуємо взяти існуючий шаблон
    direct_text = (m.text or "").strip()
    is_forward = _is_forward_message(m)
    if (not has_reply) and (not is_forward) and direct_text and re.fullmatch(r"\d{1,9}", direct_text):
        tid = _try_int(direct_text)
        tpl_row = bot_template_db.get_template(tid) if tid else None
        if not tpl_row:
            await m.answer("Не знайшов bot-template з таким id. Надішли інший id або повідомлення від бота.")
            return
        text = tpl_row.get("text") or ""
        bot_tpl_id = tid
    else:
        # 2) беремо джерело як у канал-флоу: reply > поточне
        src = m.reply_to_message if has_reply else m
        tpl = await _create_bot_template_from_source(src)
        if not tpl:
            await m.answer(
                "Не зміг створити шаблон бота. Надішли повідомлення/форвард від бота або відповідай на потрібне повідомлення."
            )
            return
        bot_tpl_id, text = tpl

    data = await state.get_data()
    username = data.get("bot_username")
    if not username:
        await m.answer("Не зберіг бота, почни заново.", reply_markup=main_menu_kb())
        await state.clear()
        return

    await state.update_data(expected_html=text, bot_template_id=bot_tpl_id)
    await state.set_state(BotWatch.time_window)
    await m.answer(
        "Вкажи час закінчення вікна СЬОГОДНІ у форматі HH:MM, наприклад 23:30.",
        reply_markup=back_to_menu_kb()
    )


@router.message(BotWatch.time_window)
async def bot_watch_time_window(m: Message, state: FSMContext):
    text = (m.text or "").strip()
    m_time = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text)
    if not m_time:
        await m.answer("Введи час у форматі HH:MM, наприклад 23:30.")
        return

    h = int(m_time.group(1))
    mi = int(m_time.group(2))
    s = int(m_time.group(3) or "0")
    if not (0 <= h <= 23 and 0 <= mi <= 59 and 0 <= s <= 59):
        await m.answer("Невірний час. Приклад: 23:30.")
        return

    now = msk_now()
    tw_end_dt = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if tw_end_dt <= now:
        await m.answer("Час закінчення має бути пізніше за поточний. Вкажи інший час.")
        return

    mins = int((tw_end_dt - now).total_seconds() // 60)
    if mins <= 0:
        await m.answer("Вікно має бути хоча б кілька хвилин. Вкажи інший час.")
        return

    tw_end = tw_end_dt.strftime("%Y-%m-%d %H:%M:%S")
    data = await state.get_data()
    username = data.get("bot_username")
    expected_html = data.get("expected_html") or ""

    preview = expected_html.strip()
    if len(preview) > 500:
        preview = preview[:500] + "…"

    await state.update_data(time_window_end=tw_end, mins=mins)
    await state.set_state(BotWatch.confirm)
    await m.answer(
        (
            "Підтверди створення bot-watch:\n\n"
            f"бот: @{username}\n"
            f"вікно: {mins} хв (до {tw_end})\n"
            f"очікуваний текст:\n{preview}"
        ),
        reply_markup=yes_no_kb("botwatch:confirm_yes", "botwatch:confirm_no"),
        parse_mode=None,
    )


@router.callback_query(BotWatch.confirm, F.data == "botwatch:confirm_no")
async def bot_watch_confirm_no(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Скасовано.", reply_markup=main_menu_kb())


@router.callback_query(BotWatch.confirm, F.data == "botwatch:confirm_yes")
async def bot_watch_confirm_yes(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    username = data.get("bot_username")
    expected_html = data.get("expected_html") or ""
    tw_end = data.get("time_window_end")

    await state.clear()

    if not username or not expected_html:
        await cb.message.edit_text("Не зберіг дані bot-watch, почни заново.", reply_markup=main_menu_kb())
        return

    try:
        wid = bot_watch_db.add_watch(username, expected_html, time_window_end=tw_end)
        log.info(
            "bot_watch created wid=%s bot=%s tpl=%s tw_end=%s",
            wid,
            username,
            data.get("bot_template_id"),
            tw_end,
        )
        await cb.message.edit_text(
            f"Bot-watch створено: @{username}, watch_id={wid}. Меню:",
            reply_markup=main_menu_kb(),
            parse_mode=None,
        )
    except Exception as e:
        log.exception("Failed to add bot_watch: %s", e)
        await cb.message.edit_text("Не зміг створити bot-watch, спробуй ще раз.", reply_markup=main_menu_kb())
