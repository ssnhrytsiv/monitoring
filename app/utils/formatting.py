# app/utils/formatting.py
from __future__ import annotations

from typing import Any, Dict, Iterable, List
from html import escape as _esc

# карта статусів: код -> текст з іконкою
_STATUS_MAP: Dict[str, str] = {
    "joined":      "✅ приєднано",
    "already":     "♻️ вже підписаний",
    "requested":   "🕊️ заявка на вступ",
    "invalid":     "❌ невалідне",
    "private":     "🔒 приватний",
    "blocked":     "🚫 блок",
    "too_many":    "🚧 ліміт",
    "flood_wait":  "⏳ FLOOD_WAIT",
    "waiting":     "⏸ очікує",
    "cached":      "☑️ кеш",
    "temp":        "ℹ️ тимчасово",
    "duplicate":   "🔁 дублікат",
}

def _status_text(code: str, extra: str | None = None) -> str:
    base = _STATUS_MAP.get(code, code)
    return f"{base} ({_esc(extra)})" if extra else base


def fmt_result_line(
    idx: int,
    url: str,
    code: str,
    actor: str | None = None,
    extra: str | None = None,
    title: str | None = None,
) -> dict:
    return {
        "idx": idx,
        "url": url,
        "title": title or "",
        "status_code": code,
        "status_text": _status_text(code, extra),
        "actor": actor or "",
    }


def fmt_summary(rows: Iterable[Any]) -> str:
    """
    Рендер у HTML-текст із переносами рядків ('\\n') у форматі:
      1. Повна назва
         <a href="...">Посилання</a> — Статус

    Між записами — порожній рядок для читабельності.
    """
    structured: List[dict] = []
    for r in rows:
        if isinstance(r, dict) and {"idx", "url", "title", "status_code", "status_text", "actor"} <= set(r.keys()):
            structured.append(r)

    if not structured:
        return ""

    blocks: List[str] = []
    for r in structured:
        idx   = r["idx"]
        url   = r["url"]
        title = (r.get("title") or "").strip() or "—"
        stat  = r["status_text"]

        top_line = f"{idx}. {_esc(title)}"
        link_line = f"<a href=\"{_esc(url)}\">Посилання</a> — {_esc(stat)}"

        blocks.append(f"{top_line}\n{link_line}")

    # Повертаємо «чистий» HTML із переносами рядків.
    return "\n\n".join(blocks)