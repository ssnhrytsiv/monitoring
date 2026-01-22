from __future__ import annotations

import html
import re
from typing import List, Dict, Optional

from app.utils.link_parser import sanitize_link
from app.services.account_pool import session_display


def _clean_url(url: str) -> str:
    try:
        cleaned = sanitize_link(url) or url
    except Exception:
        cleaned = url
    cleaned = (cleaned or "").rstrip(").,;")
    return cleaned or ""


def render_html_with_statuses(
    result_items: List[Dict],
    original_urls: Optional[List[str]] = None,
) -> str:
    """
    Рендерить тільки фінальний нумерований список лінків зі статусами
    у порядку початкових URL (original_urls якщо задано, інакше порядок result_items).
    """

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
        base = raw.lower()

        if "owner_conflict" in base:
            m = re.search(r"existing=([^\]\)]+)", raw)
            owner = m.group(1).strip() if m else ""
            human = f"⚠️ Конфликт за админом {owner}".strip()
        elif "requested" in base or "заявк" in base:
            human = "✉️ Заявка отправлена"
        elif "duplicate" in base:
            human = "🔁 Дубликат"
        elif "bot_started" in base:
            human = "🤖 /start отправлено"
        elif "bot_invalid" in base:
            human = "❌ Бот не найден"
        elif "bot_flood" in base or "flood" in base or "wait of" in base:
            # Флуд: показуємо тривалість, якщо знайдена
            seconds = None
            m = re.search(r"flood_wait_(\d+)", base)
            if not m:
                m = re.search(r"wait of (\d+)", base)
            if m:
                seconds = m.group(1)
            human = "⏳ Флуд"
            if seconds:
                human = f"⏳ Флуд ({seconds}s)"
        elif "bot_error" in base or "error" in base:
            human = "❌ Ошибка"
        elif "joined" in base:
            human = "✅ Подписался"
        elif "already" in base:
            human = "☑️ Был подписан"
        elif "no_client" in base:
            human = "🛑 Нет доступных клиентов"
        elif "invalid" in base or "private" in base or "blocked" in base:
            human = "❌ Невалидное"
        elif "too_many" in base:
            human = "🚫 Лимит"
        else:
            human = raw or "…"

        if sess:
            human = f"{human} [{session_display(sess)}]"
        return human

    # Рахуємо дублікати по нормалізованих URL та channel_id
    norm_counts: Dict[str, int] = {}
    cid_counts: Dict[Optional[int], int] = {}
    for it in result_items:
        n = _clean_url(it.get("url", ""))
        norm_counts[n] = norm_counts.get(n, 0) + 1
        cid_counts[it.get("channel_id")] = cid_counts.get(it.get("channel_id"), 0) + 1

    # Порядок рендеру: або original_urls, або порядок result_items
    render_order = original_urls if original_urls else [it.get("url", "") for it in result_items]

    # Готуємо бакети items по нормалізованому URL, щоб брати по одному в порядку
    buckets: Dict[str, List[Dict]] = {}
    for it in result_items:
        n = _clean_url(it.get("url", ""))
        buckets.setdefault(n, []).append(it)

    norm_seen: Dict[str, int] = {}
    cid_seen: Dict[Optional[int], int] = {}
    status_lines: List[str] = []
    idx_display = 0

    def _pop_item(norm: str) -> Optional[Dict]:
        lst = buckets.get(norm) or []
        if lst:
            return lst.pop(0)
        return None

    for url in render_order:
        norm = _clean_url(url)
        item = _pop_item(norm)
        if not item:
            continue
        idx_display += 1

        href = item.get("url", "")
        cid = item.get("channel_id")
        norm_seen[norm] = norm_seen.get(norm, 0) + 1
        cid_seen[cid] = cid_seen.get(cid, 0) + 1

        raw_status = item.get("status", "")
        human = _status_human(raw_status)

        is_dup = False
        if norm_counts.get(norm, 0) > 1 and norm_seen[norm] >= 2:
            is_dup = True
        if cid is not None and cid_counts.get(cid, 0) > 1 and cid_seen[cid] >= 2:
            is_dup = True
        if is_dup:
            human = "🔁 Дубликат"
            raw, sess = _split_status_session(raw_status)
            if sess:
                human = f"{human} [{session_display(sess)}]"

        title = item.get("title") or href
        title_safe = html.escape(title or "")
        human_safe = html.escape(human or "")
        if href:
            status_lines.append(f'{idx_display}) <a href="{href}">{title_safe}</a> — {human_safe}')
        else:
            status_lines.append(f"{idx_display}) {title_safe} — {human_safe}")

    # Якщо щось залишилось у бакетах (не відображено), додаємо в кінці
    for items_left in buckets.values():
        for item in items_left:
            idx_display += 1
            href = item.get("url", "")
            title = item.get("title") or href
            human = _status_human(item.get("status", ""))
            title_safe = html.escape(title or "")
            human_safe = html.escape(human or "")
            status_lines.append(f'{idx_display}) <a href="{href}">{title_safe}</a> — {human_safe}')

    final_text = "\n".join(status_lines).strip()
    return final_text


__all__ = ["render_html_with_statuses"]
