from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from admin_bot.services import report_cache
from admin_bot.bot.keyboards import main_menu_kb

router = Router()


def split_text_for_telegram(text: str, max_len: int = 4000) -> list[str]:
    """Розбиває текст на сторінки під ліміт Telegram (по рядках, щоб не рвати розмітку)."""
    base = text or ""
    if len(base) <= max_len:
        return [base]

    parts: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in base.split("\n"):
        line_len = len(line) + 1  # +1 за перенос
        if current and current_len + line_len > max_len:
            parts.append("\n".join(current).strip())
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len

    if current:
        parts.append("\n".join(current).strip())

    return [p for p in parts if p]


async def _safe_answer(cb: CallbackQuery, text: str | None = None) -> None:
    """Безпечно відповідає на callback (ігнорує 'query is too old')."""
    try:
        await cb.answer(text)
    except TelegramBadRequest as e:
        if "query is too old" in str(e):
            return
        raise


def make_report_kb(page: int, total: int, has_report: bool) -> InlineKeyboardMarkup:
    """Клавіатура навігації по звіту: стрілки + кнопка повернення в меню."""
    buttons = []

    if total > 1:
        buttons.append(
            [
                InlineKeyboardButton(text="⬅️", callback_data="report_page_prev"),
                InlineKeyboardButton(text=f"{page+1}/{total}", callback_data="report_page_noop"),
                InlineKeyboardButton(text="➡️", callback_data="report_page_next"),
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(text="В меню", callback_data="report_back_to_menu"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data == "report_page_noop")
async def cb_report_noop(cb: CallbackQuery) -> None:
    """Нічого не робить, лише закриває callback (noop)."""
    await _safe_answer(cb)


@router.callback_query(F.data == "report_back_to_menu")
async def cb_report_back_to_menu(cb: CallbackQuery):
    """Повертає користувача в головне меню адмін-бота."""
    await cb.message.answer(
        "Адмін-бот:\n"
        "• /add_admin — додати себе (або tg_id аргументом)\n"
        "• /admins — список адмінів",
        reply_markup=main_menu_kb()
    )
    await _safe_answer(cb)


@router.callback_query(F.data.in_(["report_page_prev", "report_page_next"]))
async def cb_report_page_nav(cb: CallbackQuery) -> None:
    """Перемикає сторінки звіту вперед/назад, використовуючи кеш."""
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
    await cb.message.edit_text(
        pages[cur],
        disable_web_page_preview=True,
        reply_markup=kb,
        parse_mode="HTML",
    )
    await _safe_answer(cb)


__all__ = [
    "router",
    "split_text_for_telegram",
    "make_report_kb",
]
