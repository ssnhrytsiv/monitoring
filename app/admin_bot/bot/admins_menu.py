from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from telethon.tl.functions.contacts import BlockRequest
from telethon.tl.functions.messages import DeleteHistoryRequest

from app.DAL import bot_links_operations as blo
from app.DAL import watch_groups_operations as watch_groups_db
from app.DAL.watch_groups_operations import WatchGroupRecord
from app.admin_bot.bot.keyboards import main_menu_kb, page_kb
from app.admin_bot.bot.states import AdminParamsFlow, AdminResultsFlow, NetworkFlow
from app.db import models as m
from app.db.session import SessionLocal, session_scope
from app.db import models as sm
from app.admin_bot.services import admins as svc_admins
from app.admin_bot.services import networks as svc_networks
from app.admin_bot.services.networks import channel_hyperlink
from app.DAL import network_channels_operations as net_db
from app.admin_bot.utils.messages import extract_links_from_message
from app.services import account_pool

PARAM_FIELDS = {
    "cpm": "CPM",
    "price": "Базова ціна",
    "subscribers": "Підписники",
}

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


def _list_bot_links(owner_admin_id: Optional[int] = None, owner_username: Optional[str] = None):
    db = SessionLocal()
    try:
        return blo.list_bot_links(db, owner_admin_id=owner_admin_id, owner_username=owner_username)
    finally:
        db.close()


def _delete_bot_link(username: str) -> bool:
    db = SessionLocal()
    try:
        return blo.delete_bot_link(db, username)
    finally:
        db.close()


def _admin_label(a) -> str:
    disp = a.display or ""
    uname = f"@{a.username}" if a.username else ""
    return (f"{disp} {uname}".strip()) or f"id={a.id}"


async def _render_admin_view(msg, admin, nets, stats):
    label_new = "<code>[NEW]</code>" if getattr(admin, "is_new", 0) else ""
    bots = _list_bot_links(owner_admin_id=admin.id, owner_username=admin.username)
    bots_count = len(bots)
    # підрахунок каналів по сітках
    net_lines = []
    total_channels = 0
    if nets:
        for n in nets:
            with session_scope() as db:
                cnt = net_db.count_channels_in_network(db, n.id)
            total_channels += cnt
            # домовлені
            neg_cpm = getattr(n, "cpm_negotiated", None)
            neg_price = getattr(n, "price_negotiated", None)
            # фактичні
            act_cpm = getattr(n, "actual_cpm", None)
            act_price = getattr(n, "actual_price", None)
            act_views = getattr(n, "actual_views", None)
            # фактична ціна за підписника за 30д: сумарні actual_price груп / суму subscribers груп
            fact_price_per_sub = None
            subs_30d = _sum_subscribers_for_network(n.id, days=30)
            spend_30d = _sum_actual_price_for_network(n.id, days=30)
            if subs_30d > 0:
                try:
                    fact_price_per_sub = spend_30d / float(subs_30d)
                except Exception:
                    fact_price_per_sub = None
            net_lines.append(f"• {n.name} ({cnt})")
            neg_line = f"  Домовлено: CPM {neg_cpm:.0f}" if neg_cpm is not None else "  Домовлено: CPM —"
            neg_line += f", Ціна {neg_price:.2f}" if neg_price is not None else ", Ціна —"
            net_lines.append(neg_line)
            act_line = f"  Факт: CPM {act_cpm:.0f}" if act_cpm is not None else "  Факт: CPM —"
            act_line += f", Ціна {act_price:.2f}" if act_price is not None else ", Ціна —"
            act_line += f", Перегляди {act_views}" if act_views is not None else ", Перегляди —"
            if fact_price_per_sub is not None:
                act_line += f", Ціна/підп {fact_price_per_sub:.4f}"
            else:
                act_line += ", Ціна/підп —"
            net_lines.append(act_line)
        if len(nets) > 1:
            net_lines.append(f"Сумарно: {total_channels}")

    lines = [
        f"Адмін: {_admin_label(admin)}{' ' + label_new if label_new else ''}",
        f"Сіток: {len(nets)}",
        f"Боти: {bots_count}",
        f"Сумарна ціна: {stats['price_sum']:.2f}" if stats['price_sum'] is not None else "Сумарна ціна: —",
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

    toggle_text = "Старий" if getattr(admin, "is_new", 0) else "Новий"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Посмотреть каналы", callback_data=f"admin_net_edit:{admin.id}"),
                InlineKeyboardButton(text="Посмотреть ботов", callback_data=f"admin_bots:{admin.id}"),
            ],
            [InlineKeyboardButton(text="Результати", callback_data=f"admin_results:{admin.id}")],
            [InlineKeyboardButton(text="Оновити список каналів", callback_data=f"refresh_channels:{admin.id}")],
            [InlineKeyboardButton(text="Задати параметри", callback_data=f"admin_set_params:{admin.id}")],
            [InlineKeyboardButton(text=toggle_text, callback_data=f"admin_toggle_new:{admin.id}")],
            [InlineKeyboardButton(text="🗑 Видалити адміна", callback_data=f"admin_delete_confirm:{admin.id}")],
            [
                InlineKeyboardButton(text="⬅️ До списку", callback_data="show_admins"),
                InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu"),
            ],
        ]
    )
    text = "\n".join([ln for ln in lines if ln.strip()])
    try:
        return await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message can't be edited" in str(e):
            return await msg.answer(text, reply_markup=kb, parse_mode="HTML")
        raise
    except Exception:
        return await msg.answer(text, reply_markup=kb, parse_mode="HTML")


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


