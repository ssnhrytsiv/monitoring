"""Простий in-memory кеш звітів для навігації між сторінками."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# Ключ: (chat_id, msg_id) -> {"pages": [...], "page": int, "report_idx": Optional[int]}
_CACHE: Dict[Tuple[int, int], Dict] = {}


def register(chat_id: int, msg_id: int, pages: List[str], report_idx: Optional[int]) -> None:
    _CACHE[(chat_id, msg_id)] = {"pages": pages, "page": 0, "report_idx": report_idx}


def get(chat_id: int, msg_id: int) -> Optional[Dict]:
    return _CACHE.get((chat_id, msg_id))


def set_page(chat_id: int, msg_id: int, page: int) -> None:
    key = (chat_id, msg_id)
    if key in _CACHE:
        _CACHE[key]["page"] = page


def pages_count(chat_id: int, msg_id: int) -> int:
    entry = _CACHE.get((chat_id, msg_id))
    if not entry:
        return 0
    return len(entry.get("pages") or [])


__all__ = ["register", "get", "set_page", "pages_count"]
