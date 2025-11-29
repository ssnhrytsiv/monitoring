from typing import Optional, List, Any, Dict, Tuple
import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from app.bot.keyboards import main_menu_kb
from app.services.posts_watch_result_db import raw_connection, insert_watch_event
from app.services.time_utils import msk_now
from app.bot.services.templates_repo import load_templates_map
from app.bot.services.channels_repo import get_owners_by_channel_ids, get_links_by_channel_ids
from app.bot.services.watches_repo import list_active_watches, group_active

router = Router()
log = logging.getLogger("bot_active_watches")


def _fmt_tw_end(s: Optional[str]) -> str:
    if not s:
        return "—"
    try:
        dt = datetime.strptime(str(s), "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d.%m %H:%M")
    except Exception:
        return str(s)

def _short_title(title: Optional[Any], tid: Optional[int]) -> str:
    if title is None:
        return f"tpl#{tid}" if tid else "—"
    t = str(title).strip()
    if not t:
        return f"tpl#{tid}" if tid else "—"
    return t.split()[0]


@router.callback_query(F.data == "watch:noop")
async def watch_noop(cb: CallbackQuery):
    await cb.answer()


@router.callback_query(F.data.startswith("watch:channels:"))
async def watch_channels(cb: CallbackQuery):
    leader_wid = None
    try:
        leader_wid = int(cb.data.split(":")[-1])
    except Exception:
        leader_wid = None
    if not leader_wid:
        await cb.answer("bad id", show_alert=True)
        return

    conn = raw_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            "SELECT template_id, time_window_end, created_by FROM watch_posts WHERE id=?",
            (leader_wid,),
        )
        row = cur.fetchone()
        if not row:
            await cb.answer("Не знайдено", show_alert=True)
            return
        tid, tw_end, cby = row
        tid_i = int(tid) if tid is not None else None
        tw_end_s = str(tw_end) if tw_end is not None else None
    except Exception:
        await cb.answer("Не зміг прочитати групу", show_alert=True)
        return

    try:
        cur.execute(
            """
            SELECT id, channel_id
            FROM watch_posts
            WHERE template_id IS ?
              AND time_window_end IS ?
              AND created_by IS ?
              AND status IN ('pending','matched')
            """,
            (tid_i, tw_end_s, cby),
        )
        items = cur.fetchall()
    except Exception:
        items = []

    cids: List[int] = []
    for _, cid in items:
        try:
            ci = int(cid)
            if ci:
                cids.append(ci)
        except Exception:
            continue

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
    leader_wid = None
    try:
        leader_wid = int(cb.data.split(":")[-1])
    except Exception:
        leader_wid = None
    if not leader_wid:
        await cb.answer("bad id", show_alert=True)
        return

    conn = raw_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            "SELECT template_id, time_window_end, created_by FROM watch_posts WHERE id=?",
            (leader_wid,),
        )
        row = cur.fetchone()
        if not row:
            await cb.answer("Не знайдено", show_alert=True)
            return
        tid, tw_end, cby = row
        tid_i = int(tid) if tid is not None else None
        tw_end_s = str(tw_end) if tw_end is not None else None
    except Exception:
        await cb.answer("Не зміг прочитати групу", show_alert=True)
        return

    try:
        now_s = msk_now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            """
            UPDATE watch_posts
            SET status='cancelled', updated_at=?
            WHERE template_id IS ?
              AND time_window_end IS ?
              AND created_by IS ?
              AND status IN ('pending','matched')
            """,
            (now_s, tid_i, tw_end_s, cby),
        )
        conn.commit()
    except Exception:
        await cb.answer("Не зміг скасувати", show_alert=True)
        return

    try:
        insert_watch_event(leader_wid, "cancelled", {"watch_id": leader_wid})
    except Exception:
        pass

    await cb.answer("Скасовано", show_alert=False)
    await menu_list_active(cb)


@router.callback_query(F.data == "menu:list_active")
async def menu_list_active(cb: CallbackQuery):
    templates_map = load_templates_map()

    try:
        rows = list_active_watches(cb.from_user.id)
    except Exception as e:
        log.exception(f"menu:list_active failed: {e}")
        rows = []

    if not rows:
        try:
            await cb.message.edit_text("Активних watch немає.", reply_markup=main_menu_kb())
        except TelegramBadRequest:
            await cb.message.answer("Активних watch немає.", reply_markup=main_menu_kb())
        return

    groups = group_active(rows)

    # 🔍 ДІАГНОСТИЧНИЙ ЛОГ ГРУПУВАННЯ
    log.info("list_active: total rows=%s, groups=%s", len(rows), len(groups))
    for key, items in groups.items():
        tid_i, tw_end_s, cby = key
        wids = [wid for wid, cid in items]
        cids = [cid for wid, cid in items]
        log.info(
            "list_active: group key=%r (tpl=%r, tw_end=%r, created_by=%r), wids=%s, cids=%s",
            key, tid_i, tw_end_s, cby, wids, cids,
        )
    # 🔍 КІНЕЦЬ ЛОГУ

    ordered_keys = sorted(groups.keys(), key=lambda k: max(int(x[0]) for x in groups[k]), reverse=True)

    lines: List[str] = []
    kb = InlineKeyboardBuilder()

    for key in ordered_keys[:50]:
        tid_i, tw_end_s, cby = key
        items = groups[key]
        leader_wid = max(int(x[0]) for x in items)
        cids = [cid for _, cid in items if cid]

        tpl_title = templates_map.get(tid_i, {}).get("title") if tid_i else None
        title_short = _short_title(tpl_title, tid_i)

        tw_txt = _fmt_tw_end(tw_end_s)
        chans_n = len(items)

        owners_map = get_owners_by_channel_ids(cids)
        owners = []
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
            owner_txt = owners[0] + f" +{len(owners)-1}"

        lines.append(f"{leader_wid} | {title_short} | {chans_n} | {owner_txt} | до {tw_txt}")

        kb.button(text=str(leader_wid), callback_data="watch:noop")
        kb.button(text=f"📎 {chans_n}", callback_data=f"watch:channels:{leader_wid}")
        kb.button(text="❌ Cancel", callback_data=f"watch:cancel:{leader_wid}")

    kb.adjust(3)
    kb.row(InlineKeyboardButton(text="⬅️ Back", callback_data="menu:home"))

    text = "№ | Template | Channels | Owner | Window\n\n" + "\n".join(lines)

    try:
        await cb.message.edit_text(text, reply_markup=kb.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=kb.as_markup())