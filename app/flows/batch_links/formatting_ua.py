from __future__ import annotations

def esc(s: str) -> str:
    if not s:
        return ""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )

def ellipsis(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else (s[: max(0, n - 1)] + "…")

def pad(s: str, w: int) -> str:
    s = s or ""
    if len(s) >= w:
        return s
    return s + " " * (w - len(s))

def col(s: str, w: int) -> str:
    return pad(ellipsis(esc(s), w), w)

def short_url(u: str, width: int = 36) -> str:
    return ellipsis(u or "", width)

def human_status(kind: str, cached: bool) -> tuple[str, str]:
    """
    kind: 'joined'|'already'|'invalid'|'private'|'error'|'flood'
    cached: True якщо брали зі своєї БД/кешу
    """
    if kind == "joined":
        return "✅", ("вже підписаний" if cached else "підписано")
    if kind == "already":
        return "✅", "вже підписаний"
    if kind in ("invalid", "private", "error"):
        return "❌", ("не робочий лінк" if cached else "помилка/приватний/невалідний")
    if kind == "flood":
        return "⏳", "затримка (flood)"
    return "•", kind

def build_row(
    idx: int,
    url: str,
    title: str | None,
    kind: str,
    cached: bool,
    session_name: str | None = None,
    flood_sec: int | None = None,
) -> str:
    """
    Формуємо «рядок таблиці» для <pre>…</pre>.
    Колонки:
      № | Назва/URL | Статус | Додатково
    """
    emoji, txt = human_status(kind, cached)
    num = col(f"{idx}.", 4)
    name = col(title or short_url(url), 40)
    stat = col(f"{emoji} {txt}", 22)

    extra = ""
    if kind == "flood" and (flood_sec or 0) > 0:
        if session_name:
            extra = f"(сплю {int(flood_sec)}с; {session_name})"
        else:
            extra = f"(сплю {int(flood_sec)}с)"
    elif session_name:
        extra = f"[{session_name}]"

    return f"{num}{name}{stat}{esc(extra)}"