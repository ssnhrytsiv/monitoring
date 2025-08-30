# app/utils/link_parser.py
from __future__ import annotations
import re
from typing import Iterable, List, Optional, Union

try:
    # Імпортимо типи тільки якщо є telethon (щоб утиліта жила і без нього)
    from telethon.tl import types as tg_types
    from telethon.tl.custom.message import Message as TgMessage
except Exception:  # pragma: no cover
    tg_types = None
    TgMessage = None  # type: ignore

# --- Регулярки ---
# 1) Markdown: [label](https://t.me/...)
RE_MD_TG = re.compile(
    r"\[[^\]]+\]\(\s*(https?://t\.me/[^\s)]+)\s*\)",
    re.IGNORECASE,
)

# 2) HTML: <a href="https://t.me/..."> або одинарні лапки
RE_HTML_TG = re.compile(
    r"""<a\s+[^>]*href\s*=\s*(['"])(https?://t\.me/[^'"]+)\1""",
    re.IGNORECASE,
)

# 3) Сирі лінки та @username
#    група 1 — шлях після t.me/, група 2 — @username
RE_TG_RAW = re.compile(
    r"(?:https?://)?t\.me/([^\s)\]]+)|(@[A-Za-z0-9_]{3,})",
    re.IGNORECASE,
)

# Допоміжне: прибрати невидимі символи/окантовку і «хвости» пунктуації
_INVIS = ("\u200b", "\u200e", "\u200f")
_TRAIL_PUNCT = ".,;:)]}>"


def _clean(s: str) -> str:
    if not s:
        return s
    for ch in _INVIS:
        s = s.replace(ch, "")
    s = s.strip()
    # зняти зовнішні дужки, якщо вони «обгортають» лінк
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    # прибрати типові «хвости» пунктуації
    while s and s[-1] in _TRAIL_PUNCT:
        s = s[:-1]
    return s


def normalize(url: str) -> str:
    """
    Приводить url до стабільної форми:
    - видаляє невидимі символи та зайву окантовку
    - перетворює @username -> https://t.me/username
    - додає https:// якщо немає схеми / або починається з t.me/
    """
    url = _clean(url)

    if not url:
        return url

    if url.startswith("@"):
        return f"https://t.me/{url[1:]}"

    if url.startswith("t.me/"):
        return f"https://{url}"

    if not url.startswith("http"):
        return f"https://{url}"

    return url


def is_invite(url: str) -> bool:
    """
    Швидка перевірка: чи є лінк інвайтом (з +hash або joinchat).
    """
    u = (url or "").lower()
    return ("/+" in u) or ("joinchat/" in u)


def extract_links(text: str) -> List[str]:
    """
    Витягує t.me посилання з довільного ТЕКСТУ (regex):
      • Markdown: [label](https://t.me/...)
      • HTML: <a href="https://t.me/...">
      • Сирі: https://t.me/..., t.me/..., @username

    Повертає список нормалізованих URL у форматі 'https://t.me/...'
    (для @username — 'https://t.me/<name>'), без дублікатів, у вихідному порядку.
    """
    if not text:
        return []

    candidates: List[str] = []

    # 1) Markdown
    for m in RE_MD_TG.finditer(text):
        candidates.append(m.group(1))

    # 2) HTML
    for m in RE_HTML_TG.finditer(text):
        candidates.append(m.group(2))

    # 3) Сирі URL/username
    for m in RE_TG_RAW.finditer(text):
        if m.group(1):  # шлях після t.me/
            candidates.append("https://t.me/" + m.group(1).strip())
        elif m.group(2):  # @username
            candidates.append(m.group(2))

    # Нормалізувати та прибрати дублі, зберігаючи порядок
    seen = set()
    out: List[str] = []
    for c in candidates:
        u = normalize(c)
        if not u:
            continue
        if u not in seen:
            out.append(u)
            seen.add(u)

    return out


def _extract_from_entities(text: str, entities: Iterable) -> List[str]:
    """
    Витягує t.me посилання із Telegram entities:
      • MessageEntityTextUrl: беремо e.url
      • MessageEntityUrl: беремо фрагмент тексту за offset/length
      • MessageEntityMention: '@name' -> https://t.me/name
    """
    if tg_types is None or not entities:
        return []

    links: List[str] = []
    for e in entities:
        try:
            if isinstance(e, tg_types.MessageEntityTextUrl):
                links.append(e.url)
            elif isinstance(e, tg_types.MessageEntityUrl):
                frag = text[e.offset : e.offset + e.length]
                links.append(frag)
            elif isinstance(e, tg_types.MessageEntityMention):
                frag = text[e.offset : e.offset + e.length]
                links.append(frag)  # це @username — normalize перетворить
        except Exception:
            continue

    # Нормалізація + унікальність із збереженням порядку
    seen = set()
    out: List[str] = []
    for raw in links:
        u = normalize(raw)
        if u and u not in seen:
            out.append(u)
            seen.add(u)
    return out


def extract_links_any(msg_or_text: Union[str, "TgMessage"]) -> List[str]:
    """
    Універсальний витягувач:
      • якщо дали Telethon Message — бере і regex із тексту, і з entities
      • якщо дали рядок — працює як звичайний extract_links
    """
    # випадок Telethon Message
    if TgMessage and isinstance(msg_or_text, TgMessage):
        text = msg_or_text.raw_text or ""
        out = extract_links(text)
        # з entities добираємо приховані лінки
        ent_links = _extract_from_entities(text, msg_or_text.entities or [])
        # мержимо унікально, зберігаючи початковий порядок
        seen = set(out)
        for u in ent_links:
            if u not in seen:
                out.append(u)
                seen.add(u)
        return out

    # випадок звичайного тексту
    return extract_links(str(msg_or_text or ""))