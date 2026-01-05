from __future__ import annotations

import math
import logging
from typing import List, Dict, Any
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select, func

from admin_bot.db import models as m
from admin_bot.db.session import SessionLocal
from admin_bot.services import admins as svc_admins
from admin_bot.services import networks as svc_networks
from admin_bot.bot.keyboards import page_kb
from admin_bot.bot.states import NetworkFlow
from admin_bot.utils.messages import extract_links_from_message
from admin_bot.services.networks import channel_hyperlink
from app.services import account_pool
from app.services import channel_db
from telethon.tl.functions.contacts import BlockRequest
from telethon.tl.functions.messages import DeleteHistoryRequest
from admin_bot.bot.keyboards import main_menu_kb
from app.services import channel_db

router = Router()
log = logging.getLogger("admin_bot.bot.admins_menu")


async def _edit_text_safe(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup):
    try:
        await cb.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return False
        raise
    return True


def _db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _load_admins():
    db = next(_db())
    admins = svc_admins.list_admins(db)
    return sorted(admins, key=lambda a: (a.display or "").lower())


def _admin_label(a) -> str:
    disp = a.display or ""
    uname = f"@{a.username}" if a.username else ""
    return (f"{disp} {uname}".strip()) or f"id={a.id}"


def _render_admin_view(msg, admin, nets, stats):
    bots = channel_db.list_bot_links(owner_display=admin.display, owner_username=admin.username)
    bots_count = len(bots)
    # підрахунок каналів по сітках
    net_lines = []
    total_channels = 0
    if nets:
        db = next(_db())
        counts = {}
        for n in nets:
            cnt = db.execute(
                select(func.count(m.NetworkChannel.id)).where(m.NetworkChannel.network_id == n.id)
            ).scalar() or 0
            counts[n.id] = cnt
            total_channels += cnt
            net_lines.append(f"• {n.name} ({cnt})")
        if len(nets) > 1:
            net_lines.append(f"Сумарно: {total_channels}")

    lines = [
        f"Адмін: {_admin_label(admin)}",
        f"Сіток: {len(nets)}",
        f"Боти: {bots_count}",
        f"Сумарна ціна: {stats['price_sum']:.2f}" if stats["price_sum"] is not None else "Сумарна ціна: —",
        f"Середні перегляди (сума 30д): {stats['avg_views_30d_sum'] or 0}",
    ]
    if nets:
        lines.append("Сітки:")
        if net_lines:
            lines.extend(net_lines)
        else:
            for n in nets:
                lines.append(f"• {n.name}")
    else:
        lines.append("Сіток поки немає.")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Посмотреть каналы", callback_data=f"admin_net_edit:{admin.id}"),
                InlineKeyboardButton(text="Посмотреть ботов", callback_data=f"admin_bots:{admin.id}"),
            ],
            [InlineKeyboardButton(text="Оновити список каналів", callback_data=f"refresh_channels:{admin.id}")],
            [InlineKeyboardButton(text="🗑 Видалити адміна", callback_data=f"admin_delete_confirm:{admin.id}")],
            [
                InlineKeyboardButton(text="⬅️ До списку", callback_data="show_admins"),
                InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu"),
            ],
        ]
    )
    return msg.edit_text("\n".join(lines), reply_markup=kb)


ADMINS_PER_PAGE = 30
ADMINS_PER_ROW = 2
NETS_PER_ROW = 4
BOTS_PER_PAGE = 30


def _current_page_from_markup(msg) -> int:
    if msg and msg.reply_markup:
        for row in msg.reply_markup.inline_keyboard:
            for btn in row:
                if btn.text and "/" in btn.text:
                    try:
                        return int(btn.text.split("/")[0]) - 1
                    except Exception:
                        return 0
    return 0


def _build_admins_kb(admins, page: int = 0, per_page: int = 10):
    total_pages = max(1, math.ceil(len(admins) / per_page))
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    subset = admins[start:start + per_page]
    buttons = []
    row = []
    for a in subset:
        row.append(InlineKeyboardButton(text=_admin_label(a), callback_data=f"admins_item_{a.id}"))
        if len(row) == ADMINS_PER_ROW:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    nav = page_kb(page, total_pages, prefix="admins_page", menu_cb="admins_back_to_menu")
    return InlineKeyboardMarkup(inline_keyboard=buttons + nav.inline_keyboard)