@router.callback_query(F.data == "show_requested")
async def cb_show_requested(cb: CallbackQuery):
    db = SessionLocal()
    try:
        rows = (
            db.query(
                sm.RequestedCheck.session,
                sm.RequestedCheck.channel_id,
                sm.RequestedCheck.noted_at,
                m.Channel,
                m.Admin,
            )
            .join(m.Channel, m.Channel.channel_id == sm.RequestedCheck.channel_id)
            .outerjoin(m.Admin, m.Admin.id == m.Channel.owner_admin_id)
            .order_by(sm.RequestedCheck.noted_at.desc())
            .all()
        )
    finally:
        db.close()

    if not rows:
        await cb.message.edit_text(
            "Немає відправлених заявок.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")]]
            ),
        )
        await cb.answer()
        return

    db = SessionLocal()
    try:
        lines = ["Відправлені заявки:"]
        for idx, (session, channel_id, noted_at, channel, owner_admin) in enumerate(rows, start=1):
            link_html = channel_hyperlink(db, channel)
            owner_label = owner_admin.display if owner_admin and owner_admin.display else "—"
            dt = datetime.fromtimestamp(noted_at).strftime("%Y-%m-%d %H:%M:%S")
            lines.append(
                f"{idx}) {link_html} — акаунт: {session}, власник: {owner_label}, дата: {dt}"
            )
    finally:
        db.close()

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")]]
    )
    await cb.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
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
    rows = net_db.list_channels_in_network(db, net_id)
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


def _params_kb(admin_id: int, net_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="CPM", callback_data=f"admin_param:{admin_id}:{net_id}:cpm"),
                InlineKeyboardButton(text="Ціна", callback_data=f"admin_param:{admin_id}:{net_id}:price"),
                InlineKeyboardButton(text="Підписники", callback_data=f"admin_param:{admin_id}:{net_id}:subscribers"),
            ],
            [InlineKeyboardButton(text="⬅️ До адміна", callback_data=f"admin_back:{admin_id}")],
            [InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")],
        ]
    )


