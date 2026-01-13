from typing import List, Any, Dict, Optional, Tuple
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from app.bot.keyboards import main_menu_kb
from app.bot.services.templates_repo import load_templates_map
from app.bot.services.channels_repo import get_owners_by_channel_ids
from app.DAL.watch_posts_operations import list_active_watches, group_active

router = Router()
log = logging.getLogger("bot_active_watches.menu")

STATUS_PRESETS = {
    "pending": {
        "title": "Активні",
        "statuses": ["pending"],
    },
    "matched": {
        "title": "Відслідковуються перегляди",
        "statuses": ["matched"],
    },
    "expired": {
        "title": "Вийшли з терміну",
        "statuses": ["expired"],
    },
}

LIST_PAGE_SIZE = 12


def _short_title(title: Any, tid: int | None) -> str:
    """
    Скорочений заголовок шаблону: перше слово, або tpl#<id>, якщо назви немає.
    """
    if title is None:
        return f"tpl#{tid}" if tid else "—"
    t = str(title).strip()
    if not t:
        return f"tpl#{tid}" if tid else "—"
    return t.split()[0]


def _fmt_tw_end(s: str | None) -> str:
    """
    Форматування часу вікна, який уже приходить з watch_posts_operations/group_active
    у вигляді рядка 'YYYY-MM-DD HH:MM:SS' або None.
    Тут можемо виводити скорочено (дата+час) або як є.
    """
    if not s:
        return "—"
    # Можна залишити як є, щоб не тягнути datetime тут
    return str(s)


def _status_key_from_cb(cb: CallbackQuery) -> Optional[str]:
    parts = cb.data.split(":") if cb.data else []
    if len(parts) >= 3:
        key = parts[2]
        if key in STATUS_PRESETS:
            return key
    return None


def _parse_status_and_page(cb: CallbackQuery, explicit_key: Optional[str]) -> Tuple[Optional[str], int]:
    """
    Розбирає status_key і page з callback_data типу:
      menu:list_active
      menu:list_active:<status_key>
      menu:list_active:<status_key>:<page>
    """
    if explicit_key:
        return explicit_key, 1
    parts = cb.data.split(":") if cb.data else []
    status = None
    page = 1
    for p in parts[2:]:
        if p in STATUS_PRESETS:
            status = p
        else:
            try:
                page = max(1, int(p))
            except Exception:
                continue
    return status, page