@router.callback_query(F.data == "show_admins")
async def cb_show_admins(cb: CallbackQuery, state: FSMContext):
    admins = _load_admins()
    if not admins:
        await cb.message.answer(
            "Список адмінів порожній.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")]]
            ),
        )
        await cb.answer()
        return
    kb = _build_admins_kb(admins, page=0, per_page=ADMINS_PER_PAGE)
    await cb.message.edit_text("Адміни:", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "admins_back_to_menu")
async def cb_admins_back_to_menu(cb: CallbackQuery):
    try:
        await cb.message.edit_text(
            "Адмін-бот:\n"
            "• /add_admin — додати себе (або tg_id аргументом)\n"
            "• /admins — список адмінів",
            reply_markup=main_menu_kb(),
        )
    except TelegramBadRequest:
        # якщо не вдалося відредагувати, надсилаємо нове повідомлення
        await cb.message.answer(
            "Адмін-бот:\n"
            "• /add_admin — додати себе (або tg_id аргументом)\n"
            "• /admins — список адмінів",
            reply_markup=main_menu_kb(),
        )
    await cb.answer()


@router.callback_query(F.data.startswith("admin_net_show:"))
async def cb_admin_net_show(cb: CallbackQuery):
    try:
        net_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    db = next(_db())
    net = db.execute(select(m.Network).where(m.Network.id == net_id)).scalar_one_or_none()
    if not net:
        await cb.answer("Сітку не знайдено", show_alert=True)
        return
    pages, total = _net_channel_pages(db, net.id, net.name)
    text, kb = _render_net_page(net, pages, 0)
    await _edit_text_safe(cb, text, kb)
    await cb.answer()


def _net_channel_pages(db, net_id: int, net_name: str, per_page: int = 25) -> tuple[list[str], int]:
    rows = db.execute(
        select(m.Channel)
        .join(m.NetworkChannel, m.NetworkChannel.channel_id == m.Channel.channel_id)
        .where(m.NetworkChannel.network_id == net_id)
        .order_by(m.Channel.title)
    ).scalars().all()
    total = len(rows)
    if not rows:
        return [f"Сітка: {net_name} (0)\n(поки без каналів)"], 0
    pages = []
    cur = []
    for ch in rows:
        cur.append(f"• {channel_hyperlink(db, ch)}")
        if len(cur) >= per_page:
            pages.append("\n".join([f"Сітка: {net_name} ({total})", "Канали:"] + cur))
            cur = []
    if cur:
        pages.append("\n".join([f"Сітка: {net_name} ({total})", "Канали:"] + cur))
    return pages, total


