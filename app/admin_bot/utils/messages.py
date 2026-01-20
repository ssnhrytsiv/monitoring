from __future__ import annotations

from typing import List

from aiogram.types import Message

from app.utils.link_parser import extract_links_aiogram


def extract_links_from_message(m: Message) -> List[str]:
    """
    Обгортка над загальним парсером з app.utils.link_parser.
    """
    return extract_links_aiogram(m)
