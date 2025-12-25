from __future__ import annotations

import re
from typing import List

from aiogram.types import Message

LINK_RE = re.compile(r"(?i)\b((?:https?://|tg://|t\.me/)[^\s<>'\"\\]+)")


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
                urls.append(u)
        elif et == "url":
            off = int(getattr(ent, "offset", 0))
            ln = int(getattr(ent, "length", 0))
            piece = txt[off:off + ln].strip()
            if piece:
                urls.append(piece)
    for m_ in LINK_RE.finditer(txt):
        urls.append(m_.group(1))
    # унікальні з порядком
    return list(dict.fromkeys(urls))