def _render_net_page(net: m.Network, pages: list[str], page_idx: int):
    page_idx = max(0, min(page_idx, len(pages) - 1))
    text = pages[page_idx]
    nav = []
    if len(pages) > 1:
        prev_cb = f"admin_net_show_page:{net.id}:{(page_idx - 1) % len(pages)}"
        next_cb = f"admin_net_show_page:{net.id}:{(page_idx + 1) % len(pages)}"
        nav.append([
            InlineKeyboardButton(text="⬅️", callback_data=prev_cb),
            InlineKeyboardButton(text=f"{page_idx+1}/{len(pages)}", callback_data="noop"),
            InlineKeyboardButton(text="➡️", callback_data=next_cb),
        ])
    buttons = []
    if net.name != "Основные каналы":
        buttons.append([InlineKeyboardButton(text="🔄 Оновити сітку", callback_data=f"admin_net_refresh:{net.id}")])
        buttons.append([InlineKeyboardButton(text="🗑 Видалити сітку", callback_data=f"admin_net_delete:{net.id}")])
    if nav:
        buttons += nav
    buttons.append([
        InlineKeyboardButton(text="⬅️ До сіток", callback_data=f"admin_net_edit:{net.admin_id}"),
        InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu"),
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    return text, kb


@router.callback_query(F.data.startswith("admin_net_show_page:"))
async def cb_admin_net_show_page(cb: CallbackQuery):
    try:
        _, net_id, page = cb.data.split(":", 2)
        net_id = int(net_id)
        page = int(page)
    except Exception:
        await cb.answer()
        return
    db = next(_db())
    net = db.execute(select(m.Network).where(m.Network.id == net_id)).scalar_one_or_none()
    if not net:
        await cb.answer("Сітку не знайдено", show_alert=True)
        return
    pages, total = _net_channel_pages(db, net.id, net.name)
    text, kb = _render_net_page(net, pages, page)
    await _edit_text_safe(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.startswith("admin_net_delete:"))
async def cb_admin_net_delete(cb: CallbackQuery):
    try:
        net_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    db = next(_db())
    res = svc_networks.delete_network(db, net_id)
    if not res["deleted"]:
        await cb.answer("Сітку не знайдено", show_alert=True)
        return
    admin_id = res["admin_id"] or 0
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ До сіток", callback_data=f"admin_net_edit:{admin_id}")],
            [InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")],
        ]
    )
    await cb.message.edit_text(
        f"Сітку '{res['name']}' видалено.\nКаналів переведено в 'Без сітки': {res['moved']}.",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("admin_net_refresh:"))
async def cb_admin_net_refresh(cb: CallbackQuery, state: FSMContext):
    try:
        net_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    db = next(_db())
    net = db.execute(select(m.Network).where(m.Network.id == net_id)).scalar_one_or_none()
    if not net:
        await cb.answer("Сітку не знайдено", show_alert=True)
        return
    await state.update_data(
        net_id=net.id,
        net_name=net.name,
        net_admin_id=net.admin_id,
        net_move_existing=True,
    )
    await state.set_state(NetworkFlow.waiting_links)
    await cb.message.edit_text(
        f"Сітка: {net.name}\nНадішли посилання, щоб оновити/перенести канали у цю сітку.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ До сіток", callback_data=f"admin_net_edit:{net.admin_id}")],
                [InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")],
            ]
        ),
        disable_web_page_preview=True,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("admin_orphan:"))
async def cb_admin_orphan(cb: CallbackQuery):
    try:
        admin_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    db = next(_db())
    svc_networks.move_orphans_to_primary(db, admin_id)
    await cb.answer("Канали перенесені в 'Основные каналы'", show_alert=True)
@router.callback_query(F.data.in_(["admins_page_prev", "admins_page_next"]))
async def cb_admins_page_nav(cb: CallbackQuery):
    admins = _load_admins()
    if not admins:
        await cb.answer("Список порожній")
        return
    total_pages = max(1, math.ceil(len(admins) / ADMINS_PER_PAGE))
    # поточну сторінку беремо з кнопки пагінації (текст типу 1/3)
    cur_page = _current_page_from_markup(cb.message)
    old_page = cur_page
    if cb.data == "admins_page_prev":
        cur_page = (cur_page - 1) % total_pages
    else:
        cur_page = (cur_page + 1) % total_pages
    if cur_page == old_page:
        await cb.answer()
        return
    kb = _build_admins_kb(admins, page=cur_page, per_page=ADMINS_PER_PAGE)
    await cb.message.edit_text("Адміни:", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("admins_item_"))
async def cb_admin_item(cb: CallbackQuery):
    try:
        admin_id = int(cb.data.rsplit("_", 1)[-1])
    except Exception:
        await cb.answer()
        return

    db = next(_db())
    admin = svc_admins.get_admin_by_id(db, admin_id)
    if not admin:
        await cb.answer("Адміна не знайдено", show_alert=True)
        return

    nets = svc_networks.list_networks_by_admin(db, admin_id)
    stats = svc_networks.stats_for_admin(db, admin_id)
    await _render_admin_view(cb.message, admin, nets, stats)
    await cb.answer()


