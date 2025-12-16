# app/utils/tg_links.py
import re
from urllib.parse import urlsplit, urlunsplit, SplitResult

def sanitize_link(u: str) -> str:
    """
    Нормалізує/«лікує» URL:
      - виправляє типові опечатки у схемі: tps://, htps://, https//, http//
      - tg://resolve?domain=foo  ->  https://t.me/foo
      - @username                ->  https://t.me/username
      - t.me/... без схеми       ->  https://t.me/...
      - прибирає «подвійну схему»: https://https://t.me/...
      - для t.me завжди ставить HTTPS
    Повертає стабільний рядок. Якщо не вдалось розпарсити — повертає виправлене «як є».
    """
    s = (u or "").strip()
    if not s:
        return s

    low = s.lower()

    # 1) tg://resolve?domain=foo -> https://t.me/foo
    if low.startswith("tg://resolve?domain="):
        # беремо домен до першого '&' (якщо він є), і знімаємо '@'
        name = s.split("=", 1)[-1].split("&", 1)[0].lstrip("@").strip()
        if name:
            s = f"https://t.me/{name}"
            low = s.lower()

    # 2) @username -> https://t.me/username
    if s.startswith("@"):
        s = f"https://t.me/{s[1:].strip()}"
        low = s.lower()

    # 3) Найчастіші опечатки/усічення схеми на початку
    fixes = (
        ("https//", "https://"),
        ("http//",  "http://"),
        ("tps://",  "https://"),
        ("htps://", "https://"),
        ("ttps://", "https://"),
        ("ps://",   "https://"),
        ("s://",    "https://"),
    )
    for bad, good in fixes:
        if s.startswith(bad):
            s = good + s[len(bad):]
            low = s.lower()
            break

    # 4) t.me/... без схеми -> https://t.me/...
    if low.startswith("t.me/"):
        s = "https://" + s
        low = s.lower()

    # 5) Прибрати «подвійну схему»: https://https://t.me/...
    m = re.match(r"^([a-zA-Z][a-zA-Z0-9+\-.]*://)(.+)$", s)
    if m:
        scheme = m.group(1)
        rest = re.sub(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", "", m.group(2))
        s = scheme + rest
        low = s.lower()

    # 6) Розбір URL та фінальне доведення до ладу
    try:
        p = urlsplit(s)
    except Exception:
        return s  # як є, якщо дуже криво

    # якщо схеми немає — вважаємо https
    if not p.scheme:
        s = "https://" + s.lstrip("/")
        p = urlsplit(s)

    # якщо netloc порожній, а шлях схожий на t.me/... → перетворюємо
    if not p.netloc and p.path.startswith("t.me/"):
        s = "https://" + p.path
        p = urlsplit(s)

    # Підвищуємо до HTTPS для t.me
    if p.netloc.lower() == "t.me" and p.scheme != "https":
        p = SplitResult("https", p.netloc, p.path, p.query, p.fragment)

    return urlunsplit(p)