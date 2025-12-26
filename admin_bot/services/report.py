from __future__ import annotations

"""
Локальна копія логіки формування звіту з flow.batch_links.process_links:
- split_text_for_telegram: ріже довгі повідомлення під ліміт TG
- build_full_footer: формує підсумковий футер і секції (конфлікти/заявки/помилки/дублікати/сирі рядки)

Використання:
    footer, sections = build_full_footer(result_items, raw_lines)
    # footer — основний список з ренумерацією 1..N
    # sections — список (label, text) для додаткових блоків
"""

from typing import List, Optional, Any, Dict, Tuple
import re
from html import escape as _escape

from app.utils.tg_links import sanitize_link
from app.services import account_pool


def split_text_for_telegram(text: str, max_len: int = 4000) -> List[str]:
    """
    Розбиває текст на шматки, що поміщаються в ліміт Telegram (4096 символів).
    Розділяємо по рядках, щоб не рвати розмітку/посилання посередині.
    """
    base = text or ""
    if len(base) <= max_len:
        return [base]

    parts: List[str] = []
    current: List[str] = []
    current_len = 0

    for line in base.split("\n"):
        # +1 за символ переносу, який додамо при join
        line_len = len(line) + 1
        if current and current_len + line_len > max_len:
            parts.append("\n".join(current).strip())
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len

    if current:
        parts.append("\n".join(current).strip())

    return [p for p in parts if p]