def _net_nav_keyboard(admin_id: int, page: int, total_pages: int):
    nav = page_kb(page, total_pages, prefix="admin_net_page")
    add_net = InlineKeyboardButton(text="Додати сітку", callback_data=f"admin_net_add:{admin_id}")
    back_btn = InlineKeyboardButton(text="⬅️ До адміна", callback_data=f"admin_back:{admin_id}")
    return InlineKeyboardMarkup(inline_keyboard=[[add_net], [back_btn]] + nav.inline_keyboard)


def _build_networks_keyboard(db, nets, admin_id: int):
    # підготуємо кількість каналів у кожній сітці
    nets = sorted(nets, key=lambda n: (0 if n.name == "Основные каналы" else 1, n.name.lower()))
    counts = {}
    for n in nets:
        cnt = db.execute(
            select(func.count(m.NetworkChannel.id)).where(m.NetworkChannel.network_id == n.id)
        ).scalar() or 0
        counts[n.id] = cnt

    rows = []
    row = []
    for n in nets:
        label = f"{n.name} ({counts.get(n.id, 0)})"
        row.append(InlineKeyboardButton(text=label, callback_data=f"admin_net_show:{n.id}"))
        if len(row) == NETS_PER_ROW:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def _build_bots_view(admin, bots: List[Dict[str, Any]], page: int = 0, per_page: int = BOTS_PER_PAGE):
    total_pages = max(1, math.ceil(len(bots) / per_page))
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    chunk = bots[start:start + per_page]
    lines = [f"Боти для {_admin_label(admin)} (всього {len(bots)}):"]
    if chunk:
        for idx, b in enumerate(chunk, start + 1):
            lines.append(_format_bot_line(idx, b))
    else:
        lines.append("Ботів не знайдено.")
    if total_pages > 1:
        nav_rows = page_kb(page, total_pages, prefix="admin_bots_page", menu_cb="admins_back_to_menu").inline_keyboard
        pagination_row, menu_row = nav_rows[0], nav_rows[1]
    else:
        pagination_row = None
        menu_row = [InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")]

    inline_keyboard = [
        [InlineKeyboardButton(text="⬅️ До адміна", callback_data=f"admin_back:{admin.id}")],
    ]
    if pagination_row:
        inline_keyboard.append(pagination_row)
    inline_keyboard.append([InlineKeyboardButton(text="🚫 Отписаться от ботов", callback_data=f"admin_unsub_bots:{admin.id}")])
    inline_keyboard.append(menu_row)

    kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    return "\n".join(lines), kb


def _format_bot_line(idx: int, bot: Dict[str, Any]) -> str:
    parts = [f"{idx}. @{bot['username']} — {bot.get('status') or '—'}"]
    if bot.get("session"):
        parts.append(f"    сесія: {bot['session']}")
    if bot.get("last_error"):
        parts.append(f"    помилка: {bot['last_error']}")
    return "\n".join(parts)


@router.callback_query(F.data.startswith("admin_net_edit"))
async def cb_admin_net_edit(cb: CallbackQuery):
    try:
        admin_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    db = next(_db())
    svc_networks.move_orphans_to_primary(db, admin_id)
    nets = svc_networks.list_networks_by_admin(db, admin_id)
    if not nets:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Додати сітку", callback_data=f"admin_net_add:{admin_id}")],
                [
                    InlineKeyboardButton(text="⬅️ До адміна", callback_data=f"admin_back:{admin_id}"),
                    InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu"),
                ],
            ]
        )
        await cb.message.edit_text("Поки немає сіток/каналів для цього адміна.", reply_markup=kb, disable_web_page_preview=True)
        await cb.answer()
        return
    rows = _build_networks_keyboard(db, nets, admin_id)
    rows.append([InlineKeyboardButton(text="Додати сітку", callback_data=f"admin_net_add:{admin_id}")])
    rows.append([
        InlineKeyboardButton(text="⬅️ До адміна", callback_data=f"admin_back:{admin_id}"),
        InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu"),
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await cb.message.edit_text("Сітки адміна (обери сітку):", reply_markup=kb, disable_web_page_preview=True)
    await cb.answer()


@router.callback_query(F.data.in_(["admin_net_page_prev", "admin_net_page_next"]))
async def cb_admin_net_page(cb: CallbackQuery):
    # витягуємо admin_id з попереднього повідомлення? не зберігаємо — беремо з останньої кнопки Додати сітку
    admin_id = None
    if cb.message and cb.message.reply_markup:
        for row in cb.message.reply_markup.inline_keyboard:
            for btn in row:
                if btn.callback_data and btn.callback_data.startswith("admin_net_add:"):
                    try:
                        admin_id = int(btn.callback_data.split(":")[1])
                    except Exception:
                        admin_id = None
                    break
    if admin_id is None:
        await cb.answer()
        return
    db = next(_db())
    svc_networks.move_orphans_to_primary(db, admin_id)
    # пагінації для списку сіток більше немає – повертаємо до admin_net_edit
    await cb_admin_net_edit(cb)


@router.callback_query(F.data.startswith("admin_back:"))
async def cb_admin_back(cb: CallbackQuery):
    try:
        admin_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    db = next(_db())
    admin = svc_admins.get_admin_by_id(db, admin_id)
    if not admin:
        await cb.answer("Адміна не знайдено", show_alert=True)
        return
    nets = svc_networks.list_networks_by_admin(db, admin_id)
    stats = svc_networks.stats_for_admin(db, admin_id)
    await _render_admin_view(cb.message, admin, nets, stats)
    await cb.answer()


@router.callback_query(F.data.startswith("admin_delete:"))
async def cb_admin_delete(cb: CallbackQuery):
    # більше не використовується
    await cb.answer()


@router.callback_query(F.data.startswith("admin_delete_confirm:"))
async def cb_admin_delete_confirm(cb: CallbackQuery):
    try:
        admin_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Так, видалити", callback_data=f"admin_delete_yes:{admin_id}"),
                InlineKeyboardButton(text="↩️ Ні", callback_data=f"admin_delete_no:{admin_id}"),
            ]
        ]
    )
    await cb.message.edit_text("Точно видалити адміна і прив'язані дані?", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("admin_delete_no:"))