@router.callback_query(F.data.startswith("menu:list_active"))
async def menu_list_active(cb: CallbackQuery, status_key: Optional[str] = None, page: Optional[int] = None):
    """
    Показує список активних watch-груп користувача (з фільтром за статусом).

    - бере сирі рядки через list_active_watches(user_id)
    - групує їх через group_active
    - будує коротку табличку:
        № | Template | Channels | Owner | Window
    - додає кнопки:
        [leader_wid] [owner_txt] [❌ Cancel]
    """
    # якщо не передали явно — пробуємо взяти з callback_data; якщо нема, показуємо меню вибору
    status_key, page_parsed = _parse_status_and_page(cb, status_key)
    if page is None:
        page = page_parsed or 1
    preset = STATUS_PRESETS.get(status_key or "", None)
    if not preset:
        kb = InlineKeyboardBuilder()
        kb.button(text="Активні", callback_data="menu:list_active:pending")
        kb.button(text="Відслідковуються перегляди", callback_data="menu:list_active:matched")
        kb.button(text="Вийшли з терміну", callback_data="menu:list_active:expired")
        kb.adjust(1)
        kb.row(InlineKeyboardButton(text="⬅️ Back", callback_data="menu:home"))
        text = (
            "Виберіть, котрий тип вотчу ви хочете бачити, "
            "активні чи ті що вийшли з терміну"
        )
        try:
            await cb.message.edit_text(text, reply_markup=kb.as_markup())
        except TelegramBadRequest:
            await cb.message.answer(text, reply_markup=kb.as_markup())
        return

    templates_map = load_templates_map()

    try:
        rows = list_active_watches(cb.from_user.id, statuses=preset["statuses"])
    except Exception as e:
        log.exception(f"menu_list_active failed: {e}")
        rows = []

    if not rows:
        try:
            await cb.message.edit_text(
                f"{preset['title']}: записів немає.",
                reply_markup=main_menu_kb(),
            )
        except TelegramBadRequest:
            await cb.message.answer(
                f"{preset['title']}: записів немає.",
                reply_markup=main_menu_kb(),
            )
        return

    groups = group_active(rows)

    # 🔍 ДІАГНОСТИЧНИЙ ЛОГ ГРУПУВАННЯ (можеш вимкнути, коли перестане бути потрібен)
    log.info("list_active: total rows=%s, groups=%s", len(rows), len(groups))
    for key, items in groups.items():
        tid_i, tw_end_s, cby = key
        wids = [wid for wid, cid in items]
        cids = [cid for wid, cid in items]
        log.info(
            "list_active: group key=%r (tpl=%r, tw_end=%r, created_by=%r), wids=%s, cids=%s",
            key,
            tid_i,
            tw_end_s,
            cby,
            wids,
            cids,
        )
    # 🔍 КІНЕЦЬ ЛОГУ

    # Сортуємо групи за максимальним id вотча у групі (спадаюче)
    ordered_keys = sorted(
        groups.keys(),
        key=lambda k: max(int(x[0]) for x in groups[k]),
        reverse=True,
    )

    total_items = len(ordered_keys)
    total_pages = max(1, (total_items + LIST_PAGE_SIZE - 1) // LIST_PAGE_SIZE)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start = (page - 1) * LIST_PAGE_SIZE
    end = start + LIST_PAGE_SIZE
    page_keys = ordered_keys[start:end]

    lines: List[str] = []
    kb = InlineKeyboardBuilder()

    for key in page_keys:
        tid_i, tw_end_s, cby = key
        items = groups[key]

        # leader_wid — максимальний id у групі
        leader_wid = max(int(x[0]) for x in items)
        cids = [cid for _, cid in items if cid]

        tpl_title = templates_map.get(tid_i, {}).get("title") if tid_i else None
        title_short = _short_title(tpl_title, tid_i)

        tw_txt = _fmt_tw_end(tw_end_s)
        chans_n = len(items)

        owners_map: Dict[int, str] = get_owners_by_channel_ids(cids)
        owners: List[str] = []
        seen = set()
        for cid in cids:
            o = owners_map.get(cid)
            if o and o not in seen:
                seen.add(o)
                owners.append(o)

        if not owners:
            owner_txt = "—"
        elif len(owners) == 1:
            owner_txt = owners[0]
        else:
            owner_txt = owners[0] + f" +{len(owners) - 1}"

        lines.append(
            f"{leader_wid} | {title_short} | {chans_n} | {owner_txt} | до {tw_txt}"
        )

        # Кнопки для цієї групи:
        kb.button(text=str(leader_wid), callback_data="watch:noop")
        kb.button(
            text=owner_txt,
            callback_data=f"watch:group:{leader_wid}:{status_key}",
        )
        kb.button(text="❌ Cancel", callback_data=f"watch:cancel:{leader_wid}:{status_key}")

    kb.adjust(3)

    # навігація
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"menu:list_active:{status_key}:{page-1}"))
    else:
        nav_row.append(InlineKeyboardButton(text=" ", callback_data="watch:noop"))
    nav_row.append(InlineKeyboardButton(text=f"Page {page}/{total_pages}", callback_data="watch:noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"menu:list_active:{status_key}:{page+1}"))
    else:
        nav_row.append(InlineKeyboardButton(text=" ", callback_data="watch:noop"))
    kb.row(*nav_row)

    kb.row(InlineKeyboardButton(text="⬅️ Back", callback_data="menu:list_active"))

    text = (
        f"{preset['title']} — № | Template | Channels | Owner | Window\n\n"
        + "\n".join(lines)
    )

    try:
        await cb.message.edit_text(text, reply_markup=kb.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=kb.as_markup())
