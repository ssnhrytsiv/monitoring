import math
from typing import Iterable, Sequence, Any

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app.watch_bot.keyboards import build_pager_row, pager_callbacks, back_button, menu_home_button

ADMINS_PER_ROW = 2
ADMINS_PER_PAGE = 36


def admins_keyboard(admins: Sequence, page: int = 0, pager_prefix: str = "watchnet:page") -> InlineKeyboardMarkup:
    """
    Пагінація списку адмінів (2 в ряд). Очікує, що елемент має id/display/username.
    """
    sorted_admins = sorted(admins, key=lambda a: (getattr(a, "display", None) or getattr(a, "username", None) or f"{getattr(a, 'id', '')}"))
    total_pages = max(1, math.ceil(len(sorted_admins) / ADMINS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))
    start = page * ADMINS_PER_PAGE
    end = start + ADMINS_PER_PAGE
    admins_page = sorted_admins[start:end]

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for a in admins_page:
        label = getattr(a, "display", None) or getattr(a, "username", None) or f"id={getattr(a, 'id', '')}"
        row.append(InlineKeyboardButton(text=label, callback_data=f"watchnet:admin:{getattr(a, 'id', '')}"))
        if len(row) == ADMINS_PER_ROW:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    if total_pages > 1:
        prev_cb, next_cb = pager_callbacks(pager_prefix, page, total_pages)
        label = f"{page + 1}/{total_pages}"
        rows.append(build_pager_row(page + 1, total_pages, prev_cb, next_cb, label=label, noop_cb="noop"))

    rows.append([menu_home_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def networks_keyboard(admin_id: int, networks: Iterable) -> InlineKeyboardMarkup:
    """
    Клавіатура вибору сітки за адміном. Очікує, що елемент має id та name.
    """
    sorted_nets = sorted(networks, key=lambda n: (getattr(n, "name", "") or ""))
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for n in sorted_nets:
        row.append(InlineKeyboardButton(text=getattr(n, "name", ""), callback_data=f"watchnet:net:{admin_id}:{getattr(n, 'id', '')}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([back_button(callback_data="menu:add_watch_net", text="⬅️ Адміни")])
    rows.append([menu_home_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def project_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="ALI", callback_data=f"{prefix}:ALI"),
                InlineKeyboardButton(text="PATRON", callback_data=f"{prefix}:PATRON"),
                InlineKeyboardButton(text="EXPRESS", callback_data=f"{prefix}:EXPRESS"),
            ]
        ]
    )


def sheet_mgmt_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Створити таблицю для цього місяця", callback_data="sheet:create")],
            [InlineKeyboardButton(text="📂 Архівні таблиці", callback_data="sheet:archive")],
            [menu_home_button()],
        ]
    )


def sheet_archive_projects_keyboard(projects: Sequence[str]) -> InlineKeyboardMarkup:
    """
    Клавіатура вибору проєкту для архіву. Елементи — назвами проєктів.
    """
    row = [InlineKeyboardButton(text=p, callback_data=f"sheet:archive_proj:{p}") for p in projects]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            row,
            [menu_home_button()],
        ]
    )


def sheet_archive_empty_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [back_button(callback_data="sheet:archive", text="⬅️ До проєктів")],
            [menu_home_button()],
        ]
    )


def _val(obj: Any, key: str):
    if hasattr(obj, "get"):
        return obj.get(key)
    return getattr(obj, key, None)


def sheet_archive_list_keyboard(project: str, rows: Sequence[Any]) -> InlineKeyboardMarkup:
    """
    Клавіатура архівних таблиць (2 в ряд), кнопки відкривають spreadsheet url.
    """
    rows_sorted = sorted(
        rows,
        key=lambda r: (_val(r, "archived_at") or "", _val(r, "title") or ""),
        reverse=True,
    )

    def _btn_label(title: str) -> str:
        parts = title.strip().split()
        if len(parts) >= 2:
            return " ".join(parts[-2:])
        return title[:32]

    buttons = []
    for r in rows_sorted[:30]:
        title = _val(r, "title") or ""
        url = f"https://docs.google.com/spreadsheets/d/{_val(r, 'spreadsheet_id')}"
        buttons.append(InlineKeyboardButton(text=_btn_label(title), url=url))

    kb_rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(buttons), 2):
        kb_rows.append(buttons[i:i + 2])
    kb_rows.append([back_button(callback_data="sheet:archive", text="⬅️ До проєктів")])
    kb_rows.append([menu_home_button()])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)


def join_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Задати адміністратора", callback_data="join:set_owner")],
            [InlineKeyboardButton(text="❌ Скасувати пакет", callback_data="join:cancel_batch")],
            [menu_home_button()],
        ]
    )


def active_status_picker_keyboard() -> InlineKeyboardMarkup:
    kb_rows = [
        [InlineKeyboardButton(text="Активні", callback_data="menu:list_active:pending")],
        [InlineKeyboardButton(text="Відслідковуються перегляди", callback_data="menu:list_active:matched")],
        [InlineKeyboardButton(text="Вийшли з терміну", callback_data="menu:list_active:expired")],
        [menu_home_button(text="⬅️ Back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)
