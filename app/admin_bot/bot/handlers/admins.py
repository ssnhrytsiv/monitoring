from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
import logging
import asyncio
import time
import uuid
import re
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramServerError

from app.db.session import session_scope
from app.admin_bot.services import admins as svc_admins
from app.admin_bot.config import ADMIN_ALLOWED_IDS
from app.admin_bot.bot.states import AddAdminFlow, RefreshChannelsFlow, DedupAdminChannelsFlow
from app.admin_bot.bot.keyboards import main_menu_kb
from app.admin_bot.services.subscription import (
    refresh_channels_for_admin,
    finalize_refresh_confirmation,
    RefreshContext,
)
from app.admin_bot.utils.messages import extract_links_from_message
from app.utils.link_parser import extract_bot_username
from app.services import account_pool
from app.services.account_pool import iter_pool_clients
from telethon.tl import types as tl_types
from app.admin_bot.services import dedup_admin_channels as svc_dedup

router = Router()
log = logging.getLogger("admin_bot.handlers.admins")
_DEDUP_PENDING = {}
_DEDUP_AC_PENDING = {}


def _admin_btn_label(admin_obj) -> str:
    disp = getattr(admin_obj, "display", None) or admin_obj.get("display") if isinstance(admin_obj, dict) else None
    uname_raw = getattr(admin_obj, "username", None) if not isinstance(admin_obj, dict) else admin_obj.get("username")
    uname = f"@{uname_raw}" if uname_raw else ""
    aid = getattr(admin_obj, "id", None) if not isinstance(admin_obj, dict) else admin_obj.get("id")
    base = (f"{disp} {uname}".strip()) or (f"id={aid}" if aid is not None else "")
    return base if base else "невідомий"


def _is_allowed(user_id: int | None) -> bool:
    if not ADMIN_ALLOWED_IDS:
        return True
    if user_id is None:
        return False
    return user_id in ADMIN_ALLOWED_IDS


def _clean_urls(urls: list[str]) -> list[str]:
    """
    Прибирає зайві розділові символи (типу закриваючої дужки) та дублікати, зберігаючи порядок.
    Залишає лише t.me інвайти (t.me/+hash), ботів (username_bot) або публічні канали (t.me/username).
    """
    from app.utils.link_parser import sanitize_link

    cleaned: list[str] = []
    seen: set[str] = set()
    # Шукаємо t.me інвайти (+hash або joinchat/hash), bot-юзернейми (_bot/bot) або канал за username.
    invite_pattern = re.compile(r"^(?:https?://)?t\.me/(?:\+|joinchat/)[A-Za-z0-9_-]{5,128}$")
    channel_pattern = re.compile(r"^(?:https?://)?t\.me/[A-Za-z0-9_]{3,}$")
    for u in urls:
        try:
            c = sanitize_link(u) or u
        except Exception:
            c = u
        c = (c or "").strip()
        # Вирізаємо зайві хвости
        # дефіс наприкінці класу символів, щоб уникнути діапазонів
        c = re.sub(r"[^\w./:?&=#%+/-]+$", "", c)
        c = c.rstrip(").,;'\"<>[]{}")
        is_invite = bool(invite_pattern.match(c))
        bot_username = extract_bot_username(c)
        is_channel_username = bool(channel_pattern.match(c))
        if not is_invite and not bot_username and not is_channel_username:
            continue
        key = f"https://t.me/{bot_username}" if bot_username else c
        if key not in seen:
            cleaned.append(key)
            seen.add(key)
    return cleaned


async def _answer_with_retry(msg: Message, text: str, **kwargs):
    """
    Відправляє відповідь з одним повтором на випадок тимчасових 5xx Telegram.
    """
    for attempt in range(2):
        try:
            return await msg.answer(text, **kwargs)
        except TelegramServerError as e:
            if attempt == 0:
                log.warning("answer retry after TelegramServerError: %s", e)
                await asyncio.sleep(1)
            else:
                raise


@router.message(Command("start"))
async def cmd_start(m: Message):
    if not _is_allowed(m.from_user.id if m.from_user else None):
        return
    await m.answer(
        "Адмін-бот:\n"
        "• /add_admin — додати себе (або tg_id аргументом)\n"
        "• /admins — список адмінів",
        reply_markup=main_menu_kb()
    )


