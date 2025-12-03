from typing import List, Any, Dict
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from app.bot.keyboards import main_menu_kb
from app.bot.services.templates_repo import load_templates_map
from app.bot.services.channels_repo import get_owners_by_channel_ids
from app.bot.services.watches_repo import list_active_watches, group_active

router = Router()
log = logging.getLogger("bot_active_watches.menu")


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
    Форматування часу вікна, який уже приходить з watches_repo/group_active
    у вигляді рядка 'YYYY-MM-DD HH:MM:SS' або None.
    Тут можемо виводити скорочено (дата+час) або як є.
    """
    if not s:
        return "—"
    # Можна залишити як є, щоб не тягнути datetime тут
    return str(s)


@router.callback_query(F.data == "menu:list_active")
async def menu_list_active(cb: CallbackQuery):
    """
    Показує список активних watch-груп користувача.

    - бере сирі рядки через list_active_watches(user_id)
    - групує їх через group_active
    - будує коротку табличку:
        № | Template | Channels | Owner | Window
    - додає кнопки:
        [leader_wid] [owner_txt] [❌ Cancel]
    """
    templates_map = load_templates_map()

    try:
        rows = list_active_watches(cb.from_user.id)
    except Exception as e:
        log.exception(f"menu_list_active failed: {e}")
        rows = []

    if not rows:
        try:
            await cb.message.edit_text(
                "Активних watch немає.",
                reply_markup=main_menu_kb(),
            )
        except TelegramBadRequest:
            await cb.message.answer(
                "Активних watch немає.",
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

    lines: List[str] = []
    kb = InlineKeyboardBuilder()

    for key in ordered_keys[:50]:
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
        kb.button(text=owner_txt, callback_data=f"watch:group:{leader_wid}")
        kb.button(text="❌ Cancel", callback_data=f"watch:cancel:{leader_wid}")

    kb.adjust(3)
    kb.row(InlineKeyboardButton(text="⬅️ Back", callback_data="menu:home"))

    text = "№ | Template | Channels | Owner | Window\n\n" + "\n".join(lines)

    try:
        await cb.message.edit_text(text, reply_markup=kb.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=kb.as_markup())