def _net_select_kb(admin_id: int, nets: List[m.Network]) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for n in nets:
        row.append(InlineKeyboardButton(text=n.name, callback_data=f"admin_param_net:{admin_id}:{n.id}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ До адміна", callback_data=f"admin_back:{admin_id}")])
    rows.append([InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _result_groups_for_admin(admin_id: int) -> tuple[list[WatchGroupRecord], list[int]]:
    """Повертає групи вотчів, прив'язані до адміна (admin_id або його сітки)."""
    with session_scope() as db:
        nets = svc_networks.list_networks_by_admin(db, admin_id)
        net_ids = [n.id for n in nets]
    groups_data = watch_groups_db.list_groups_for_admin(admin_id, net_ids)
    return groups_data, net_ids


def _group_label(group_data: WatchGroupRecord) -> str:
    if group_data.title:
        return group_data.title
    if group_data.created_at:
        return str(group_data.created_at).split()[0]
    return f"ID {group_data.id}"


def _build_results_text(admin, groups: list[WatchGroupRecord]) -> str:
    lines = [f"Результати для {_admin_label(admin)}:"]
    if not groups:
        lines.append("Груп немає.")
    for g in groups:
        ac_cpm = g.actual_cpm
        ac_price = g.actual_price
        ac_views = g.actual_views
        subs = g.subscribers
        line = f"• {_group_label(g)} — CPMф: {ac_cpm:.0f}" if ac_cpm is not None else f"• {_group_label(g)} — CPMф: —"
        line += f", Цінаф: {ac_price:.2f}" if ac_price is not None else ", Цінаф: —"
        line += f", Перегляди: {ac_views}" if ac_views is not None else ", Перегляди: —"
        line += f", Підписники: {subs}" if subs is not None else ", Підписники: —"
        lines.append(line)
    return "\n".join(lines)


def _sum_actual_price_for_network(net_id: int, days: int = 30) -> float:
    """Сумує actual_price груп для сітки за останні days."""
    return watch_groups_db.sum_actual_price_for_network(net_id, days)


def _sum_subscribers_for_network(net_id: int, days: int = 30) -> int:
    """Сумує subscribers груп для сітки за останні days."""
    return watch_groups_db.sum_subscribers_for_network(net_id, days)


def _results_kb(admin_id: int, groups: list[WatchGroupRecord]) -> InlineKeyboardMarkup:
    rows = []
    for g in groups:
        rows.append([InlineKeyboardButton(text=_group_label(g), callback_data=f"admin_result_group:{admin_id}:{g.id}")])
    rows.append([InlineKeyboardButton(text="⬅️ До адміна", callback_data=f"admin_back:{admin_id}")])
    rows.append([InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _render_group_detail(admin_id: int, group_id: int) -> tuple[str, InlineKeyboardMarkup]:
    group_data, posts_data = watch_groups_db.get_group_detail(group_id)
    if not group_data:
        return "Групу не знайдено.", InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Результати", callback_data=f"admin_results:{admin_id}")],
                [InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")],
            ]
        )
    subscriber_count = group_data.subscribers
    text_lines = [
        f"Реклама: {_group_label(group_data)}",
        f"CPM факт: {group_data.actual_cpm:.0f}" if group_data.actual_cpm is not None else "CPM факт: —",
        f"Ціна факт: {group_data.actual_price:.2f}" if group_data.actual_price is not None else "Ціна факт: —",
        f"Перегляди факт: {group_data.actual_views}" if group_data.actual_views is not None else "Перегляди факт: —",
        f"Підписники: {subscriber_count if subscriber_count is not None else '—'}",
        "Пости:",
    ]
    if not posts_data:
        text_lines.append("• Пости відсутні.")
    else:
        for post_data in posts_data:
            views = post_data.final_views or post_data.views_at_post or 0
            price = None
            if post_data.price_at_post is not None:
                price = float(post_data.price_at_post)
            elif post_data.cpm_at_post is not None and views:
                price = float(post_data.cpm_at_post) * views / 1000.0
            cpm = None
            if price is not None and views > 0:
                cpm = price * 1000.0 / views
            elif post_data.cpm_at_post is not None:
                cpm = post_data.cpm_at_post
            price_per_sub = None
            if subscriber_count:
                try:
                    price_per_sub = price / subscriber_count if price is not None else None
                except Exception:
                    price_per_sub = None
            line = f"• Post {post_data.id}: "
            line += f"CPM {cpm:.0f}" if cpm is not None else "CPM —"
            line += f", Перегляди {views}"
            line += f", Ціна {price:.2f}" if price is not None else ", Ціна —"
            line += f", Ціна/підп {price_per_sub:.4f}" if price_per_sub is not None else ", Ціна/підп —"
            text_lines.append(line)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Вказати підписників", callback_data=f"admin_group_subs:{admin_id}:{group_id}")],
            [InlineKeyboardButton(text="⬅️ Результати", callback_data=f"admin_results:{admin_id}")],
            [InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")],
        ]
    )
    return "\n".join(text_lines), kb


@router.callback_query(F.data.startswith("admin_set_params:"))
async def cb_admin_set_params(cb: CallbackQuery):
    try:
        admin_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    db = next(_db())
    nets = svc_networks.list_networks_by_admin(db, admin_id)
    if not nets:
        await cb.answer("У адміна немає сіток", show_alert=True)
        return
    if len(nets) == 1:
        await cb.message.edit_text(
            f"Сітка: {nets[0].name}. Обери параметр для редагування:",
            reply_markup=_params_kb(admin_id, nets[0].id),
        )
    else:
        await cb.message.edit_text(
            "Оберіть сітку для редагування параметрів:",
            reply_markup=_net_select_kb(admin_id, nets),
        )
    await cb.answer()


@router.callback_query(F.data.startswith("admin_param_net:"))
async def cb_admin_param_net(cb: CallbackQuery):
    try:
        _, admin_id, net_id = cb.data.split(":", 2)
        admin_id = int(admin_id)
    except Exception:
        await cb.answer()
        return
    db = next(_db())
    nets = svc_networks.list_networks_by_admin(db, admin_id)
    net = next((n for n in nets if n.id == int(net_id)), None)
    if not net:
        await cb.answer("Сітку не знайдено", show_alert=True)
        return
    await cb.message.edit_text(
        f"Сітка: {net.name}. Обери параметр:",
        reply_markup=_params_kb(admin_id, net.id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("admin_param:"))
async def cb_admin_param(cb: CallbackQuery, state: FSMContext):
    try:
        _, admin_id, net_id, field = cb.data.split(":", 3)
        admin_id = int(admin_id)
        net_id = int(net_id)
    except Exception:
        await cb.answer()
        return
    if field not in PARAM_FIELDS:
        await cb.answer()
        return
    db = next(_db())
    net = db.execute(select(m.Network).where(m.Network.id == net_id)).scalar_one_or_none()
    if not net:
        await cb.answer("Сітку не знайдено", show_alert=True)
        return
    current = getattr(net, field, None)
    label = PARAM_FIELDS[field]
    await state.update_data(param_admin_id=admin_id, param_net_id=net_id, param_field=field)
    await state.set_state(AdminParamsFlow.waiting_value)
    await cb.message.edit_text(
        f"Сітка: {net.name}\n{label}: введи значення.\nПоточне: {current if current is not None else '—'}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_set_params:{admin_id}")],
                [InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")],
            ]
        ),
    )
    await cb.answer()


