from __future__ import annotations

import re
from typing import Iterable, List

# Дозволені символи у шляху/квері після t.me/
# - букви/цифри/підкреслення
# - + (для інвайтів), / (сегменти), - . (часто трапляються в юзернеймах/квері)
# - параметри ?=&% (інколи є в коротких лінках)
_PATH_CHARS = r"A-Za-z0-9_/\+\-\.\?\=\%\&"

# 1) t.me/...
_RE_TME = re.compile(
    rf"""
    (?P<prefix>\b(?:https?://)?t\.me/)           # t.me/ з опційним http(s)
    (?P<path>[{_PATH_CHARS}]+)                   # все до пробілу/переносу/закр.дужки
    """,
    re.IGNORECASE | re.VERBOSE,
)

# 2) @username
_RE_AT = re.compile(
    r"(?P<at>@[A-Za-z0-9_]{3,})\b"
)

# Хвости, які часто "прилипають" у текстах після посилань
_TRAILING_JUNK = ".,;:!?)]}»”’"

def _to_str(text) -> str:
    """Гарантовано приводимо вхід до рядка."""
    if text is None:
        return ""
    if isinstance(text, str):
        return text
    try:
        return str(text)
    except Exception:
        return ""

def _strip_trailing_junk(s: str) -> str:
    """Прибираємо типові 'хвости' пунктуації наприкінці URL."""
    while s and s[-1] in _TRAILING_JUNK:
        s = s[:-1]
    return s

def _normalize_scheme(url: str) -> str:
    """Нормалізуємо схему до https://t.me/..."""
    u = url.strip()
    u = u.strip("()[]{}<>«»“”‘’")
    if u.startswith("@"):
        return "https://t.me/" + u[1:]
    if u.lower().startswith("http://t.me/"):
        return "https://" + u[7:]  # замінюємо http на https
    if u.lower().startswith("https://t.me/"):
        return "https://" + u[8:]  # нормалізуємо регістр
    if u.lower().startswith("t.me/"):
        return "https://" + u
    # якщо користувач вставив щось зовсім "сире"
    return "https://t.me/" + u

def is_invite(url: str) -> bool:
    """Швидка перевірка: чи інвайт (t.me/+... або t.me/joinchat/...)."""
    u = url.lower()
    return ("/+" in u) or ("joinchat/" in u)

def normalize(url: str) -> str:
    """Повна нормалізація одного t.me посилання."""
    url = _strip_trailing_junk(_to_str(url))
    return _normalize_scheme(url)

def _dedup_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in items:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out

def extract_links(text: str) -> List[str]:
    """
    Витягує t.me-посилання з довільного тексту:
      - https://t.me/...
      - http://t.me/...
      - t.me/...
      - @username  → https://t.me/username
      - підтримка інвайтів: t.me/+..., t.me/joinchat/...
      - підтримка t.me/c/...
    Повертає список НОРМАЛІЗОВАНИХ URL у форматі https://t.me/...
    """
    s = _to_str(text)
    if not s:
        return []

    found: List[str] = []

    # 1) зібрати всі t.me/...
    for m in _RE_TME.finditer(s):
        prefix = m.group("prefix") or ""
        path = m.group("path") or ""
        raw = prefix + path
        raw = _strip_trailing_junk(raw)
        if not raw:
            continue
        found.append(_normalize_scheme(raw))

    # 2) зібрати @username
    for m in _RE_AT.finditer(s):
        at = m.group("at")
        if not at:
            continue
        found.append(_normalize_scheme(at))

    # Унікалізуємо з збереженням порядку
    return _dedup_preserve_order(found)

# Сумісний псевдонім для існуючих викликів у плагіні
def extract_links_any(text: str) -> List[str]:
    return extract_links(text)