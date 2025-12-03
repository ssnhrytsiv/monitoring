from __future__ import annotations
from typing import Iterable
import re

STATUS_ICON = {
    "joined": "✅ Подписано",
    "already": "↪️ Был подписан",
    "requested": "📨 Заявку отправлено",
    "invalid": "❌ Нерабочий",
    "private": "🔒 Приватный ",
    "blocked": "🚫 Ограничено",
    "too_many": "⚠️ Лимит каналов на аккаунте",
    "flood_wait": "⏳ FLOOD_WAIT",
    "duplicate": "🔁 Дубликат",
    "cached": "☑️",  # без хвостового пробілу
    "temp": "⚠️ Временная ошибка",
    "waiting": "⌛ Ожидание другим аккаунтом",
}

def fmt_result_line(idx: int, url: str, status: str, who: str | None = None, extra: str | None = None) -> str:
    base = STATUS_ICON.get(status, "• Невідомо")
    tail = f" [{who}]" if who else ""

    # Для кешованих joined/already — показуємо лише "☑️" без extra
    if status == "cached":
        ex = (extra or "").strip().lower()
        if ex in {"joined", "already", "alredy"}:
            extra = None

    extra_part = f" {extra}" if extra else ""
    line = f"{idx}. {url} — {base}{extra_part}{tail}"
    # На випадок множинних пробілів
    return re.sub(r"\s{2,}", " ", line).strip()

def fmt_summary(results: Iterable[str]) -> str:
    tail = "\n".join(results)
    return f"📊 Підсумок (останні):\n{tail}"