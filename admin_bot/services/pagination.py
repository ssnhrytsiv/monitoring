from __future__ import annotations

import math
from typing import List, Tuple

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def chunk_items(items: List[str], per_page: int) -> List[List[str]]:
    return [items[i:i + per_page] for i in range(0, len(items), per_page)]


def page_kb(page: int, total: int, prefix: str, menu_cb: str = "report_back_to_menu") -> InlineKeyboardMarkup:
    prev_cb = f"{prefix}_prev"
    next_cb = f"{prefix}_next"
    noop_cb = f"{prefix}_noop"
    to_menu = InlineKeyboardButton(text="В меню", callback_data=menu_cb)
    rows = [
        [
            InlineKeyboardButton(text="⬅️", callback_data=prev_cb),
            InlineKeyboardButton(text=f"{page+1}/{total}", callback_data=noop_cb),
            InlineKeyboardButton(text="➡️", callback_data=next_cb),
        ],
        [to_menu],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def buttons_page(all_items: List[str], page: int, per_page: int, prefix: str) -> InlineKeyboardMarkup:
    """
    Рендерить кнопки для одного пейджа списку.
    callback_data: f"{prefix}_item_{global_idx}"
    """
    total = max(1, math.ceil(len(all_items) / per_page))
    page = max(0, min(page, total - 1))
    start = page * per_page
    items = all_items[start:start + per_page]
    buttons = []
    for idx, label in enumerate(items):
        global_idx = start + idx
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"{prefix}_item_{global_idx}")])
    # Пагінація + меню внизу
    nav = page_kb(page, total, prefix)
    return InlineKeyboardMarkup(inline_keyboard=buttons + nav.inline_keyboard)