@router.message(AdminParamsFlow.waiting_value)
async def on_param_value(m, state: FSMContext):
    data = await state.get_data()
    admin_id = data.get("param_admin_id")
    net_id = data.get("param_net_id")
    field = data.get("param_field")
    if not admin_id or not net_id or field not in PARAM_FIELDS:
        await m.answer("Сесія втрачена, відкрий адміна знову.")
        await state.clear()
        return
    raw = (m.text or "").strip()
    if not raw:
        await m.answer("Значення не може бути порожнім. Введи число.")
        return
    try:
        if field == "subscribers":
            val = int(float(raw))
        else:
            val = float(raw)
    except Exception:
        await m.answer("Не вдалося розпізнати число, спробуй ще раз.")
        return
    db = next(_db())
    net = svc_networks.update_network_params(
        db,
        net_id,
        cpm=val if field == "cpm" else None,
        price=val if field == "price" else None,
        subscribers=val if field == "subscribers" else None,
    )
    await state.clear()
    if not net:
        await m.answer("Сітку не знайдено.")
        return
    nets = svc_networks.list_networks_by_admin(db, admin_id)
    stats = svc_networks.stats_for_admin(db, admin_id)
    await m.answer(
        f"{PARAM_FIELDS[field]} оновлено: {val}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ До адміна", callback_data=f"admin_back:{admin_id}")],
                [InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")],
            ]
        ),
    )
    # Оновимо картку адміна окремим повідомленням
    await _render_admin_view(m, svc_admins.get_admin_by_id(db, admin_id), nets, stats)


@router.callback_query(F.data.startswith("admin_results:"))
async def cb_admin_results(cb: CallbackQuery):
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
    groups, _ = _result_groups_for_admin(admin_id)
    text = _build_results_text(admin, groups)
    kb = _results_kb(admin_id, groups)
    await _edit_text_safe(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.startswith("admin_result_group:"))
