from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Додати канал/адміна", callback_data="add_admin_flow")],
            [InlineKeyboardButton(text="Адміни", callback_data="show_admins")],
        ]
    )