async def _render_ac_conflict(cb: CallbackQuery, state: FSMContext, idx: int):
    data = await state.get_data()
    conflicts = data.get("conflicts") or []
    if idx < 0 or idx >= len(conflicts):
        await state.clear()
        await cb.message.edit_text("✅ Конфліктів більше немає.", reply_markup=main_menu_kb())
        await cb.answer()
        return

    conflict = conflicts[idx]
    cid = conflict.get("channel_id")
    title = conflict.get("title") or "—"
    admins = conflict.get("admins") or []
    lines = [
        "Знайдено кількох адмінів для каналу:",
        f"• {title} (id={cid})",
        "",
        "Оберіть, кого залишити:",
    ]
    buttons = []
    for adm in admins:
        txt = _admin_btn_label(type("Obj", (), adm))
        buttons.append([InlineKeyboardButton(text=txt, callback_data=f"dedup_ac_keep:{cid}:{adm['id']}")])
    buttons.append([InlineKeyboardButton(text="Пропустити", callback_data="dedup_ac_skip")])
    buttons.append([InlineKeyboardButton(text="Завершити", callback_data="dedup_ac_stop")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await cb.message.edit_text("\n".join(lines), reply_markup=kb, disable_web_page_preview=True)
    await state.update_data(idx=idx)


@router.callback_query(F.data == "dedup_sessions")
async def cb_dedup_sessions(cb: CallbackQuery):
    if not _is_allowed(cb.from_user.id if cb.from_user else None):
        await cb.answer()
        return
    msg = await cb.message.answer("🔁 Сканую підписки сесій у пулі, шукаю дублікати...")

    slots = iter_pool_clients()
    if not slots:
        await msg.edit_text("Пул сесій порожній (ACCOUNTS не налаштовані).")
        await cb.answer()
        return

    session_channels: dict[str, dict[int, str]] = {}
    errors = []

    async def _collect(slot):
        chans: dict[int, str] = {}
        try:
            async for dlg in slot.client.iter_dialogs():
                ent = dlg.entity
                if isinstance(ent, tl_types.Channel):
                    cid = int(ent.id)
                    title = getattr(ent, "title", "") or dlg.name or ""
                    chans[cid] = title
        except Exception as e:
            errors.append(f"{slot.name}: {e}")
        return chans

    # зібрати канали для кожної сесії
    for slot in slots:
        chans = await _collect(slot)
        session_channels[slot.name] = chans

    # будуємо cid -> сесії
    cid_map: dict[int, list[tuple[str, str]]] = {}
    for sess, cid_title in session_channels.items():
        for cid, title in cid_title.items():
            cid_map.setdefault(cid, []).append((sess, title))

    leave_plan: dict[str, set[int]] = {}
    keep_map: dict[int, str] = {}
    title_map: dict[int, str] = {}
    for cid, sess_list in cid_map.items():
        if len(sess_list) <= 1:
            continue
        # Залишаємо сесію з кінця відсортованого списку, а решту відписуємо.
        keep = sorted(s for s, _ in sess_list)[-1]
        keep_map[cid] = keep
        title_map[cid] = sess_list[0][1] or ""
        for sess, _ in sess_list:
            if sess == keep:
                continue
            leave_plan.setdefault(sess, set()).add(cid)

    if not leave_plan:
        lines = ["Дублікатів не знайдено."]
        if errors:
            lines.append("Помилки збору: " + "; ".join(errors))
        await msg.edit_text("\n".join(lines))
        await cb.answer()
        return

    # Формуємо попередній огляд
    preview = ["Знайдені дублікати підписок:"]
    dup_cids = [cid for cid, lst in cid_map.items() if len(lst) > 1]
    preview.append(f"Каналів з дублями: {len(dup_cids)}")
    for cid in sorted(dup_cids)[:50]:
        keep = keep_map.get(cid)
        leave = []
        for sess, _ in cid_map.get(cid, []):
            if sess != keep:
                leave.append(account_pool.session_display(sess))
        title = title_map.get(cid) or ""
        title_txt = title or f"channel_id={cid}"
        preview.append(f"• {title_txt} (ID: {cid}) — keep {account_pool.session_display(keep) if keep else '?'}; leave {', '.join(leave) if leave else '—'}")
    if len(dup_cids) > 50:
        preview.append(f"... ще {len(dup_cids)-50} каналів")
    if errors:
        preview.append("Помилки збору: " + "; ".join(errors))

    token = str(uuid.uuid4())
    _DEDUP_PENDING[token] = {
        "leave_plan": leave_plan,
        "title_map": title_map,
        "keep_map": keep_map,
    }


@router.callback_query(F.data == "dedup_admin_channels")
async def cb_dedup_admin_channels(cb: CallbackQuery, state: FSMContext):
    if not _is_allowed(cb.from_user.id if cb.from_user else None):
        await cb.answer()
        return
    conflicts = []
    try:
        with session_scope() as db:
            conflicts = svc_dedup.find_conflicts(db)
    except Exception:
        log.exception("dedup_admin_channels: failed to load conflicts")
        await cb.message.answer("Сталася помилка при пошуку дублікатів.")
        await cb.answer()
        return
    if not conflicts:
        await cb.message.answer("Дублікатів у admin_channels не знайдено.", reply_markup=main_menu_kb())
        await cb.answer()
        return
    await state.set_state(DedupAdminChannelsFlow.browsing)
    await state.update_data(conflicts=conflicts, idx=0, resolved=0)
    await cb.answer()
    await _render_ac_conflict(cb, state, 0)


@router.callback_query(StateFilter(DedupAdminChannelsFlow.browsing), F.data.startswith("dedup_ac_keep:"))
async def cb_dedup_ac_keep(cb: CallbackQuery, state: FSMContext):
    if not _is_allowed(cb.from_user.id if cb.from_user else None):
        await cb.answer()
        return
    try:
        _, cid_str, aid_str = cb.data.split(":", 2)
        cid = int(cid_str)
        aid = int(aid_str)
    except Exception:
        await cb.answer("Невірні дані.")
        return
    removed = 0
    try:
        with session_scope() as db:
            removed = svc_dedup.resolve_conflict(db, channel_id=cid, keep_admin_id=aid)
    except Exception:
        log.exception("dedup_ac_keep: failed channel_id=%s admin_id=%s", cid, aid)
        await cb.answer("Помилка при видаленні.")
        return
    data = await state.get_data()
    idx = data.get("idx", 0)
    resolved = data.get("resolved", 0) + 1
    # пропускаємо далі
    next_idx = idx + 1
    await state.update_data(idx=next_idx, resolved=resolved)
    await cb.answer(f"Залишено admin_id={aid}, видалено {removed}.")
    await _render_ac_conflict(cb, state, next_idx)


@router.callback_query(StateFilter(DedupAdminChannelsFlow.browsing), F.data == "dedup_ac_skip")
async def cb_dedup_ac_skip(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    idx = data.get("idx", 0)
    next_idx = idx + 1
    await state.update_data(idx=next_idx)
    await cb.answer("Пропущено.")
    await _render_ac_conflict(cb, state, next_idx)


@router.callback_query(StateFilter(DedupAdminChannelsFlow.browsing), F.data == "dedup_ac_stop")
async def cb_dedup_ac_stop(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    resolved = data.get("resolved", 0)
    await state.clear()
    await cb.message.edit_text(f"Готово. Оброблено конфліктів: {resolved}.", reply_markup=main_menu_kb())
    await cb.answer()


@router.message(Command("admins"))
async def cmd_list_admins(m: Message):
    if not _is_allowed(m.from_user.id if m.from_user else None):
        return
    with session_scope() as db:
        admins = svc_admins.list_admins(db)
        if not admins:
            await m.answer("Адмінів поки немає.")
            return
        lines = []
        for a in admins:
            disp = a.display or ""
            uname = f"@{a.username}" if a.username else ""
            lines.append(f"{a.id}. {disp} {uname} (tg_id={a.tg_id})")
        await m.answer("\n".join(lines))


@router.message(Command("add_admin"))
async def cmd_add_admin(m: Message):
    if not _is_allowed(m.from_user.id if m.from_user else None):
        return

    parts = (m.text or "").strip().split(maxsplit=3)

    # Вимагаємо tg_id першим аргументом
    if len(parts) < 2:
        await m.answer("Вкажи tg_id. Використання: /add_admin <tg_id> [@username] [display]")
        return
    try:
        target_id = int(parts[1])
    except Exception:
        await m.answer("tg_id має бути числом. Використання: /add_admin <tg_id> [@username] [display]")
        return

    username = None
    display = None

    if len(parts) >= 3:
        arg2 = parts[2]
        if arg2.startswith("@"):
            username = arg2.lstrip("@")
        else:
            display = arg2
    if len(parts) >= 4:
        display = parts[3]

    with session_scope() as db:
        adm = svc_admins.get_or_create_admin(db, tg_id=target_id, username=username, display=display)
        msg = (
            "✅ Адміна додано/оновлено:\n"
            f"id={adm.id}\n"
            f"tg_id={adm.tg_id}\n"
            f"username=@{adm.username or ''}\n"
            f"display={adm.display or '—'}"
        )
    await m.answer(msg)
    await m.answer(
        "✅ Адміна додано/оновлено:\n"
        f"id={adm.id}\n"
        f"tg_id={adm.tg_id}\n"
        f"username=@{adm.username or ''}\n"
        f"display={adm.display or '—'}"
    )


# ---------- Меню / FSM для додавання через посилання ----------

@router.callback_query(F.data == "add_admin_flow")
async def cb_add_admin_flow(cb: CallbackQuery, state):
    if not _is_allowed(cb.from_user.id):
        return
    await state.set_state(AddAdminFlow.waiting_link)
    await cb.message.answer("Надішли посилання на канал, який хочеш закріпити за адміном.")
    await cb.answer()


@router.callback_query(F.data.startswith("refresh_channels:"))
async def cb_refresh_channels(cb: CallbackQuery, state: FSMContext):
    if not _is_allowed(cb.from_user.id):
        return
    admin = None
    admin_id = None
    if cb.data and ":" in cb.data:
        try:
            admin_id = int(cb.data.split(":", 1)[1])
        except Exception:
            admin_id = None
    found_admin_id = None
    with session_scope() as db:
        if admin_id:
            admin = svc_admins.get_admin_by_id(db, admin_id)
        if admin is None:
            admin = svc_admins.find_admin(
                db,
                tg_id=cb.from_user.id if cb.from_user else None,
                username=cb.from_user.username if cb.from_user else None,
                display=None,
            )
        if not admin:
            await cb.message.answer("Спочатку додай себе як адміна (/add_admin).")
            await cb.answer()
            return
        found_admin_id = admin.id
    await state.clear()
    await state.set_state(RefreshChannelsFlow.waiting_links)
    await state.update_data(admin_id=found_admin_id)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Скасувати оновлення каналів",
                    callback_data="refresh_channels_cancel",
                )
            ]
        ]
    )
    await cb.message.answer(
        "Надішли новий список каналів (інвайт-посилання t.me/+...). "
        "Канали, яких не буде у списку, будуть відписані й очищені з бази.",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data == "refresh_channels_cancel")
