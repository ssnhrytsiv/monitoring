from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Адміни", callback_data="show_admins")],
        ]
    )


def page_kb(
    page: int,
    total: int,
    *,
    prefix: str = "page",
    menu_cb: str = "back_to_menu",
) -> InlineKeyboardMarkup:
    """
    Клавіатура пагінації: стрілки та центр із номером сторінки, нижче кнопка повернення в меню.
    prefix визначає callback_data для prev/next/noop, menu_cb — callback для кнопки меню.
    """
    page_num = max(1, page + 1)
    total = max(1, total)
    prev_cb = f"{prefix}_prev"
    next_cb = f"{prefix}_next"
    noop_cb = f"{prefix}_noop"

    kb = [
        [
            InlineKeyboardButton(text="⬅️", callback_data=prev_cb),
            InlineKeyboardButton(text=f"{page_num}/{total}", callback_data=noop_cb),
            InlineKeyboardButton(text="➡️", callback_data=next_cb),
        ],
        [InlineKeyboardButton(text="В меню", callback_data=menu_cb)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)
