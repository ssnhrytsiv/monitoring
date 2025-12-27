from __future__ import annotations

import math
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select, func

from admin_bot.db import models as m
from admin_bot.db.session import SessionLocal
from admin_bot.services import admins as svc_admins
from admin_bot.services import networks as svc_networks
from admin_bot.services.pagination import page_kb
from admin_bot.bot.states import NetworkFlow
from admin_bot.utils.messages import extract_links_from_message
from admin_bot.services.networks import channel_hyperlink
from app.services import account_pool

router = Router()


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
    lines = [
        f"Адмін: {_admin_label(admin)}",
        f"Сіток: {len(nets)}",
        f"Сумарна ціна: {stats['price_sum']:.2f}" if stats["price_sum"] is not None else "Сумарна ціна: —",
        f"Середні перегляди (сума 30д): {stats['avg_views_30d_sum'] or 0}",
    ]
    if nets:
        lines.append("Сітки:")
        for n in nets:
            lines.append(f"• {n.name}")
    else:
        lines.append("Сіток поки немає.")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оновити сітку", callback_data=f"admin_net_edit:{admin.id}")],
            [InlineKeyboardButton(text="🗑 Видалити адміна", callback_data=f"admin_delete_confirm:{admin.id}")],
            [InlineKeyboardButton(text="⬅️ До списку", callback_data="show_admins")],
            [InlineKeyboardButton(text="В меню", callback_data="report_back_to_menu")],
        ]
    )
    return msg.edit_text("\n".join(lines), reply_markup=kb)


ADMINS_PER_PAGE = 30
ADMINS_PER_ROW = 2
NETS_PER_ROW = 4


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
    nav = page_kb(page, total_pages, prefix="admins_page")
    return InlineKeyboardMarkup(inline_keyboard=buttons + nav.inline_keyboard)


@router.callback_query(F.data == "show_admins")
async def cb_show_admins(cb: CallbackQuery, state: FSMContext):
    admins = _load_admins()
    if not admins:
        await cb.message.answer(
            "Список адмінів порожній.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="report_back_to_menu")]]
            ),
        )
        await cb.answer()
        return
    kb = _build_admins_kb(admins, page=0, per_page=ADMINS_PER_PAGE)
    await cb.message.edit_text("Адміни:", reply_markup=kb)
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
        InlineKeyboardButton(text="В меню", callback_data="report_back_to_menu"),
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
            [InlineKeyboardButton(text="В меню", callback_data="report_back_to_menu")],
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
                [InlineKeyboardButton(text="В меню", callback_data="report_back_to_menu")],
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
    if cb.data == "admins_page_prev":
        cur_page = (cur_page - 1) % total_pages
    else:
        cur_page = (cur_page + 1) % total_pages
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
                    InlineKeyboardButton(text="В меню", callback_data="report_back_to_menu"),
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
        InlineKeyboardButton(text="В меню", callback_data="report_back_to_menu"),
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
    text = (
        "Адміна видалено.\n"
        f"Прив'язок каналів: {res['admin_channels_deleted']}\n"
        f"Сіток: {res['networks_deleted']}, каналів у сітках: {res['network_channels_deleted']}\n"
        f"membership: {res.get('membership_deleted',0)}, invite_map: {res.get('invite_map_deleted',0)}, invite_status: {res.get('invite_status_deleted',0)}, links: {res.get('links_deleted',0)}, channels: {res.get('channels_deleted',0)}\n"
        f"Відписка: {leaves}\n"
        "Увага: link_queue/інші таблиці не чіпалися."
    )
    admins = _load_admins()
    kb = _build_admins_kb(admins, page=0, per_page=ADMINS_PER_PAGE) if admins else InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="report_back_to_menu")]]
    )
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
            [InlineKeyboardButton(text="В меню", callback_data="report_back_to_menu")],
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
                [InlineKeyboardButton(text="В меню", callback_data="report_back_to_menu")],
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
                [InlineKeyboardButton(text="В меню", callback_data="report_back_to_menu")],
            ]
        ),
    )
    await state.clear()