async def cb_refresh_channels_cancel(cb: CallbackQuery, state: FSMContext):
    if not _is_allowed(cb.from_user.id):
        return
    log.info("refresh_channels_cancel: invoked chat=%s user=%s", cb.message.chat.id if cb.message else None, cb.from_user.id if cb.from_user else None)
    await state.clear()
    try:
        if cb.message:
            await cb.message.delete()
            log.info("refresh_channels_cancel: prompt deleted")
    except Exception:
        log.exception("refresh_channels_cancel: failed to delete prompt message")
    await cb.answer("Оновлення скасовано.")


def _refresh_collect_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Добавити", callback_data="refresh_channels_collect_add"),
                InlineKeyboardButton(text="🚀 Перейти до підписки", callback_data="refresh_channels_collect_go"),
            ],
            [
                InlineKeyboardButton(text="❌ Скасувати оновлення каналів", callback_data="refresh_channels_cancel"),
            ],
        ]
    )


@router.callback_query(F.data.startswith("refresh_unsub_yes:"))
async def cb_refresh_unsub_yes(cb: CallbackQuery):
    if not _is_allowed(cb.from_user.id if cb.from_user else None):
        return
    batch_id = cb.data.split(":", 1)[1] if cb.data and ":" in cb.data else None
    if not batch_id:
        await cb.answer("Запит не знайдено", show_alert=True)
        return
    try:
        if cb.message:
            await cb.message.edit_reply_markup()
    except Exception:
        log.warning("refresh_unsub_yes: failed to clear markup", exc_info=True)
    target_msg = cb.message
    if not target_msg:
        await cb.answer("Не знайшов повідомлення для відповіді", show_alert=True)
        return
    await cb.answer("Готую звіт…")
    asyncio.create_task(finalize_refresh_confirmation(batch_id, True, target_msg))


