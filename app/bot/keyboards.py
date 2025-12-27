from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Додати watch", callback_data="menu:add_watch")],
        [InlineKeyboardButton(text="➕ Додати канали для підписки", callback_data="menu:add_join_channels")],
        [InlineKeyboardButton(text="📋 Мої активні watch", callback_data="menu:list_active")],
        [InlineKeyboardButton(text="🧩 Шаблони постів", callback_data="menu:list_templates")],
    ])


def back_to_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")]
    ])


def yes_no_kb(yes_cb: str, no_cb: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Так", callback_data=yes_cb),
            InlineKeyboardButton(text="❌ Ні", callback_data=no_cb),
        ]
    ])


def templates_kb(templates):
    rows = []
    for t in templates:
        tid = t["id"]
        title = t.get("title") or f"Template #{tid}"
        rows.append([InlineKeyboardButton(text=title, callback_data=f"tpl:{tid}")])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def join_channels_result_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Скасувати пакет", callback_data="join:cancel_batch")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")],
    ])