async def cb_admin_delete_no(cb: CallbackQuery):
    try:
        admin_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    db = next(_db())
    admin = svc_admins.get_admin_by_id(db, admin_id)
    if not admin:
        await cb.answer("Адміна не знайдено", show_alert=True)
        return
    nets = svc_networks.list_networks_by_admin(db, admin_id)
    stats = svc_networks.stats_for_admin(db, admin_id)
    await _render_admin_view(cb.message, admin, nets, stats)
    await cb.answer("Скасовано", show_alert=False)


@router.callback_query(F.data.startswith("admin_delete_yes:"))
async def cb_admin_delete_yes(cb: CallbackQuery):
    try:
        admin_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    db = next(_db())
    # 1) збираємо канали та сесії, що підписані
    chan_ids = [ac.channel_id for ac in db.execute(select(m.AdminChannel).where(m.AdminChannel.admin_id == admin_id)).scalars().all()]
    # канали із сіток цього адміна
    net_chan_ids = db.execute(
        select(m.NetworkChannel.channel_id).join(m.Network, m.NetworkChannel.network_id == m.Network.id).where(m.Network.admin_id == admin_id)
    ).scalars().all()
    if net_chan_ids:
        chan_ids = list(set(chan_ids) | set(net_chan_ids))

    memberships = db.execute(
        select(m.Membership).where(m.Membership.channel_id.in_(chan_ids), m.Membership.account != "")
    ).scalars().all()
    acct_map = {}
    for mbr in memberships:
        acct_map.setdefault(mbr.account, set()).add(mbr.channel_id)
    leave_stats = []
    for acct, cids in acct_map.items():
        stat = await account_pool.leave_channels(acct, list(cids))
        leave_stats.append(stat)

    res = svc_admins.remove_admin_deep(db, admin_id, cleanup_channels=True)
    if not res["admin_deleted"]:
        await cb.answer("Не знайшов адміна", show_alert=True)
        return
    leaves = "; ".join([f"{s['session']}: left={s.get('left',0)} errors={s.get('errors',0)}" for s in leave_stats]) or "нема"
    leave_errors = sum(s.get("errors", 0) or 0 for s in leave_stats)
    if leave_errors:
        log.warning("admin_delete: leave errors admin_id=%s stats=%s", admin_id, leave_stats)
    text = (
        "Адміна видалено.\n"
        f"Прив'язок каналів: {res['admin_channels_deleted']}\n"
        f"Сіток: {res['networks_deleted']}, каналів у сітках: {res['network_channels_deleted']}\n"
        f"membership: {res.get('membership_deleted',0)}, invite_map: {res.get('invite_map_deleted',0)}, invite_status: {res.get('invite_status_deleted',0)}, links: {res.get('links_deleted',0)}, channels: {res.get('channels_deleted',0)}\n"
        f"link_queue: {res.get('link_queue_deleted',0)}\n"
        f"Відписка: {leaves}"
        + ("" if not leave_errors else "\n⚠️ Помилки відписки: перевірити вручну")
    )
    admins = _load_admins()
    kb = _build_admins_kb(admins, page=0, per_page=ADMINS_PER_PAGE) if admins else InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")]]
    )
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("admin_bots:"))
async def cb_admin_bots(cb: CallbackQuery):
    try:
        admin_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    db = next(_db())
    admin = svc_admins.get_admin_by_id(db, admin_id)
    if not admin:
        await cb.answer("Адміна не знайдено", show_alert=True)
        return
    bots = channel_db.list_bot_links(owner_display=admin.display, owner_username=admin.username)
    text, kb = _build_bots_view(admin, bots, page=0)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("admin_unsub_bots:"))