@router.callback_query(F.data.startswith("refresh_unsub_no:"))
async def cb_refresh_unsub_no(cb: CallbackQuery):
    if not _is_allowed(cb.from_user.id if cb.from_user else None):
        return
    batch_id = cb.data.split(":", 1)[1] if cb.data and ":" in cb.data else None
    if not batch_id:
        await cb.answer("Запит не знайдено", show_alert=True)
        return
    try:
        if cb.message:
            await cb.message.edit_reply_markup()
    except Exception:
        log.warning("refresh_unsub_no: failed to clear markup", exc_info=True)
    target_msg = cb.message
    if not target_msg:
        await cb.answer("Не знайшов повідомлення для відповіді", show_alert=True)
        return
    await cb.answer("Відписку скасовано.")
    asyncio.create_task(finalize_refresh_confirmation(batch_id, False, target_msg))


@router.callback_query(F.data == "refresh_channels_collect_add")
async def cb_refresh_collect_add(cb: CallbackQuery):
    if not _is_allowed(cb.from_user.id):
        return
    await cb.answer("Надішли додаткові посилання.")


@router.callback_query(F.data == "refresh_channels_collect_go")
async def cb_refresh_collect_go(cb: CallbackQuery, state: FSMContext):
    if not _is_allowed(cb.from_user.id):
        return
    if not cb.message:
        await cb.answer()
        return
    data = await state.get_data()
    urls: list[str] = data.get("urls") or []
    if not urls:
        await cb.answer("Немає зібраних посилань. Надішли t.me/+ ...", show_alert=True)
        return
    admin_snapshot = svc_admins.get_admin_for_refresh(
        admin_id=data.get("admin_id"),
        from_user_id=cb.from_user.id if cb.from_user else None,
        from_username=cb.from_user.username if cb.from_user and cb.from_user.username else None,
    )
    if not admin_snapshot:
        await cb.answer("Адміна не знайдено. Додай через /add_admin", show_alert=True)
        await state.clear()
        return

    raw_texts: list[str] = data.get("raw_texts") or []
    raw_htmls: list[str] = data.get("raw_htmls") or raw_texts
    raw_text = "\n".join(raw_texts) if raw_texts else ""
    raw_html = "\n".join(raw_htmls) if raw_htmls else raw_text
    entities = data.get("entities") or []
    batch_id = f"refresh:{cb.message.chat.id}:{int(time.time())}"

    await state.clear()
    await cb.answer("Запускаю підписку…", show_alert=False)
    asyncio.create_task(
        refresh_channels_for_admin(
            RefreshContext(
                batch_id=batch_id,
                chat_id=cb.message.chat.id if cb.message else 0,
                reply_msg=cb.message,
                admin=admin_snapshot,
                urls=urls,
                raw_text=raw_text,
                raw_html=raw_html,
                entities=entities,
            )
        )
    )


