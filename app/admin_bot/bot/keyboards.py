from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app.DAL import channel_subscription_audit_operations


def _get_total_missing_channels_count() -> int:
    try:
        return max(
            0,
            int(
                channel_subscription_audit_operations.count_missing_channels_for_all_admins()
            ),
        )
    except Exception:
        return 0


def main_menu_kb() -> InlineKeyboardMarkup:
    total_missing_channel_count = _get_total_missing_channels_count()
    inline_keyboard_rows = [
        [InlineKeyboardButton(text="Адміни", callback_data="show_admins")],
        [InlineKeyboardButton(text="🔁 Дедуп підписок", callback_data="dedup_sessions")],
    ]
    if total_missing_channel_count > 0:
        inline_keyboard_rows.append(
            [
                InlineKeyboardButton(
                    text=f"🔴 Missing к-сть каналів ({total_missing_channel_count})",
                    callback_data="admins_missing_total",
                )
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=inline_keyboard_rows
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