async def cb_admin_unsub_bots(cb: CallbackQuery, state: FSMContext):
    try:
        admin_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    db = next(_db())
    admin = svc_admins.get_admin_by_id(db, admin_id)
    if not admin:
        await cb.answer("Адміна не знайдено", show_alert=True)
        return
    bots = channel_db.list_bot_links(owner_display=admin.display, owner_username=admin.username)
    if not bots:
        await cb.answer("Немає ботів для відписки", show_alert=True)
        return
    # готуємо список username з індексами
    lines = ["Обери бота для відписки:"]
    kb_rows = []
    for idx, b in enumerate(bots, 1):
        uname = b.get("username") or ""
        lines.append(f"{idx}. @{uname} — {b.get('status') or '—'}")
        kb_rows.append([InlineKeyboardButton(text=f"🚫 @{uname}", callback_data=f"admin_unsub_bot:{admin_id}:{uname}")])
    kb_rows.append([InlineKeyboardButton(text="⬅️ До адміна", callback_data=f"admin_back:{admin_id}")])
    kb_rows.append([InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await cb.message.edit_text("\n".join(lines), reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("admin_unsub_bot:"))
async def cb_admin_unsub_bot(cb: CallbackQuery):
    try:
        _, admin_id_str, uname = cb.data.split(":", 2)
        admin_id = int(admin_id_str)
    except Exception:
        await cb.answer()
        return
    username = uname.strip()
    if not username:
        await cb.answer()
        return
    bots = channel_db.list_bot_links()
    bot_row = next((b for b in bots if b.get("username") == username), None)
    sess_name = bot_row.get("session") if bot_row else None
    if not sess_name:
        await cb.answer("Не знаю з якої сесії підписувались", show_alert=True)
        return
    client = account_pool.get_client_by_session_name(sess_name)
    if not client:
        await cb.answer(f"Сесія {sess_name} недоступна", show_alert=True)
        return
    errors = []
    try:
        await client(BlockRequest(username))
    except Exception as e:
        errors.append(str(e))
    try:
        await client(DeleteHistoryRequest(peer=username, revoke=True, max_id=0))
    except Exception as e:
        errors.append(f"del_history:{e}")
    removed = channel_db.delete_bot_link(username)
    msg = f"Бот @{username} заблокований на сесії {sess_name}."
    if errors:
        msg += " Помилки: " + "; ".join(errors)
    if removed:
        msg += " Запис у БД видалено."
    else:
        msg += " Запис у БД не знайдено."
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ До адміна", callback_data=f"admin_back:{admin_id}")],
            [InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")],
        ]
    )
    await cb.message.edit_text(msg, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.in_(["admin_bots_page_prev", "admin_bots_page_next"]))
async def cb_admin_bots_page(cb: CallbackQuery):
    # визначаємо admin_id з кнопки "⬅️ До адміна" у поточній клавіатурі
    admin_id = None
    if cb.message and cb.message.reply_markup:
        for row in cb.message.reply_markup.inline_keyboard:
            for btn in row:
                if btn.callback_data and btn.callback_data.startswith("admin_back:"):
                    try:
                        admin_id = int(btn.callback_data.split(":", 1)[1])
                    except Exception:
                        admin_id = None
                    break
    if not admin_id:
        await cb.answer()
        return
    db = next(_db())
    admin = svc_admins.get_admin_by_id(db, admin_id)
    if not admin:
        await cb.answer("Адміна не знайдено", show_alert=True)
        return
    bots = channel_db.list_bot_links(owner_display=admin.display, owner_username=admin.username)
    total_pages = max(1, math.ceil(len(bots) / BOTS_PER_PAGE))
    # поточну сторінку беремо з кнопки пагінації (текст типу 1/3)
    cur_page = _current_page_from_markup(cb.message)
    if cb.data == "admin_bots_page_prev":
        cur_page = (cur_page - 1) % total_pages
    else:
        cur_page = (cur_page + 1) % total_pages
    text, kb = _build_bots_view(admin, bots, page=cur_page)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("admin_net_add:"))