@router.message(AddAdminFlow.waiting_link)
async def on_link_message(m: Message, state: FSMContext):
    if not _is_allowed(m.from_user.id if m.from_user else None):
        return
    urls = _clean_urls(extract_links_from_message(m))
    log.info("admins.extract_urls chat_id=%s urls=%s", m.chat.id if m.chat else None, urls)
    if not urls:
        await m.answer("Не знайшов посилання. Надішли t.me/... або tg://")
        return
    await state.update_data(
        urls=urls,
        raw_text=m.text or m.caption or "",
        raw_html=m.html_text or m.text or m.caption or "",
        entities=m.entities or [],
    )
    await state.set_state(AddAdminFlow.waiting_name)
    log.info("auto-flow: state set to waiting_name chat_id=%s urls=%d", m.chat.id if m.chat else None, len(urls))
    await m.answer("Надішли ім'я адміна (обов'язково). Username опційний — вкажи через пробіл після імені.")


@router.message(StateFilter(None))
async def on_any_links(m: Message, state: FSMContext):
    """
    Обробка без кнопки: якщо прийшли посилання поза FSM, автоматично запускаємо флоу.
    """
    if m.text and m.text.startswith("/"):
        return  # команди не чіпаємо
    if not _is_allowed(m.from_user.id if m.from_user else None):
        return
    # якщо вже у стані FSM – ігноруємо, хай обробляє конкретний хендлер
    cur_state = await state.get_state()
    if cur_state:
        return
    urls = _clean_urls(extract_links_from_message(m))
    if not urls:
        return
    log.info("admins.extract_urls chat_id=%s urls=%s", m.chat.id if m.chat else None, urls)
    log.info("auto-flow: detected %s urls in chat_id=%s", len(urls), m.chat.id if m.chat else None)
    await state.update_data(
        urls=urls,
        raw_text=m.text or m.caption or "",
        raw_html=m.html_text or m.text or m.caption or "",
        entities=m.entities or [],
    )
    await state.set_state(AddAdminFlow.waiting_name)
    log.info("auto-flow (no btn): state set to waiting_name chat_id=%s urls=%d", m.chat.id if m.chat else None, len(urls))
    await m.answer("Надішли ім'я адміна (обов'язково). Username опційний — вкажи через пробіл після імені.")