def build_full_footer(items: List[dict], raw_lines: Optional[List[str]] = None) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Формує секції підсумку:
      - головна: лише «чисті» пункти з ренумерацією 1..N
      - додаткові: конфлікти, заявки, помилки, дублікати (для окремих кнопок)
      - опційно: сирий список рядків, як прийшли в бот (raw_lines), з позначками проблемних статусів
    """

    def _esc(s: str) -> str:
        return _escape(s or "")

    RE_CONFLICT = re.compile(r"owner_conflict\(existing=([^)]+)\)", re.IGNORECASE)

    def _conflict_name(status: str) -> Optional[str]:
        if not status:
            return None
        m = RE_CONFLICT.search(status)
        return m.group(1).strip() if m else None

    def _strip_conflict(status: str) -> str:
        if not status:
            return ""
        s = RE_CONFLICT.sub("", status)
        s = re.sub(r"\s*\|\s*\|\s*", " | ", s)
        s = re.sub(r"^\s*\|\s*|\s*\|\s*$", "", s)
        s = re.sub(r"\s{2,}", " ", s).strip()
        return s

    def _is_private(status: str) -> bool:
        s = (status or "").lower()
        return "private" in s

    def _is_invalid_or_error(status: str) -> bool:
        s = (status or "").lower()
        if _is_private(status):
            return False
        tokens = ("invalid", "error", "temp", "blocked", "too_many", "waiting")
        return any(tok in s for tok in tokens)

    def _is_duplicate(status: str) -> bool:
        return "duplicate" in (status or "").lower()

    def _looks_requested(status: str) -> bool:
        """
        Визначаємо заявки максимально надійно:
        - шукаємо 'requested' у status
        - або слово 'заявк' / 'заявка' / 'заявку'
        """
        raw, _ = _split_status_session(status)
        s = _strip_conflict(raw).lower()
        return "requested" in s or "заявк" in s

    def _split_status_session(status: str) -> tuple[str, Optional[str]]:
        if not status:
            return "", None
        s = status
        sess = None
        if "[" in s and s.endswith("]"):
            try:
                sess = s[s.rfind("[") + 1 : s.rfind("]")]
                s = s[: s.rfind("[")].strip()
            except Exception:
                pass
        return s, sess

    def _status_human(status: str) -> str:
        raw, sess = _split_status_session(status)
        base = _strip_conflict(raw).lower()
        raw_lower = raw.lower()

        if "owner_conflict" in raw_lower:
            conflict_with = _conflict_name(raw) or ""
            human = f"⚠️ Конфликт владельца (закреплен за {conflict_with})".strip()
        elif _looks_requested(status):
            human = "✉️ Заявка отправлена"
        elif _is_duplicate(status):
            human = "🔁 Дубликат"
        elif "bot_started" in base:
            human = "🤖 /start отправлено"
        elif "bot_invalid" in base:
            human = "❌ Бот не найден"
        elif "bot_flood" in base:
            human = "⏳ Flood (бот)"
        elif "bot_error" in base:
            human = "❌ Ошибка бота"
        elif "joined" in base:
            human = "✅ Подписался"
        elif "already" in base:
            human = "☑️ Был подписан"
        elif "flood" in base:
            human = "⏳ Flood"
        elif (
            "invalid" in base
            or "private" in base
            or "error" in base
            or "blocked" in base
            or "too_many" in base
        ):
            human = "❌ Невалидное"
        elif "done" in base or "ok" in base:
            human = "✅ Готово"
        elif "no_client" in base:
            human = "🛑 Нет доступных клиентов"
        else:
            human = _strip_conflict(raw) or "…"

        if sess:
            human = f"{human} [{account_pool.session_display(sess)}]"
        return human

    def _should_link_be_clickable(status: str) -> bool:
        s = _strip_conflict(status).lower()
        if _looks_requested(status):
            return False
        if _is_duplicate(status):
            return False
        if (
            "invalid" in s
            or "private" in s
            or "error" in s
            or "blocked" in s
            or "too_many" in s
            or "flood" in s
        ):
            return False
        return True

    def _link_line(idx: int, url: str, title: Optional[str], status: str, tag: str = "") -> str:
        """
        Рендер для всіх, крім блоку заявок (requested_items).
        Для заявок використовуємо окрему гілку нижче.
        """
        human_status = _status_human(status)
        suffix = f" {tag}" if tag else ""
        clickable = _should_link_be_clickable(status)

        if title:
            title_part = f"{idx}. {_esc(title)}{suffix}"
        else:
            title_part = f"{idx}."

        if clickable:
            link_part = f'<a href="{_esc(url)}">Ссылка</a>'
            return f"{title_part}\n   {link_part} — {human_status}"

        return f"{title_part}\n   Ссылка: {_esc(url)} — {human_status}"

    # --- групування і дублікати ---

    cid_to_items: Dict[Any, List[dict]] = {}
    for it in (items or []):
        cid = it.get("channel_id")
        if cid is None:
            continue
        cid_to_items.setdefault(cid, []).append(it)
    dup_cids = {cid for cid, lst in cid_to_items.items() if len(lst) > 1}

    clean_items_raw: List[tuple[str, Optional[str], str]] = []
    conflicts_by_admin: Dict[str, List[tuple[int, str, Optional[str], str]]] = {}
    requested_raw: List[tuple[int, str, Optional[str], str]] = []
    invalid_raw: List[tuple[int, str, Optional[str], str]] = []
    duplicate_raw: List[tuple[int, str, Optional[str], str]] = []
    dup_lines_by_cid: Dict[Any, List[tuple[int, str, Optional[str], str]]] = {}
    title_by_cid: Dict[Any, Optional[str]] = {}
    url_tags: Dict[str, tuple[str, str]] = {}
    url_status: Dict[str, str] = {}

    for it in (items or []):
        idx: int = it.get("idx") or 0
        url: str = it.get("url") or ""
        title: Optional[str] = it.get("title")
        status: str = it.get("status") or ""
        cid = it.get("channel_id")
        admin = _conflict_name(status)

        # Теги для raw-списку + карта статусів для прямої прив'язки до URL
        tag_label = ""
        tag_emoji = ""
        if cid is not None and cid in dup_cids:
            tag_label = "Дубликат"
            cadmin = _conflict_name(status)
            if cadmin:
                tag_label = f"Дубликат ({cadmin})"
            tag_emoji = "🔁"
        elif _is_duplicate(status):
            tag_label = "Дубликат"
            tag_emoji = "🔁"
        elif admin:
            tag_label = f"Конфликт (owner={admin})"
            tag_emoji = "⚠️"
        elif _looks_requested(status):
            tag_label = "Заявка отправлена"
            tag_emoji = "✉️"
        elif _is_invalid_or_error(status) or _is_private(status):
            tag_label = "Невалид"
            tag_emoji = "❌"
        human_status = _status_human(status)
        if url:
            try:
                nu = sanitize_link(url) or url
            except Exception:
                nu = url
            url_status[nu] = human_status
            if tag_label:
                if nu not in url_tags:
                    url_tags[nu] = (tag_emoji, tag_label)

        # Будь-який дублікат іде в окрему секцію (не показуємо в основному списку)
        if cid is not None and cid in dup_cids:
            dup_lines_by_cid.setdefault(cid, []).append((idx, url, title, status))
            title_by_cid.setdefault(cid, title)
            continue

        if admin:
            conflicts_by_admin.setdefault(admin, []).append((idx, url, title, status))
        elif _looks_requested(status):
            requested_raw.append((idx, url, title, status))
        elif _is_private(status):
            invalid_raw.append((idx, url, title, status))
        elif _is_invalid_or_error(status):
            invalid_raw.append((idx, url, title, status))
        elif _is_duplicate(status):
            duplicate_raw.append((idx, url, title, status))
        else:
            clean_items_raw.append((url, title, status))

    # ---------- Основний чистий список (ренумерація 1..N) ----------
    out: List[str] = ["📋 <b>Список:</b>"]
    if clean_items_raw:
        for new_idx, (url, title, status) in enumerate(clean_items_raw, start=1):
            out.append(_link_line(new_idx, url, title, status))
    else:
        out.append("— Нет чистых ссылок.")

    # ---------- Додаткові секції ----------
    sections: List[tuple[str, str]] = []

    # Конфлікти по адмінах
    if conflicts_by_admin:
        lines: List[str] = []
        for admin, lst in conflicts_by_admin.items():
            prefix = f'⚠️ Админ уже есть для этого канала: \"{admin}\"'
            lines.append(prefix)
            for orig_idx, url, title, status in lst:
                lines.append("  " + _link_line(orig_idx, url, title, status))
            lines.append("")
        sections.append(("⚠️ Конфликты", "\n".join(line for line in lines if line != "")))

    # Заявки, які ще не прийняті
    if requested_raw:
        lines: List[str] = ["✉️ Заявки отправлены, ожидаем:"]
        for orig_idx, url, title, status in requested_raw:
            lines.append(_link_line(orig_idx, url, title, status))
        sections.append(("✉️ Заявки", "\n".join(lines)))

    # Невалідні/приватні/помилки
    if invalid_raw:
        lines: List[str] = ["❌ Невалидные/приватные/ошибки:"]
        for orig_idx, url, title, status in invalid_raw:
            lines.append(_link_line(orig_idx, url, title, status))
        sections.append(("❌ Ошибки", "\n".join(lines)))

    # Дублікати (повтори посилань у пакеті)
    if duplicate_raw:
        lines: List[str] = ["🔁 Дубликаты ссылок (повторы в запросе):"]
        for orig_idx, url, title, status in duplicate_raw:
            lines.append(_link_line(orig_idx, url, title, status))
        sections.append(("🔁 Дубликаты ссылок", "\n".join(lines)))

    # Дублікати
    if dup_lines_by_cid:
        lines: List[str] = ["🔁 Дубликаты каналов:"]
        for cid in sorted(dup_lines_by_cid.keys()):
            title = title_by_cid.get(cid)
            if not title:
                for it in cid_to_items.get(cid, []):
                    if it.get("title"):
                        title = it.get("title")
                        break
            header = f"• {title or 'Без назви'} (ID: {cid})"
            lines.append(header)
            for orig_idx, url, title, status in dup_lines_by_cid[cid]:
                lines.append("  " + _link_line(orig_idx, url, title, status, tag="[дубликат]"))
        sections.append(("🔁 Дубликаты", "\n".join(lines)))

    # Отчет для кнопки: усі посилання + статуси (вихідна нумерація за idx)
    if items:
        report_lines = []
        for it in sorted(items, key=lambda t: t.get("idx") or 0):
            url = it.get("url") or ""
            status = it.get("status") or ""
            human = _status_human(status)
            idx_val = it.get("idx") or 0
            report_lines.append(f"{idx_val}. {url} — {human}")
        sections.append(("Отчет", "\n".join(report_lines)))

    return "\n".join(out), sections
