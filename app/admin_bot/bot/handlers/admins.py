from __future__ import annotations

from aiogram import Router, F
import re
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
import logging
import asyncio
import time
import uuid
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramServerError

from app.admin_bot.db.session import SessionLocal
from app.admin_bot.services import admins as svc_admins
from app.admin_bot.config import ADMIN_ALLOWED_IDS
from app.admin_bot.bot.states import AddAdminFlow, RefreshChannelsFlow
from app.admin_bot.bot.keyboards import main_menu_kb
from app.admin_bot.services.queue_worker import process_batch
from app.admin_bot.services.subscription import refresh_channels_for_admin, finalize_refresh_confirmation
from app.admin_bot.utils.messages import extract_links_from_message
from app.services import link_queue
from app.utils.link_parser import extract_bot_username
from app.services import account_pool
from app.services.account_pool import iter_pool_clients
from telethon.tl import types as tl_types

router = Router()
log = logging.getLogger("admin_bot.handlers.admins")
_DEDUP_PENDING = {}


def _db():
    db = SessionLocal()
    try:
        svc_admins.ensure_admin_schema(db)
    except Exception:
        pass
    try:
        yield db
    finally:
        db.close()


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
        c = re.sub(r"[^\w\-./:?&=#%+]+$", "", c)
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
        keep = sorted(s for s, _ in sess_list)[0]
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
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Відписати дублікати", callback_data=f"dedup_confirm_yes:{token}"),
                InlineKeyboardButton(text="❌ Не відписувати", callback_data=f"dedup_confirm_no:{token}"),
            ]
        ]
    )
    await msg.edit_text("\n".join(preview), reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("dedup_confirm_no:"))
async def cb_dedup_confirm_no(cb: CallbackQuery):
    token = cb.data.split(":", 1)[1]
    _DEDUP_PENDING.pop(token, None)
    await cb.message.edit_text("Відписка скасована.")
    await cb.answer()


@router.callback_query(F.data.startswith("dedup_confirm_yes:"))
async def cb_dedup_confirm_yes(cb: CallbackQuery):
    token = cb.data.split(":", 1)[1]
    plan = _DEDUP_PENDING.pop(token, None)
    if not plan:
        await cb.message.edit_text("Дані для відписки не знайдено. Запусти дедуп знову.")
        await cb.answer()
        return
    leave_plan: dict[str, set[int]] = plan.get("leave_plan") or {}
    title_map: dict[int, str] = plan.get("title_map") or {}
    keep_map: dict[int, str] = plan.get("keep_map") or {}

    stats_lines = []
    left_total = 0
    errors_total = 0
    for sess, cids in leave_plan.items():
        res = await account_pool.leave_channels(sess, list(cids))
        left_total += res.get("left", 0) or 0
        errors_total += res.get("errors", 0) or 0
        stats_lines.append(f"{account_pool.session_display(sess)}: left={res.get('left',0)} errors={res.get('errors',0)}")

    summary = [f"Відписка завершена. Каналів з дублями: {len(keep_map)}"]
    summary.extend(stats_lines or ["Не було що відписувати"])
    summary.append(f"Сумарно відписок: {left_total}, помилок: {errors_total}")
    await cb.message.edit_text("\n".join(summary))
    await cb.answer()


@router.message(Command("admins"))
async def cmd_list_admins(m: Message):
    if not _is_allowed(m.from_user.id if m.from_user else None):
        return
    db = next(_db())
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

    db = next(_db())

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

    adm = svc_admins.get_or_create_admin(db, tg_id=target_id, username=username, display=display)
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
    db = next(_db())
    admin = None
    admin_id = None
    if cb.data and ":" in cb.data:
        try:
            admin_id = int(cb.data.split(":", 1)[1])
        except Exception:
            admin_id = None
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
    await state.clear()
    await state.set_state(RefreshChannelsFlow.waiting_links)
    await state.update_data(admin_id=admin.id)
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
    db = next(_db())
    admin = None
    admin_id = data.get("admin_id")
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
            batch_id=batch_id,
            chat_id=cb.message.chat.id if cb.message else 0,
            reply_msg=cb.message,
            admin=admin,
            urls=urls,
            raw_text=raw_text,
            raw_html=raw_html,
            entities=entities,
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
    db = next(_db())
    admin = None
    admin_id = data.get("admin_id")
    if admin_id:
        admin = svc_admins.get_admin_by_id(db, admin_id)
    if admin is None and m.from_user:
        admin = svc_admins.find_admin(
            db,
            tg_id=m.from_user.id,
            username=m.from_user.username if m.from_user.username else None,
            display=None,
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
        batch_id = f"adminbot:{m.chat.id}:{int(time.time())}"
        log.info("on_admin_name: enqueue batch_id=%s urls=%s admin_display=%s username=%s", batch_id, len(urls), display, candidate_username)
        added = link_queue.enqueue(
            urls,
            batch_id=batch_id,
            origin_chat=m.chat.id if m.chat else None,
            origin_msg=m.message_id,
            owner_display=display,
            owner_username=candidate_username,
            adopt_existing=True,
            reset_next_try=True,
        )
        await _answer_with_retry(m, f"Додано у чергу {added}/{len(urls)} посилань. Починаю обробку…")

        asyncio.create_task(
            process_batch(
                batch_id=batch_id,
                chat_id=m.chat.id,
                reply_msg=m,
                admin_display=display,
                admin_username=candidate_username,
                admin_tg_id=None,
                raw_text=raw_text,
                raw_html=raw_html,
                entities=entities,
                original_urls=urls,
            )
        )

        await state.clear()
    except Exception:
        log.exception("on_admin_name failed")
        await state.clear()
        await m.answer("Сталася помилка під час обробки. Спробуй ще раз.")