@router.message(RefreshChannelsFlow.waiting_links)
async def on_refresh_links(m: Message, state: FSMContext):
    if not _is_allowed(m.from_user.id if m.from_user else None):
        return
    urls = _clean_urls(extract_links_from_message(m))
    log.info("admins.refresh_urls chat_id=%s urls=%s", m.chat.id if m.chat else None, urls)
    if not urls:
        await m.answer("Не знайшов посилання. Надішли t.me/+ інвайти.")
        return

    data = await state.get_data()
    admin = svc_admins.get_admin_for_refresh(
        admin_id=data.get("admin_id"),
        from_user_id=m.from_user.id if m.from_user else None,
        from_username=m.from_user.username if m.from_user and m.from_user.username else None,
    )
    if not admin:
        await m.answer("Адміна не знайдено. Додай його через /add_admin і спробуй ще раз.")
        await state.clear()
        return

    existing: list[str] = data.get("urls") or []
    seen = set(existing)
    merged = existing[:]
    for u in urls:
        if u not in seen:
            merged.append(u)
            seen.add(u)

    raw_texts: list[str] = data.get("raw_texts") or []
    raw_htmls: list[str] = data.get("raw_htmls") or []
    raw_text = m.text or m.caption or ""
    raw_html = m.html_text or raw_text
    if raw_text:
        raw_texts.append(raw_text)
    if raw_html:
        raw_htmls.append(raw_html)

    await state.update_data(
        urls=merged,
        raw_texts=raw_texts,
        raw_htmls=raw_htmls,
        entities=m.entities or [],
    )
    await _answer_with_retry(
        m,
        f"Додав {len(urls)} посилань (всього {len(merged)}). "
        "Потрібно добавити ще канали, чи перейти до підписки?",
        reply_markup=_refresh_collect_kb(),
    )


@router.message(AddAdminFlow.waiting_name)
async def on_admin_name(m: Message, state: FSMContext):
    if not _is_allowed(m.from_user.id if m.from_user else None):
        return
    try:
        cur_state = await state.get_state()
        log.info("on_admin_name: state=%s chat_id=%s user_id=%s", cur_state, m.chat.id if m.chat else None, m.from_user.id if m.from_user else None)
        await _answer_with_retry(m, "Прийняв ім'я, обробляю…")
        data = await state.get_data()
        name_raw = (m.text or "").strip()
        if not name_raw:
            await m.answer("Ім'я не може бути порожнім. Надішли ім'я.")
            return
        tokens = name_raw.split()
        username = None
        display_parts = []
        for tok in tokens:
            if tok.startswith("@") and username is None:
                username = tok.lstrip("@")
            else:
                display_parts.append(tok)
        display = " ".join(display_parts).strip()
        if not display:
            await m.answer("Ім'я не може бути порожнім. Надішли ім'я.")
            return

        urls: list[str] = data.get("urls") or []
        if not urls:
            log.warning("on_admin_name: no urls in state chat_id=%s data_keys=%s", m.chat.id if m.chat else None, list(data.keys()))
            log.warning("on_admin_name: no urls in state chat_id=%s", m.chat.id if m.chat else None)
            await state.clear()
            await m.answer("Немає збережених посилань. Почни спочатку.")
            return

        candidate_username = username or data.get("admin_username")
        raw_text = data.get("raw_text") or ""
        raw_html = data.get("raw_html") or raw_text
        entities = data.get("entities") or []
        admin_id, batch_id, added = svc_admins.add_admin_and_enqueue_links(
            urls=urls,
            display=display,
            username=candidate_username,
            raw_text=raw_text,
            raw_html=raw_html,
            entities=entities,
            chat_id=m.chat.id if m.chat else None,
            msg_id=m.message_id,
            reply_msg=m,
        )
        log.info("on_admin_name: enqueue batch_id=%s urls=%s admin_display=%s username=%s", batch_id, len(urls), display, candidate_username)
        await _answer_with_retry(m, f"Додано у чергу {added}/{len(urls)} посилань. Починаю обробку…")

        await state.clear()
    except Exception:
        log.exception("on_admin_name failed")
        await state.clear()
        await m.answer("Сталася помилка під час обробки. Спробуй ще раз.")