async def cb_admin_net_add(cb: CallbackQuery, state: FSMContext):
    try:
        admin_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    await state.update_data(net_admin_id=admin_id)
    await state.set_state(NetworkFlow.waiting_name)
    await cb.message.edit_text("Вкажи назву сітки.", reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ До адміна", callback_data=f"admin_back:{admin_id}")],
            [InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")],
        ]
    ))
    await cb.answer()


@router.message(NetworkFlow.waiting_name)
async def on_network_name(m, state: FSMContext):
    name = (m.text or "").strip()
    if not name:
        await m.answer("Назва не може бути порожньою. Вкажи назву сітки.")
        return
    data = await state.get_data()
    admin_id = data.get("net_admin_id")
    if not admin_id:
        await m.answer("Не бачу адміна. Почни заново з меню.")
        await state.clear()
        return
    db = next(_db())
    net = svc_networks.create_network(db, admin_id=admin_id, name=name)
    await state.update_data(net_id=net.id, net_name=net.name, net_move_existing=True)
    await state.set_state(NetworkFlow.waiting_links)
    await m.answer(
        f"Сітка '{net.name}' створена. Надішли посилання каналів для цієї сітки.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ До адміна", callback_data=f"admin_back:{admin_id}")],
                [InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")],
            ]
        ),
    )


@router.message(NetworkFlow.waiting_links)
async def on_network_links(m, state: FSMContext):
    urls = extract_links_from_message(m)
    data = await state.get_data()
    net_id = data.get("net_id")
    net_name = data.get("net_name")
    admin_id = data.get("net_admin_id")
    move_existing = data.get("net_move_existing", False)
    if not net_id:
        await m.answer("Не бачу сітки. Почни заново з меню.")
        await state.clear()
        return
    if not urls:
        await m.answer("Не знайшов посилань. Надішли t.me/... або tg://")
        return
    db = next(_db())
    res = svc_networks.add_channels_to_network(
        db,
        network_id=net_id,
        urls=urls,
        admin_id=admin_id,
        move_existing=move_existing,
    )
    moved_info = ""
    if res.get("moved"):
        moved_info = f" Перенесено з інших сіток: {res['moved']}."
    await m.answer(
        f"Сітка '{net_name}': додано каналів {res['added']}, не знайшов {res['not_found']}.{moved_info}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ До адміна", callback_data=f"admin_back:{data.get('net_admin_id')}")],
                [InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")],
            ]
        ),
    )
    await state.clear()
