from __future__ import annotations

from typing import List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def make_report_keyboard(
    page: int,
    total: int,
    has_report: bool,
    extra_rows: list | None = None,
) -> InlineKeyboardMarkup:
    """
    Клавіатура навігації по звіту: стрілки + кнопка повернення в меню.
    Додатково може містити extra_rows (наприклад, кнопки підтвердження).
    """
    buttons: List[List[InlineKeyboardButton]] = []

    if total > 1:
        buttons.append(
            [
                InlineKeyboardButton(text="⬅️", callback_data="report_page_prev"),
                InlineKeyboardButton(text=f"{page+1}/{total}", callback_data="report_page_noop"),
                InlineKeyboardButton(text="➡️", callback_data="report_page_next"),
            ]
        )

    if extra_rows:
        buttons.extend(extra_rows)

    buttons.append(
        [
            InlineKeyboardButton(text="В меню", callback_data="report_back_to_menu"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_confirm_unsubscribe_rows(batch_id: str) -> list[list[InlineKeyboardButton]]:
    """
    Ряди кнопок підтвердження відписки (Так/Ні) для використання разом з пагінацією.
    """
    return [
        [
            InlineKeyboardButton(text="Так", callback_data=f"refresh_unsub_yes:{batch_id}"),
            InlineKeyboardButton(text="Ні", callback_data=f"refresh_unsub_no:{batch_id}"),
        ]
    ]


def build_confirm_unsubscribe_keyboard(batch_id: str) -> InlineKeyboardMarkup:
    """
    Повна клавіатура підтвердження відписки (без пагінації).
    """
    return InlineKeyboardMarkup(inline_keyboard=build_confirm_unsubscribe_rows(batch_id))

