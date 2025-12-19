from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from app.bot import pagination as pager
from app.bot.keyboards import main_menu_kb

router = Router()


@router.callback_query(F.data.startswith("blpage:"))
async def paginate(cb: CallbackQuery):
    """
    Інлайн-пагінація підсумкового списку з batch_links.
    callback_data: blpage:{session_id}:{page_idx}
    """
    parts = (cb.data or "").split(":")
    if len(parts) != 3:
        await cb.answer()
        return

    _, sid, page_raw = parts
    if sid == "noop":
        await cb.answer()
        return

    try:
        page_idx = int(page_raw)
    except Exception:
        await cb.answer("Сторінка невалідна", show_alert=True)
        return

    text = pager.get_page(sid, page_idx, cb.from_user.id if cb.from_user else None)
    total = pager.page_count(sid)
    if text is None or total == 0:
        await cb.answer("Список більше недоступний", show_alert=True)
        return

    kb = pager.build_keyboard(sid, page_idx, total)

    try:
        await cb.message.edit_text(
            text,
            reply_markup=kb,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest:
        await cb.answer("Не вдалося оновити повідомлення", show_alert=True)
        return

    await cb.answer()


@router.callback_query(F.data == "blmenu:home")
async def paginate_menu_home(cb: CallbackQuery):
    """
    Повернення у меню з пагінації підсумку batch_links.
    Не редагуємо існуюче повідомлення, шлемо нове меню.
    """
    await cb.message.answer("Меню:", reply_markup=main_menu_kb())
    try:
        await cb.answer()
    except TelegramBadRequest:
        pass
