from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from admin_bot.services import report_cache
from admin_bot.bot.keyboards import main_menu_kb

router = Router()


async def _safe_answer(cb: CallbackQuery, text: str | None = None):
    try:
        await cb.answer(text)
    except TelegramBadRequest as e:
        # Якщо callback прострочений — мовчки ігноруємо, щоб не валити хендлер.
        if "query is too old" in str(e):
            return
        raise


def make_report_kb(page: int, total: int, has_report: bool) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="⬅️", callback_data="report_page_prev"),
            InlineKeyboardButton(text=f"{page+1}/{total}", callback_data="report_page_noop"),
            InlineKeyboardButton(text="➡️", callback_data="report_page_next"),
        ],
        [
            InlineKeyboardButton(text="Отчет", callback_data="report_show_sections"),
        ],
        [
            InlineKeyboardButton(text="В меню", callback_data="report_back_to_menu"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data == "report_page_noop")
async def cb_report_noop(cb: CallbackQuery):
    await _safe_answer(cb)


@router.callback_query(F.data == "report_back_to_menu")
async def cb_report_back_to_menu(cb: CallbackQuery):
    await cb.message.answer(
        "Адмін-бот:\n"
        "• /add_admin — додати себе (або tg_id аргументом)\n"
        "• /admins — список адмінів",
        reply_markup=main_menu_kb()
    )
    await _safe_answer(cb)


@router.callback_query(F.data == "report_show_sections")
async def cb_report_show_sections(cb: CallbackQuery):
    if not cb.message:
        await _safe_answer(cb)
        return
    entry = report_cache.get(cb.message.chat.id, cb.message.message_id)
    if not entry:
        await _safe_answer(cb, "Деталі недоступні.")
        return
    pages = entry.get("pages") or []
    report_idx = entry.get("report_idx")
    if report_idx is None or report_idx >= len(pages):
        await _safe_answer(cb, "Звіт уже на екрані.")
        return
    entry["page"] = report_idx
    kb = make_report_kb(report_idx, len(pages), has_report=True)
    await cb.message.edit_text(pages[report_idx], disable_web_page_preview=True, reply_markup=kb)
    await _safe_answer(cb)


@router.callback_query(F.data.in_(["report_page_prev", "report_page_next"]))
async def cb_report_page_nav(cb: CallbackQuery):
    if not cb.message:
        await _safe_answer(cb)
        return
    entry = report_cache.get(cb.message.chat.id, cb.message.message_id)
    if not entry:
        await _safe_answer(cb, "Деталі недоступні")
        return
    pages = entry.get("pages") or []
    if not pages:
        await _safe_answer(cb)
        return
    cur = entry.get("page", 0)
    total = len(pages)
    if cb.data == "report_page_prev":
        cur = (cur - 1) % total
    else:
        cur = (cur + 1) % total
    entry["page"] = cur
    kb = make_report_kb(cur, total, has_report=entry.get("report_idx") is not None)
    await cb.message.edit_text(pages[cur], disable_web_page_preview=True, reply_markup=kb)
    await _safe_answer(cb)
