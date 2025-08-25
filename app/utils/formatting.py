# app/utils/formatting.py
from __future__ import annotations
from typing import Iterable

STATUS_ICON = {
    "joined": "✅ Підписано",
    "already": "↪️ Вже підписаний",
    "requested": "📨 Заявку на вступ відправлено",
    "invalid": "❌ Невалідне посилання",
    "private": "🔒 Приватний / неприєднуваний",
    "blocked": "🚫 Обмеження для акаунта",
    "too_many": "⚠️ Ліміт каналів на акаунті",
    "flood_wait": "⏳ FLOOD_WAIT",
    "duplicate": "🔁 Дублікат",
    "cached": "☑️ Кешований статус",
    "temp": "⚠️ Тимчасова помилка",
    "waiting": "⌛ Очікування / спроби іншими акаунтами",
}

def fmt_result_line(idx: int, url: str, status: str, who: str | None = None, extra: str | None = None) -> str:
    base = STATUS_ICON.get(status, "• Невідомо")
    tail = f" [{who}]" if who else ""
    extra = f" {extra}" if extra else ""
    return f"{idx}. {url} — {base}{extra}{tail}"

def fmt_summary(results: Iterable[str]) -> str:
    tail = "\n".join(results)
    return f"📊 Підсумок (останні):\n{tail}"