from __future__ import annotations

import time
import uuid
from typing import Dict, List, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class _Session:
    __slots__ = ("pages", "user_id", "created_at", "labels")

    def __init__(self, pages: List[str], user_id: Optional[int], labels: Optional[List[str]] = None) -> None:
        self.pages = pages
        self.user_id = user_id
        self.created_at = time.time()
        self.labels = labels or []


_STORE: Dict[str, _Session] = {}
_TTL_SEC = 3600  # простий час життя сесії пагінації (очищаємо лінивим способом)


def _cleanup() -> None:
    now = time.time()
    expired = [sid for sid, data in _STORE.items() if now - data.created_at > _TTL_SEC]
    for sid in expired:
        _STORE.pop(sid, None)


def create_session(pages: List[str], user_id: Optional[int], labels: Optional[List[str]] = None) -> str:
    """
    Зберігає сторінки для інлайн-пагінації. Повертає session_id для callback_data.
    """
    _cleanup()
    sid = uuid.uuid4().hex
    _STORE[sid] = _Session(pages, user_id, labels)
    return sid


def get_page(sid: str, idx: int, user_id: Optional[int]) -> Optional[str]:
    data = _STORE.get(sid)
    if not data:
        return None
    if data.user_id and user_id and data.user_id != user_id:
        return None
    if idx < 0 or idx >= len(data.pages):
        return None
    # оновлюємо час для м'якого продовження життя
    data.created_at = time.time()
    return data.pages[idx]


def page_count(sid: str) -> int:
    data = _STORE.get(sid)
    return len(data.pages) if data else 0


def build_keyboard(sid: str, idx: int, total: int) -> Optional[InlineKeyboardMarkup]:
    if total <= 1:
        return None

    session = _STORE.get(sid)
    labels = getattr(session, "labels", []) if session else []

    buttons: List[InlineKeyboardButton] = []
    if idx > 0:
        buttons.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"blpage:{sid}:{idx-1}")
        )
    buttons.append(
        InlineKeyboardButton(text=f"{idx+1}/{total}", callback_data="blpage:noop")
    )
    if idx + 1 < total:
        buttons.append(
            InlineKeyboardButton(text="Вперед ➡️", callback_data=f"blpage:{sid}:{idx+1}")
        )

    rows: List[List[InlineKeyboardButton]] = [buttons]

    # Кнопки швидкого переходу до секцій (категорій), якщо задано labels у сесії.
    cat_btns: List[InlineKeyboardButton] = []
    for i, label in enumerate(labels):
        if not label:
            continue
        if i == 0:
            continue  # головна сторінка і так показана
        cat_btns.append(InlineKeyboardButton(text=label, callback_data=f"blpage:{sid}:{i}"))
    if cat_btns:
        # розбиваємо по 2 в рядок, щоб не розтягувати клавіатуру
        for start in range(0, len(cat_btns), 2):
            rows.append(cat_btns[start:start+2])

    # Додаємо рядок з поверненням у меню
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")])

    return InlineKeyboardMarkup(inline_keyboard=rows)
