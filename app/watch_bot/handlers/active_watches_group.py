from typing import Optional, List, Any, Dict
import os
import logging
import re
import html

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from app.watch_bot.states import EditWatch
from app.watch_bot.keyboards import main_menu_kb
from app.services.time_utils import msk_now

from app.watch_bot.services.templates_repo import load_templates_map
from app.watch_bot.services.channels_repo import (
    get_links_by_channel_ids,
    get_owners_by_channel_ids,
    get_titles_by_channel_ids,
)
from app.watch_bot.services.active_watches_service import (
    get_group_leader_key,
    load_group_items,
    load_group_channels,
    cancel_group_watches,
    get_watch_by_id,
    get_group_leader_for_watch,
)
from app.watch_bot.services.edit_watch_service import (
    set_watch_status_pending,
    update_watch_time_window,
    manual_match_watch_from_message,
)
from app.DAL.watch_candidates_operations import (
    CANDIDATE_PENDING_STATUS,
    list_watch_candidates,
    list_group_watch_candidates,
    list_candidates_by_hash,
    get_watch_candidate,
    accept_watch_candidate,
    set_watch_candidate_status,
    get_watch_expected_links,
    get_watch_expected_text,
)
try:
    from app.sheet_bot.services import gsheets_buffer as gsb
except Exception:
    gsb = None
from app.services.post_matcher import normalize_text, extract_links_norm
from app.watch_bot.utils.active_watches_formatters import (
    fmt_tw_end_human,
    short_title,
    status_to_emoji,
    build_group_table,
    format_single_watch,
)
from app.watch_bot.utils.active_watches_pagination import (
    paginate_items,
    build_group_keyboard,
    PAGE_SIZE,
)

log = logging.getLogger("bot_active_watches.group")
router = Router()

STATUS_PRESETS = {
    "pending": ["pending"],
    "matched": ["matched"],
    "expired": ["expired"],
}

_TG_EMOJI_TAG_RE = re.compile(r"<tg-emoji\b(?P<attrs>[^>]*)>(?P<body>.*?)</tg-emoji>", re.DOTALL | re.IGNORECASE)
_TG_EMOJI_TOKEN_RE = re.compile(r"(<tg-emoji\b[^>]*>.*?</tg-emoji>)", re.DOTALL | re.IGNORECASE)
_SPAN_TAG_RE = re.compile(r"<span\b(?P<attrs>[^>]*)>(?P<body>.*?)</span>", re.DOTALL | re.IGNORECASE)
_PRE_TAG_RE = re.compile(r"<pre\b(?P<attrs>[^>]*)>(?P<body>.*?)</pre>", re.DOTALL | re.IGNORECASE)
_TG_SPOILER_TAG_RE = re.compile(r"<tg-spoiler>(?P<body>.*?)</tg-spoiler>", re.DOTALL | re.IGNORECASE)