async def cb_admin_result_group(cb: CallbackQuery):
    try:
        _, admin_id, gid = cb.data.split(":", 2)
        admin_id = int(admin_id)
        gid = int(gid)
    except Exception:
        await cb.answer()
        return
    text, kb = _render_group_detail(admin_id, gid)
    await _edit_text_safe(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.startswith("admin_group_subs:"))
async def cb_admin_group_subs(cb: CallbackQuery, state: FSMContext):
    try:
        _, admin_id, gid = cb.data.split(":", 2)
        admin_id = int(admin_id)
        gid = int(gid)
    except Exception:
        await cb.answer()
        return
    await state.update_data(result_admin_id=admin_id, result_group_id=gid)
    await state.set_state(AdminResultsFlow.waiting_group_subs)
    await cb.message.edit_text(
        "Введи кількість підписників для цієї реклами.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Результати", callback_data=f"admin_results:{admin_id}")],
                [InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")],
            ]
        ),
    )
    await cb.answer()


@router.message(AdminResultsFlow.waiting_group_subs)
async def on_group_subs(m, state: FSMContext):
    data = await state.get_data()
    admin_id = data.get("result_admin_id")
    gid = data.get("result_group_id")
    if not admin_id or not gid:
        await m.answer("Сесія втрачена, відкрий адміна знову.")
        await state.clear()
        return
    raw = (m.text or "").strip()
    try:
        subs = int(float(raw))
    except Exception:
        await m.answer("Не вдалося розпізнати число, спробуй ще раз.")
        return
    watch_groups_db.set_watch_group_subscribers(int(gid), subs)
    await state.clear()
    text, kb = _render_group_detail(int(admin_id), int(gid))
    await m.answer(f"Підписників встановлено: {subs}", reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Результати", callback_data=f"admin_results:{admin_id}")],
            [InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")],
        ]
    ))
    await m.answer(text, reply_markup=kb)
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
        counts[n.id] = net_db.count_channels_in_network(db, n.id)

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
                [InlineKeyboardButton(text="Задати порядок", callback_data=f"admin_net_order:{admin_id}")],
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
    rows.append([InlineKeyboardButton(text="Задати порядок", callback_data=f"admin_net_order:{admin_id}")])
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


@router.callback_query(F.data.startswith("admin_net_order:"))
async def cb_admin_net_order(cb: CallbackQuery):
    try:
        admin_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    text = (
        "Порядок каналів у сітках тепер відтворює послідовність додавання з черги. "
        "Додаткове ручне налаштування буде доступне пізніше."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ До сіток", callback_data=f"admin_net_edit:{admin_id}")],
            [InlineKeyboardButton(text="В меню", callback_data="admins_back_to_menu")],
        ]
    )
    await cb.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    await cb.answer()


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


@router.callback_query(F.data.startswith("admin_toggle_new:"))
async def cb_admin_toggle_new(cb: CallbackQuery):
    try:
        admin_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    db = next(_db())
    admin = svc_admins.toggle_admin_new(db, admin_id)
    if not admin:
        await cb.answer("Адміна не знайдено", show_alert=True)
        return
    nets = svc_networks.list_networks_by_admin(db, admin.id)
    stats = svc_networks.stats_for_admin(db, admin.id)
    await _render_admin_view(cb.message, admin, nets, stats)
    await cb.answer("Мітку оновлено.")


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
    info = svc_admins.collect_admin_delete_info(admin_id)
    if not info.get("exists"):
        await cb.answer("Не знайшов адміна", show_alert=True)
        return
    chan_ids = info.get("chan_ids") or []
    acct_map = info.get("acct_map") or {}
    leave_stats = []
    for acct, cids in acct_map.items():
        stat = await account_pool.leave_channels(acct, list(cids))
        leave_stats.append(stat)

    res = svc_admins.remove_admin_deep(admin_id, cleanup_channels=True)
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
        f"membership: {res.get('membership_deleted',0)}, links: {res.get('links_deleted',0)}, channels: {res.get('channels_deleted',0)}\n"
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
    bots = _list_bot_links(owner_admin_id=admin.id, owner_username=admin.username)
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
    bots = _list_bot_links(owner_admin_id=admin.id, owner_username=admin.username)
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
    bots = _list_bot_links(owner_admin_id=admin_id)
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
    removed = _delete_bot_link(username)
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
    bots = _list_bot_links(owner_admin_id=admin.id, owner_username=admin.username)
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
