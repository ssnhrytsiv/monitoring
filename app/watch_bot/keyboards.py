from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Додати watch", callback_data="menu:add_watch")],
        [InlineKeyboardButton(text="➕ Додати watch (сітка)", callback_data="menu:add_watch_net")],
        [InlineKeyboardButton(text="📋 Мої активні watch", callback_data="menu:list_active")],
        [InlineKeyboardButton(text="🧩 Шаблони постів", callback_data="menu:list_templates")],
        [InlineKeyboardButton(text="📑 Управління таблицями", callback_data="menu:sheet_mgmt")],
    ])


def back_to_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")]
    ])


def back_button(callback_data: str, text: str = "⬅️ Back") -> InlineKeyboardButton:
    """Стандартна кнопка повернення."""
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def yes_no_kb(yes_cb: str, no_cb: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Так", callback_data=yes_cb),
            InlineKeyboardButton(text="❌ Ні", callback_data=no_cb),
        ]
    ])


def spacer_button(noop_cb: str = "watch:noop") -> InlineKeyboardButton:
    """Порожня кнопка для симетрії навігації."""
    return InlineKeyboardButton(text=" ", callback_data=noop_cb)


def menu_home_button(text: str = "⬅️ В меню") -> InlineKeyboardButton:
    """Стандартна кнопка повернення у головне меню."""
    return back_button(callback_data="menu:home", text=text)


def build_pager_row(
    current_page: int,
    total_pages: int,
    prev_cb: str | None,
    next_cb: str | None,
    *,
    label: str | None = None,
    noop_cb: str = "watch:noop",
) -> list[InlineKeyboardButton]:
    """
    Стандартний рядок пагінації з prev/label/next. Якщо prev/next немає — ставимо порожню кнопку.
    """
    label_text = label or f"Page {current_page}/{total_pages}"
    row: list[InlineKeyboardButton] = []
    row.append(InlineKeyboardButton(text="⬅️", callback_data=prev_cb) if prev_cb else spacer_button(noop_cb))
    row.append(InlineKeyboardButton(text=label_text, callback_data=noop_cb))
    row.append(InlineKeyboardButton(text="➡️", callback_data=next_cb) if next_cb else spacer_button(noop_cb))
    return row


def pager_callbacks(prefix: str, page: int, total_pages: int) -> tuple[str | None, str | None]:
    """
    Генерує prev/next callback_data для пагінації з префіксом (наприклад, watchnet:page).
    """
    if total_pages <= 0:
        return None, None
    prev_idx = (page - 1) % total_pages
    next_idx = (page + 1) % total_pages
    prev_cb = f"{prefix}:{prev_idx}" if total_pages > 1 else None
    next_cb = f"{prefix}:{next_idx}" if total_pages > 1 else None
    return prev_cb, next_cb


def templates_kb(templates):
    rows = []
    for t in templates:
        tid = t["id"]
        title = t.get("title") or f"Template #{tid}"
        rows.append([InlineKeyboardButton(text=title, callback_data=f"tpl:{tid}")])
    rows.append([back_button(callback_data="menu:home", text="⬅️ В меню")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def join_channels_result_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Скасувати пакет", callback_data="join:cancel_batch")],
        [back_button(callback_data="menu:home", text="⬅️ В меню")],
    ])