def _edit_back_kb(wid: int) -> InlineKeyboardBuilder:
    """
    Клавіатура з кнопкою 'Back' для повернення в картку редагування watch'а.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Back", callback_data=f"watch:edit:{wid}")
    return kb


def _back_to_group_cb(wid: Optional[int]) -> Optional[str]:
    # Завжди повертаємо у список активних вотчів (за замовчуванням — pending)
    return "menu:list_active:pending"


def _collect_links(text: str) -> List[str]:
    """
    Витягує унікальні посилання: href з HTML + голі URL із очищеного тексту (без тегів).
    Прибирає сміття типу \"><u> тощо.
    """
    links: List[str] = []
    seen = set()
    if not text:
        return links

    def _clean(u: str) -> str:
        u = html.unescape(u or "").strip()
        u = u.strip(" '\"<>")
        return u

    # href
    for m in re.findall(r'href\s*=\s*(?:"|\')([^"\']+)(?:"|\')', text, flags=re.IGNORECASE):
        u = _clean(m)
        if u and u not in seen:
            seen.add(u)
            links.append(u)

    # текст без тегів
    plain = re.sub(r"<[^>]+>", " ", html.unescape(text))
    try:
        for u in extract_links_norm(plain):
            u = _clean(u)
            if u and u not in seen:
                seen.add(u)
                links.append(u)
    except Exception:
        pass

    return links


def _extract_html_attr_value(attrs_text: str, attr_name: str) -> str:
    if not attrs_text:
        return ""
    attr_pattern = re.compile(
        rf"\b{re.escape(attr_name)}\s*=\s*(?:\"(?P<dq>[^\"]+)\"|'(?P<sq>[^']+)')",
        flags=re.IGNORECASE,
    )
    match = attr_pattern.search(attrs_text)
    if not match:
        return ""
    value = match.group("dq") or match.group("sq") or ""
    return str(value).strip()


def _sanitize_bot_api_html_fragment(text: str) -> str:
    """
    Приводить HTML-фрагмент до формату, який стабільно приймає Bot API.
    Зокрема:
      - <span data-custom-emoji-id="...">..</span> -> <tg-emoji emoji-id="...">..</tg-emoji>
      - <span class="tg-spoiler">..</span> лишається canonical
      - інші span розгортаються в plain body
      - <br> перетворюється на звичайні переводи рядків
    """
    if not text:
        return ""

    sanitized = text.replace("\r\n", "\n").replace("\r", "\n")
    sanitized = re.sub(r"<\s*br\s*/?>", "\n", sanitized, flags=re.IGNORECASE)

    def _replace_tg_emoji(match: re.Match) -> str:
        attrs_text = str(match.group("attrs") or "")
        body_text = str(match.group("body") or "")
        emoji_id = _extract_html_attr_value(attrs_text, "emoji-id")
        if not emoji_id:
            return body_text
        emoji_id_safe = html.escape(emoji_id, quote=True)
        return f'<tg-emoji emoji-id="{emoji_id_safe}">{body_text}</tg-emoji>'

    def _replace_span(match: re.Match) -> str:
        attrs_text = str(match.group("attrs") or "")
        body_text = str(match.group("body") or "")
        emoji_id = _extract_html_attr_value(attrs_text, "data-custom-emoji-id")
        if emoji_id:
            emoji_id_safe = html.escape(emoji_id, quote=True)
            return f'<tg-emoji emoji-id="{emoji_id_safe}">{body_text}</tg-emoji>'

        span_class = _extract_html_attr_value(attrs_text, "class")
        classes = {part.strip().lower() for part in span_class.split() if part.strip()}
        if "tg-spoiler" in classes:
            return f"<tg-spoiler>{body_text}</tg-spoiler>"

        return body_text

    def _replace_pre(match: re.Match) -> str:
        body_text = str(match.group("body") or "")
        return f"<pre>{body_text}</pre>"

    sanitized = _TG_EMOJI_TAG_RE.sub(_replace_tg_emoji, sanitized)
    sanitized = _SPAN_TAG_RE.sub(_replace_span, sanitized)
    sanitized = _PRE_TAG_RE.sub(_replace_pre, sanitized)
    return sanitized


_A_TAG_RE = re.compile(
    r'<a\s+href=(?P<q1>"|\')(?P<href>.+?)(?P=q1)>(?P<body>.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)


def _candidate_html_to_display_text(text: str) -> str:
    """
    Готує читабельний preview-текст для UI.
    Це не matcher-логіка і не exact-render оригіналу, а саме clean preview:
      - лінки показує їх видимим текстом;
      - block tags перетворює на нормальні переводи рядків;
      - custom emoji / spoiler розкриває до тексту;
      - прибирає технічний HTML, який добре підходить для матчингу, але погано для картки.
    """
    if not text:
        return ""

    normalized = _sanitize_bot_api_html_fragment(text)

    def _replace_a(match: re.Match) -> str:
        body_text = str(match.group("body") or "")
        href_text = html.unescape(str(match.group("href") or "")).strip()
        body_plain_text = _candidate_html_to_display_text(body_text).strip()
        if body_plain_text:
            return body_plain_text
        return href_text

    normalized = _A_TAG_RE.sub(_replace_a, normalized)
    normalized = re.sub(r"</\s*(?:blockquote|pre|code|p|div)\s*>", "\n", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"<\s*(?:blockquote|pre|code|p|div)\b[^>]*>", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"<\s*br\s*/?>", "\n", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[\u200b\u200c\u200d\uFEFF\uFE0F]", "", normalized)
    normalized = re.sub(r"<[^>]+>", "", normalized)
    normalized = html.unescape(normalized).replace("\xa0", " ")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n[ \t]+", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)

    cleaned_lines = [line.rstrip() for line in normalized.splitlines()]
    cleaned_text = "\n".join(cleaned_lines).strip()
    return cleaned_text


def _truncate_preview_html_preserving_custom_emoji(text: str, max_visible_chars: int = 80) -> str:
    if not text:
        return ""
    if max_visible_chars <= 0:
        return ""

    parts = _TG_EMOJI_TOKEN_RE.split(text)
    out: List[str] = []
    visible_chars = 0
    truncated = False

    for part in parts:
        if not part:
            continue

        if _TG_EMOJI_TOKEN_RE.fullmatch(part):
            emoji_body_match = _TG_EMOJI_TAG_RE.fullmatch(part)
            emoji_body = str(emoji_body_match.group("body") or "") if emoji_body_match else ""
            emoji_visible_len = max(1, len(html.unescape(re.sub(r"<[^>]+>", "", emoji_body))) or 1)
            if visible_chars + emoji_visible_len > max_visible_chars and out:
                truncated = True
                break
            out.append(part)
            visible_chars += emoji_visible_len
            continue

        plain_part = html.unescape(part)
        remaining_chars = max_visible_chars - visible_chars
        if remaining_chars <= 0:
            truncated = True
            break
        if len(plain_part) <= remaining_chars:
            out.append(html.escape(plain_part, quote=False))
            visible_chars += len(plain_part)
            continue

        out.append(html.escape(plain_part[:remaining_chars].rstrip(), quote=False))
        visible_chars += remaining_chars
        truncated = True
        break

    result = "".join(out).strip()
    if truncated and result:
        result = result.rstrip() + "…"
    return result


def _candidate_html_to_preview_html(text: str, max_visible_chars: int = 80) -> str:
    """
    Короткий preview для списку кандидатів.
    Тут важливо зберегти premium emoji, але не тягнути весь технічний HTML у список.
    """
    if not text:
        return ""

    preview_html = _sanitize_bot_api_html_fragment(text)

    def _replace_a(match: re.Match) -> str:
        body_text = str(match.group("body") or "")
        href_text = html.unescape(str(match.group("href") or "")).strip()
        return body_text if body_text.strip() else html.escape(href_text, quote=False)

    preview_html = _A_TAG_RE.sub(_replace_a, preview_html)
    preview_html = _TG_SPOILER_TAG_RE.sub(lambda m: str(m.group("body") or ""), preview_html)
    preview_html = re.sub(r"</\s*(?:blockquote|pre|code|p|div)\s*>", "\n", preview_html, flags=re.IGNORECASE)
    preview_html = re.sub(r"<\s*(?:blockquote|pre|code|p|div)\b[^>]*>", "", preview_html, flags=re.IGNORECASE)
    preview_html = re.sub(r"<\s*br\s*/?>", "\n", preview_html, flags=re.IGNORECASE)
    preview_html = re.sub(r"</?(?:b|strong|i|em|u|ins|s|strike|del|code)\b[^>]*>", "", preview_html, flags=re.IGNORECASE)
    preview_html = re.sub(
        r"</?[^>]+>",
        lambda m: (
            m.group(0)
            if m.group(0).lower().startswith("<tg-emoji") or m.group(0).lower().startswith("</tg-emoji")
            else ""
        ),
        preview_html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    preview_html = re.sub(r"[\u200b\u200c\u200d\uFEFF\uFE0F]", "", preview_html)
    preview_html = preview_html.replace("\xa0", " ")
    preview_html = re.sub(r"[ \t]+\n", "\n", preview_html)
    preview_html = re.sub(r"\n[ \t]+", "\n", preview_html)
    preview_html = re.sub(r"\n{3,}", "\n\n", preview_html).strip()

    return _truncate_preview_html_preserving_custom_emoji(preview_html, max_visible_chars=max_visible_chars)


@router.callback_query(F.data == "watch:noop")
async def watch_noop(cb: CallbackQuery):
    await cb.answer()


@router.callback_query(F.data.startswith("watch:channels:"))
async def watch_channels(cb: CallbackQuery):
    """
    Показує список посилань каналів для групи leader_wid.
    """
    try:
        leader_wid = int(cb.data.split(":")[-1])
    except Exception:
        leader_wid = None

    if not leader_wid:
        await cb.answer("bad id", show_alert=True)
        return

    cids = load_group_channels(leader_wid)
    if not cids:
        await cb.answer("Каналів немає", show_alert=True)
        return

    links_map = get_links_by_channel_ids(cids)

    links: List[str] = []
    seen = set()
    for cid in cids:
        u = links_map.get(cid)
        if not u:
            continue
        u = str(u).strip()
        if not u or u in seen:
            continue
        seen.add(u)
        links.append(u)

    if not links:
        await cb.answer("Каналів немає", show_alert=True)
        return

    txt = "\n".join(links)
    if len(txt) > 3500:
        txt = txt[:3500] + "…"
    await cb.answer(txt, show_alert=True)


@router.callback_query(F.data.startswith("watch:cancel:"))
async def watch_cancel(cb: CallbackQuery):
    """
    Скасовує всі watch'і групи leader_wid (pending/matched/expired -> cancelled).
    """
    parts = cb.data.split(":")
    leader_wid: Optional[int] = None
    status_key: Optional[str] = None
    try:
        if len(parts) >= 3:
            leader_wid = int(parts[2])
        if len(parts) >= 4:
            status_key = parts[3] if parts[3] in STATUS_PRESETS else None
    except Exception:
        leader_wid = None
    if not leader_wid:
        await cb.answer("bad id", show_alert=True)
        return

    ok = False
    try:
        ok = cancel_group_watches(leader_wid)
    except Exception as e:
        log.exception("cancel_group_watches failed: %s", e)

    if not ok:
        await cb.answer("Не зміг скасувати", show_alert=True)
        return

    await cb.answer("Скасовано", show_alert=False)

    # Щоб оновити список, імпортуємо хендлер меню тут
    from app.watch_bot.handlers.active_watches_menu import menu_list_active

    await menu_list_active(cb, status_key=status_key)


@router.callback_query(F.data.startswith("watch:group:"))
async def watch_group_details(cb: CallbackQuery):
    """
    Деталізація групи вотчів для leader_wid з пагінацією по кнопках.
    """
    parts = cb.data.split(":")
    leader_wid: Optional[int] = None
    page = 1
    status_key: Optional[str] = None
    try:
        leader_wid = int(parts[2])  # watch:group:<leader_wid>:...
        for token in parts[3:]:
            if token.isdigit():
                page = int(token) or 1
            elif token in STATUS_PRESETS:
                status_key = token
    except Exception:
        leader_wid = None

    if not leader_wid:
        await cb.answer("bad id", show_alert=True)
        return

    if page < 1:
        page = 1

    # 1) Читаємо ключ групи
    try:
        key = get_group_leader_key(leader_wid)
    except Exception as e:
        log.exception("get_group_leader_key failed: %s", e)
        key = None

    if not key:
        await cb.answer("Не знайдено", show_alert=True)
        return

    tid_i, tw_key, cby, leader_cid = key

    # 2) Витягуємо всі watch'і групи
    try:
        statuses = STATUS_PRESETS.get(status_key or "", None)
        all_items = load_group_items(tid_i, tw_key, cby, statuses=statuses)
    except Exception as e:
        log.exception("load_group_items failed: %s", e)
        all_items = []

    if not all_items:
        await cb.answer("Група порожня", show_alert=True)
        return

    # 3) Пагінація
    page_items, page, total_pages = paginate_items(all_items, page, PAGE_SIZE)

    # 4) Підготовка мап (шаблони, назви каналів, owner-и)
    templates_map = load_templates_map()

    cids: List[int] = [cid_i for _, cid_i, _, _, _ in all_items if cid_i]

    channel_names_map: Dict[int, str] = {}
    owners_map: Dict[int, str] = {}
    if cids:
        channel_names_map = get_titles_by_channel_ids(cids) or {}
        owners_map = get_owners_by_channel_ids(cids) or {}

    # owner у першому рядку таблиці (і в заголовку повідомлення)
    owner_for_header = "—"
    try:
        if cids:
            first_cid = cids[0]
            owner_for_header = owners_map.get(
                first_cid,
                channel_names_map.get(first_cid, "—"),
            )
    except Exception:
        pass

    # 5) Таблиця
    table_block = build_group_table(
        all_items,
        templates_map=templates_map,
        channel_titles=channel_names_map,
        owner_display=owner_for_header,
    )

    # 6) Клавіатура для поточної сторінки
    kb = build_group_keyboard(
        page_items=page_items,
        leader_wid=leader_wid,
        page=page,
        total_pages=total_pages,
        status_to_emoji=status_to_emoji,
        get_title_for_tpl=lambda tpl_id: short_title(
            templates_map.get(tpl_id, {}).get("title"),
            tpl_id,
        ),
        status_key=status_key,
    )

    # Back
    back_cb = "menu:list_active"
    if status_key:
        back_cb = f"menu:list_active:{status_key}"
    kb.row(
        InlineKeyboardButton(
            text="🔍 Похожие посты (группа)",
            callback_data=f"watch:group_similar:{leader_wid}",
        )
    )
    kb.row(InlineKeyboardButton(text="⬅️ Back", callback_data=back_cb))

    # 7) Заголовок повідомлення
    tw_txt = fmt_tw_end_human(tw_key)
    header = f"Вотч для {owner_for_header}, час вікна до {tw_txt}"
    if status_key == "pending":
        header += " — активний"
    elif status_key == "matched":
        header += " — відслідковуються перегляди"
    elif status_key == "expired":
        header += " — вийшов з терміну"

    text = header + "\n\n" + table_block

    try:
        await cb.message.edit_text(
            text,
            reply_markup=kb.as_markup(),
            parse_mode="Markdown",
        )
    except TelegramBadRequest:
        await cb.message.answer(
            text,
            reply_markup=kb.as_markup(),
            parse_mode="Markdown",
        )


@router.callback_query(F.data.startswith("watch:group_similar:"))
async def watch_group_similar(cb: CallbackQuery):
    """
    Показує кандидати для всієї групи вотчів (одним списком).
    """
    try:
        leader_wid = int(cb.data.split(":")[-1])
    except Exception:
        leader_wid = None

    if not leader_wid:
        await cb.answer("bad id", show_alert=True)
        return

    try:
        key = get_group_leader_key(leader_wid)
    except Exception as e:
        log.exception("get_group_leader_key failed: %s", e)
        key = None

    if not key:
        await cb.answer("Групу не знайдено", show_alert=True)
        return

    tid_i, tw_key, cby, _leader_cid = key
    try:
        items = load_group_items(tid_i, tw_key, cby, statuses=["pending", "matched"])
    except Exception as e:
        log.exception("load_group_items failed: %s", e)
        items = []

    wids = [wid for wid, _, _, _, _ in items]
    if not wids:
        await cb.answer("Вотчів у групі немає", show_alert=True)
        return

    cands = list_group_watch_candidates(wids, status=CANDIDATE_PENDING_STATUS)
    if not cands:
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Back", callback_data=f"watch:group:{leader_wid}")
        await cb.message.edit_text("Схожих постів у групі немає.", reply_markup=kb.as_markup())
        await cb.answer()
        return

    # Підготуємо довідники назв/лінків каналів
    cids = [c.get("channel_id") for c in cands if c.get("channel_id")]
    titles_map: Dict[int, str] = {}
    links_map: Dict[int, str] = {}
    if cids:
        try:
            titles_map = get_titles_by_channel_ids(list(set(cids))) or {}
            links_map = get_links_by_channel_ids(list(set(cids))) or {}
        except Exception:
            titles_map = {}
            links_map = {}

    # Групуємо кандидати за text_hash (одна кнопка на один текст)
    grouped: Dict[str, Dict[str, Any]] = {}
    for cand in cands:
        key = cand.get("text_hash") or f"id:{cand.get('id')}"
        bucket = grouped.setdefault(key, {"items": [], "repr": cand})
        bucket["items"].append(cand)

    lines = ["Схожі пости (вся група):"]
    kb = InlineKeyboardBuilder()
    idx = 1
    for key, group in grouped.items():
        cand = group["repr"]
        cid = cand.get("id")
        preview_html = _candidate_html_to_preview_html(cand.get("message_text") or "", max_visible_chars=80)

        # Канали/вотчі для цього тексту
        titles = []
        wids = []
        for item in group["items"]:
            channel_id = item.get("channel_id")
            title = titles_map.get(channel_id, f"cid={channel_id}") if channel_id else "—"
            link = links_map.get(channel_id)
            if link:
                titles.append(f"<a href=\"{html.escape(str(link))}\">{html.escape(str(title))}</a>")
            else:
                titles.append(html.escape(str(title)))
            wids.append(str(item.get("watch_id")))

        lines.append(f"Пост #{idx}")
        if preview_html:
            lines.append(f"   Прев'ю: {preview_html}")
        lines.append("   Канали:")
        for j, t in enumerate(titles, start=1):
            lines.append(f"      {j}. {t}")

        btn_title = f"Відкрити пост ({idx})"
        kb.button(text=btn_title, callback_data=f"watch:similar:view:{cid}")
        idx += 1

    kb.adjust(2)
    kb.row(InlineKeyboardButton(text="⬅️ Back", callback_data=f"watch:group:{leader_wid}"))

    await cb.message.edit_text("\n".join(lines), reply_markup=kb.as_markup(), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("watch:edit:"))
async def watch_edit(cb: CallbackQuery):
    """
    Екран редагування одного watch'а:
      - показує деталі;
      - дві кнопки: Додати пост, Змінити статус;
      - Back поки що повертає в меню активних.
    """
    try:
        wid = int(cb.data.split(":")[-1])
    except Exception:
        wid = None

    if not wid:
        await cb.answer("bad id", show_alert=True)
        return

    # 1) Тягнемо watch з БД
    try:
        watch = get_watch_by_id(wid)
    except Exception as e:
        log.exception("get_watch_by_id failed: %s", e)
        watch = None

    if not watch:
        await cb.answer("Не знайшов цей watch", show_alert=True)
        return

    (
        wid_i,
        template_id,
        status,
        time_window_end,
        created_by,
        channel_id,
        source_url,
    ) = watch

    # 2) Потрібні довідники: шаблони, назви каналів, owner (опційно)
    templates_map = load_templates_map()
    cids: List[int] = []
    if channel_id:
        try:
            cids.append(int(channel_id))
        except Exception:
            pass

    channel_names_map: Dict[int, str] = {}
    owners_map: Dict[int, str] = {}
    if cids:
        channel_names_map = get_titles_by_channel_ids(cids) or {}
        owners_map = get_owners_by_channel_ids(cids) or {}

    owner_for_header = "—"
    try:
        if cids:
            first_cid = cids[0]
            owner_for_header = owners_map.get(
                first_cid,
                channel_names_map.get(first_cid, "—"),
            )
    except Exception:
        pass

    # 3) Будуємо текст (Plain Text, без Markdown)
    text = format_single_watch(
        watch=watch,
        templates_map=templates_map,
        channel_titles=channel_names_map,
        owner_display=owner_for_header,
    )

    # 4) Кнопки: Додати пост, Змінити статус, Back
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Додати пост", callback_data=f"watch:add_post:{wid_i}")
    kb.button(text="🔄 Змінити статус", callback_data=f"watch:change_status:{wid_i}")
    kb.button(text="🔍 Похожие посты", callback_data=f"watch:similar:{wid_i}")
    kb.row(
        InlineKeyboardButton(
            text="⬅️ Back",
            callback_data="menu:list_active",
        )
    )

    try:
        await cb.message.edit_text(
            text,
            reply_markup=kb.as_markup(),
        )
    except TelegramBadRequest:
        await cb.message.answer(
            text,
            reply_markup=kb.as_markup(),
        )


@router.callback_query(F.data.startswith("watch:similar:accept:"))
async def watch_similar_accept(cb: CallbackQuery):
    try:
        cid = int(cb.data.split(":")[-1])
    except Exception:
        cid = None
    if not cid:
        await cb.answer("bad candidate", show_alert=True)
        return
    cand = get_watch_candidate(cid)
    if not cand:
        await cb.answer("кандидат не знайдений", show_alert=True)
        return

    def _read_coverage_hours() -> Optional[float]:
        mins = os.getenv("WATCH_COVERAGE_MINUTES")
        if mins:
            try:
                return float(mins) / 60.0
            except Exception:
                pass
        hrs = os.getenv("WATCH_COVERAGE_HOURS")
        if hrs:
            try:
                return float(hrs)
            except Exception:
                pass
        return (23.0 * 60.0 + 59.0) / 60.0

    ok = accept_watch_candidate(cid, coverage_hours=_read_coverage_hours())
    if not ok:
        await cb.answer("не вдалось заметчити", show_alert=True)
        return
    # Після прийняття кандидата — пишемо в таблицю (для всіх accepted з цим hash)
    if gsb:
        try:
            text_hash = cand.get("text_hash") or ""
            accepted = list_candidates_by_hash(text_hash, status="accepted") if text_hash else []
            target_wids = {c.get("watch_id") for c in accepted if c.get("watch_id")}
            if not target_wids and cand.get("watch_id"):
                target_wids = {cand.get("watch_id")}
            for wid in target_wids:
                try:
                    gsb.record_matched(int(wid))
                except Exception:
                    log.exception("watch_similar_accept: gsheets record_matched failed wid=%s", wid)
        except Exception:
            log.exception("watch_similar_accept: gsheets sync failed")
    await cb.answer("Готово, поставлено matched")
    back_wid = cand.get("watch_id")
    kb = InlineKeyboardBuilder()
    back_cb = _back_to_group_cb(back_wid)
    if back_cb:
        kb.button(text="⬅️ Back", callback_data=back_cb)
    await cb.message.edit_text("✅ Кандидат заметчено", reply_markup=kb.as_markup() if kb.buttons else None)


@router.callback_query(F.data.startswith("watch:similar:reject:"))
async def watch_similar_reject(cb: CallbackQuery):
    try:
        cid = int(cb.data.split(":")[-1])
    except Exception:
        cid = None
    if not cid:
        await cb.answer("bad candidate", show_alert=True)
        return
    cand = get_watch_candidate(cid)
    if not cand:
        await cb.answer("кандидат не знайдений", show_alert=True)
        return
    # Відхиляємо всі pending з таким самим text_hash, щоб забрати всю групу
    text_hash = cand.get("text_hash") or ""
    rejected_any = False
    if text_hash:
        for c in list_candidates_by_hash(text_hash, status="pending"):
            set_watch_candidate_status(int(c["id"]), "rejected")
            rejected_any = True
    else:
        set_watch_candidate_status(cid, "rejected")
        rejected_any = True

    await cb.answer("Відхилено")
    back_wid = cand.get("watch_id")
    kb = InlineKeyboardBuilder()
    back_cb = _back_to_group_cb(back_wid)
    if back_cb:
        kb.button(text="⬅️ Back", callback_data=back_cb)
    await cb.message.edit_text(
        "❌ Кандидати відхилено" if rejected_any else "Нема що відхиляти",
        reply_markup=kb.as_markup() if kb.buttons else None,
    )


@router.callback_query(F.data.startswith("watch:similar:view:"))
async def watch_similar_view(cb: CallbackQuery):
    try:
        cid = int(cb.data.split(":")[-1])
    except Exception:
        cid = None
    if not cid:
        await cb.answer("bad id", show_alert=True)
        return
    cand = get_watch_candidate(cid)
    if not cand:
        await cb.answer("не знайдено", show_alert=True)
        return
    wid = cand.get("watch_id")

    # Всі кандидати з тим самим text_hash (щоб показати всі канали разом; тільки pending)
    same_hash = list_candidates_by_hash(cand.get("text_hash") or "", status=CANDIDATE_PENDING_STATUS) or [cand]

    # Обмежуємо кандидати лише рамками цієї групи watch'ів
    group_wids: List[int] = []
    try:
        leader = get_group_leader_for_watch(wid) if wid else None
        leader_key = get_group_leader_key(leader) if leader else None
        if leader_key:
            tpl_id, tw_key, created_by, _ = leader_key
            group_items = load_group_items(tpl_id, tw_key, created_by)
            group_wids = [item[0] for item in group_items]
    except Exception:
        group_wids = []
    if group_wids:
        same_hash = [c for c in same_hash if c.get("watch_id") in group_wids] or [cand]

    cids = [c.get("channel_id") for c in same_hash if c.get("channel_id")]
    links_map: Dict[int, str] = {}
    titles_map: Dict[int, str] = {}
    if cids:
        try:
            titles_map = get_titles_by_channel_ids(list(set(cids))) or {}
            links_map = get_links_by_channel_ids(list(set(cids))) or {}
        except Exception:
            titles_map = {}
            links_map = {}

    raw_msg_text = cand.get("message_text") or ""
    msg_text = _sanitize_bot_api_html_fragment(raw_msg_text) or "—"
    msg_text_plain = _candidate_html_to_display_text(raw_msg_text) or "—"
    # Лінки: очікувані (з watch) та фактичні (з поста)
    expected_links = []
    try:
        expected_html = get_watch_expected_text(wid) if wid else None
        if expected_html:
            expected_links = _collect_links(expected_html)
        if not expected_links:
            expected_links = get_watch_expected_links(wid) if wid else []
    except Exception:
        expected_links = []
    cand_links = _collect_links(raw_msg_text)

    lines = [
        f"<b>Кандидат #{cid}</b>",
        f"watch_id: {html.escape(str(wid))}",
        f"Схожість: {int((cand.get('similarity') or 0)*100)}%",
        f"Створено: {html.escape(str(cand.get('created_at') or '—'))}",
        "",
        "<b>Пост:</b>",
        msg_text,
        "",
        "<b>Канали:</b>",
    ]
    for item in same_hash:
        channel_id = item.get("channel_id")
        title = titles_map.get(channel_id, f"cid={channel_id}") if channel_id else "—"
        link = links_map.get(channel_id, "") if channel_id else ""
        title_safe = html.escape(str(title))
        link_safe = html.escape(str(link)) if link else ""
        wid_i = item.get("watch_id")
        prefix = f"wid={wid_i}: " if wid_i else ""
        if link_safe:
            lines.append(f"- {prefix}<a href=\"{link_safe}\">{title_safe}</a>")
        else:
            lines.append(f"- {prefix}{title_safe}")

    lines.append("")
    lines.append("<b>Очікувані лінки:</b>")
    if expected_links:
        for l in expected_links:
            l_safe = html.escape(str(l))
            lines.append(f"- <a href=\"{l_safe}\">{l_safe}</a>")
    else:
        lines.append("- немає")

    lines.append("<b>Лінки кандидата:</b>")
    if cand_links:
        for l in cand_links:
            l_safe = html.escape(str(l))
            lines.append(f"- <a href=\"{l_safe}\">{l_safe}</a>")
    else:
        lines.append("- немає")

    text = "\n".join(lines)

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Заметчити", callback_data=f"watch:similar:accept:{cid}")
    kb.button(text="❌ Ні", callback_data=f"watch:similar:reject:{cid}")
    back_cb = _back_to_group_cb(wid)
    if back_cb:
        kb.button(text="⬅️ Back", callback_data=back_cb)
    try:
        await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except TelegramBadRequest as exc:
        if "can't parse entities" not in str(exc):
            raise
        log.warning("watch_similar_view: html fallback cid=%s wid=%s err=%s", cid, wid, exc)
        fallback_lines = list(lines)
        fallback_lines[6] = html.escape(msg_text_plain)
        await cb.message.edit_text(
            "\n".join(fallback_lines),
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("watch:similar:"))
async def watch_similar_list(cb: CallbackQuery):
    """
    Показує список схожих постів для watch.
    """
    try:
        wid = int(cb.data.split(":")[-1])
    except Exception:
        wid = None

    if not wid:
        await cb.answer("bad id", show_alert=True)
        return

    cands = list_watch_candidates(wid, status=CANDIDATE_PENDING_STATUS)
    if not cands:
        await cb.message.edit_text("Схожих постів поки немає.", reply_markup=_edit_back_kb(wid).as_markup())
        await cb.answer()
        return

    # Підтягуємо назви/лінки каналів для кнопок/списку
    cids = [c.get("channel_id") for c in cands if c.get("channel_id")]
    titles_map: Dict[int, str] = {}
    links_map: Dict[int, str] = {}
    if cids:
        try:
            titles_map = get_titles_by_channel_ids(list(set(cids))) or {}
            links_map = get_links_by_channel_ids(list(set(cids))) or {}
        except Exception:
            titles_map = {}
            links_map = {}

    kb = InlineKeyboardBuilder()
    lines = ["Схожі пости:"]
    for idx, cand in enumerate(cands, start=1):
        cid = cand.get("id")
        channel_id = cand.get("channel_id")
        title = titles_map.get(channel_id, f"cid={channel_id}") if channel_id else "—"
        link = links_map.get(channel_id, "")
        title_safe = html.escape(str(title))
        link_safe = html.escape(str(link)) if link else ""
        lines.append(f"Пост #{idx}")
        lines.append("   Канали:")
        if link_safe:
            lines.append(f"      1. <a href=\"{link_safe}\">{title_safe}</a>")
        else:
            lines.append(f"      1. {title_safe}")
        kb.button(text=f"Відкрити пост ({idx})", callback_data=f"watch:similar:view:{cid}")
    kb.adjust(2)
    back_cb = _back_to_group_cb(wid)
    if back_cb:
        kb.row(InlineKeyboardButton(text="⬅️ Back", callback_data=back_cb))

    await cb.message.edit_text("\n".join(lines), reply_markup=kb.as_markup(), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("watch:change_status:"))
async def watch_change_status(cb: CallbackQuery, state: FSMContext):
    """
    Крок 1: користувач натиснув 'Змінити статус' для конкретного wid.
    - Переводимо цей watch у pending (через service).
    - Просимо ввести новий час закінчення вікна у форматі HH:MM.
    - Запам'ятовуємо wid у FSM і чекаємо повідомлення.
    """
    try:
        wid = int(cb.data.split(":")[-1])
    except Exception:
        wid = None

    if not wid:
        await cb.answer("bad id", show_alert=True)
        return

    ok = set_watch_status_pending(wid)
    if not ok:
        await cb.answer("Не зміг змінити статус", show_alert=True)
        return

    await state.set_state(EditWatch.time_window)
    await state.update_data(edit_wid=wid)

    kb = _edit_back_kb(wid)

    await cb.message.edit_text(
        f"Статус watch #{wid} змінено на pending.\n"
        f"Введи новий час закінчення вікна СЬОГОДНІ у форматі HH:MM, наприклад 23:30.",
        reply_markup=kb.as_markup(),
    )


@router.message(EditWatch.time_window)
async def edit_watch_time_window(m: Message, state: FSMContext):
    """
    Крок 2: користувач ввів новий час HH:MM для вже існуючого watch'а.
    - парсимо час;
    - перевіряємо, що в майбутньому;
    - оновлюємо time_window_start/time_window_end для wid (через service);
    - показуємо підтвердження.
    """
    data = await state.get_data()
    wid = data.get("edit_wid")
    kb = _edit_back_kb(wid) if wid else None

    text = (m.text or "").strip()
    m_time = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text)

    if not m_time:
        await m.answer(
            "Введи час у форматі HH:MM, наприклад 23:30.",
            reply_markup=kb.as_markup() if kb else None,
        )
        return

    def _try_int_local(s: str) -> Optional[int]:
        try:
            return int(str(s).strip())
        except Exception:
            return None

    h = _try_int_local(m_time.group(1))
    mi = _try_int_local(m_time.group(2))
    s_val = _try_int_local(m_time.group(3) or "0")
    if (
        h is None
        or mi is None
        or s_val is None
        or not (0 <= h <= 23)
        or not (0 <= mi <= 59)
        or not (0 <= s_val <= 59)
    ):
        await m.answer(
            "Невірний час. Приклад: 23:30.",
            reply_markup=kb.as_markup() if kb else None,
        )
        return

    now = msk_now()
    tw_end_dt = now.replace(hour=h, minute=mi, second=0, microsecond=0)

    if tw_end_dt <= now:
        await m.answer(
            "Час закінчення має бути пізніше за поточний. Вкажи інший час.",
            reply_markup=kb.as_markup() if kb else None,
        )
        return

    delta = tw_end_dt - now
    mins = int(delta.total_seconds() // 60)
    if mins <= 0:
        await m.answer(
            "Вікно має бути хоча б кілька хвилин. Вкажи інший час.",
            reply_markup=kb.as_markup() if kb else None,
        )
        return

    if not wid:
        await m.answer("Не знайшов поточний watch. Почни редагування заново.")
        await state.clear()
        return

    tw_start_dt = now
    tw_start = tw_start_dt.strftime("%Y-%m-%d %H:%M:%S")
    tw_end = tw_end_dt.strftime("%Y-%m-%d %H:%M:%S")

    ok = update_watch_time_window(int(wid), tw_start, tw_end)
    if not ok:
        await m.answer(
            "Не зміг оновити вікно. Спробуй ще раз пізніше.",
            reply_markup=kb.as_markup() if kb else None,
        )
        return

    await state.clear()

    await m.answer(
        f"Вікно для watch #{wid} оновлено.\n"
        f"Нове вікно: {mins} хв, до {tw_end}",
        reply_markup=main_menu_kb(),
    )


# ---------- ДОДАТИ ПОСТ (емуляція matched) ----------


@router.callback_query(F.data.startswith("watch:add_post:"))
async def watch_add_post_start(cb: CallbackQuery, state: FSMContext):
    """
    Крок 1: користувач натиснув 'Додати пост' для конкретного wid.
    - Просимо переслати/дати сам пост (forward/reply).
    - Запам'ятовуємо wid у FSM (edit_wid_source).
    """
    try:
        wid = int(cb.data.split(":")[-1])
    except Exception:
        wid = None

    if not wid:
        await cb.answer("bad id", show_alert=True)
        return

    await state.set_state(EditWatch.source_input)
    await state.update_data(edit_wid_source=wid)

    kb = _edit_back_kb(wid)

    await cb.message.edit_text(
        f"Додати пост для watch #{wid}.\n"
        f"Перешли повідомлення з постом з каналу або зроби reply на нього тут.",
        reply_markup=kb.as_markup(),
    )


@router.message(EditWatch.source_input)
async def watch_add_post_receive(m: Message, state: FSMContext):
    """
    Крок 2: отримуємо пост (forward або reply) і емітуємо matched для цього watch'а.
    """
    data = await state.get_data()
    wid = data.get("edit_wid_source")
    if not wid:
        await m.answer("Не знайшов поточний watch. Почни редагування заново.")
        await state.clear()
        return

    kb = _edit_back_kb(wid)

    # беремо саме повідомлення-джерело:
    # - якщо користувач зробив reply на пост → m.reply_to_message
    # - якщо просто переслав пост → саме m
    src_msg = m.reply_to_message or m
    if not src_msg:
        await m.answer(
            "Не бачу повідомлення з постом. Перешли, будь ласка, сам пост з каналу "
            "або зроби reply на нього тут.",
            reply_markup=kb.as_markup(),
        )
        return

    try:
        ok = await manual_match_watch_from_message(int(wid), src_msg)
    except Exception as e:
        log.exception("watch_add_post_receive: manual_match failed wid=%s: %s", wid, e)
        ok = False

    if not ok:
        await m.answer(
            "Не вдалось привʼязати цей пост до watch. Перевір, що це пост з того самого каналу "
            "і що для watch заданий коректний source_url.",
            reply_markup=kb.as_markup(),
        )
        return

    await state.clear()

    await m.answer(
        f"Для watch #{wid} пост привʼязано як matched.\n"
        f"Він буде оброблятися як звичайний матч (views/deleted/Excel).",
        reply_markup=main_menu_kb(),
    )
