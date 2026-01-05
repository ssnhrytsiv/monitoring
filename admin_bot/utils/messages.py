from __future__ import annotations

import re
from typing import List
from app.utils.tg_links import sanitize_link

from aiogram.types import Message

LINK_RE = re.compile(r"(?i)\b((?:https?://|tg://|t\.me/)[^\s<>'\"\\]+)")


def _clean_url(u: str) -> str:
    """
    Нормалізує URL: sanitize_link + обрізає хвости з неприйнятних символів.
    Прибирає символи, що не можуть бути частиною посилання (лапки, дужки, кирилиця у хвості).
    """
    try:
        u = sanitize_link(u) or u
    except Exception:
        u = u
    u = (u or "").strip()
    # залишаємо лише ASCII-частину посилання (щоб обрізати випадкові кириличні символи вкінці)
    m = re.match(r"^((?:https?://|tg://|t\.me/)[A-Za-z0-9_\-./?&=#%+]+)", u)
    if m:
        u = m.group(1)
    # прибираємо хвіст із символів, що не входять у стандартний URL-алфавіт
    u = re.sub(r"[^\w\-./:?&=#%+]+$", "", u)
    u = u.rstrip(').,;\'"<>[]{}')
    return u


def extract_links_from_message(m: Message) -> List[str]:
    """
    Витягує всі посилання з тексту/ентіті, повертає унікальні в порядку появи.
    """
    urls: List[str] = []
    entities = m.entities or m.caption_entities or []
    txt = m.text or m.caption or ""
    for ent in entities:
        et = getattr(ent, "type", "")
        if et == "text_link":
            u = getattr(ent, "url", None)
            if u:
                urls.append(_clean_url(u))
        elif et == "url":
            off = int(getattr(ent, "offset", 0))
            ln = int(getattr(ent, "length", 0))
            piece = txt[off:off + ln].strip()
            if piece:
                urls.append(_clean_url(piece))
        elif et == "mention":  # @username
            off = int(getattr(ent, "offset", 0))
            ln = int(getattr(ent, "length", 0))
            piece = txt[off:off + ln].strip()
            if piece:
                urls.append(_clean_url(piece))
    for m_ in LINK_RE.finditer(txt):
        urls.append(_clean_url(m_.group(1)))
    # додатково ловимо «голі» @username, якщо не було ентіті
    for m_ in re.finditer(r"@[\w\d_]{4,}", txt):
        urls.append(_clean_url(m_.group(0)))
    # унікальні з порядком
    cleaned = [_clean_url(u) for u in urls if u]
    return list(dict.fromkeys(u for u in cleaned if u))
