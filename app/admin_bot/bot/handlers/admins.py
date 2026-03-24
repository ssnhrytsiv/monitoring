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
from app.admin_bot.services.subscription import dedup_sessions_cleanup as dedup_cleanup
from app.admin_bot.utils.messages import extract_links_from_message
from app.services import link_queue
from app.utils.link_parser import extract_bot_username
from app.services import account_pool

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

    scan_result = await dedup_cleanup.collect_duplicate_cleanup_scan_result()
    if not scan_result.plan_item_list and not scan_result.error_text_list:
        await msg.edit_text("Пул сесій порожній (ACCOUNTS не налаштовані).")
        await cb.answer()
        return

    plan_item_list = scan_result.plan_item_list
    if not plan_item_list:
        lines = ["Дублікатів не знайдено."]
        if scan_result.error_text_list:
            lines.append("Помилки збору: " + "; ".join(scan_result.error_text_list))
        await msg.edit_text("\n".join(lines))
        await cb.answer()
        return

    # Формуємо попередній огляд
    preview = ["Знайдені дублікати підписок:"]
    preview.append(f"Каналів з дублями: {len(plan_item_list)}")
    for plan_item in plan_item_list[:50]:
        title_text = plan_item.title or f"channel_id={plan_item.channel_id}"
        keep_text = account_pool.session_display(plan_item.keep_session_name)
        leave_text = dedup_cleanup.session_display_list(
            plan_item.leave_session_name_list
        ) or "—"
        preview.append(
            f"• {title_text} (ID: {plan_item.channel_id}) — keep {keep_text}"
            f" [{dedup_cleanup.render_keep_reason(plan_item.keep_reason)}]; leave {leave_text}"
        )
    if len(plan_item_list) > 50:
        preview.append(f"... ще {len(plan_item_list)-50} каналів")
    if scan_result.error_text_list:
        preview.append("Помилки збору: " + "; ".join(scan_result.error_text_list))

    token = str(uuid.uuid4())
    _DEDUP_PENDING[token] = {
        "plan_item_list": plan_item_list,
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
    plan_item_list = plan.get("plan_item_list") or []

    execution_item_list = await dedup_cleanup.execute_duplicate_cleanup_plan(
        plan_item_list
    )

    left_total = sum(
        int((execution_item.cleanup_stats or {}).get("left", 0) or 0)
        for execution_item in execution_item_list
    )
    deleted_total = sum(
        int((execution_item.cleanup_stats or {}).get("deleted", 0) or 0)
        for execution_item in execution_item_list
    )
    errors_total = sum(
        int((execution_item.cleanup_stats or {}).get("errors", 0) or 0)
        for execution_item in execution_item_list
    )

    summary = [
        f"Відписка завершена. Каналів з дублями: {len(execution_item_list)}"
    ]
    for execution_item in execution_item_list[:50]:
        cleanup_stats = execution_item.cleanup_stats or {}
        summary.append(
            f"• {execution_item.title or f'channel_id={execution_item.channel_id}'}"
            f" — keep {account_pool.session_display(execution_item.keep_session_name)}"
            f" [{dedup_cleanup.render_keep_reason(execution_item.keep_reason)}];"
            f" left={cleanup_stats.get('left', 0)}"
            f" deleted={cleanup_stats.get('deleted', 0)}"
            f" errors={cleanup_stats.get('errors', 0)}"
        )
    if len(execution_item_list) > 50:
        summary.append(f"... ще {len(execution_item_list)-50} каналів")
    summary.append(
        f"Сумарно: left={left_total}, deleted={deleted_total}, errors={errors_total}"
    )
    await cb.message.edit_text("\n".join(summary))
    await cb.answer()


@router.message(Command("admins"))
async def cmd_list_admins(m: Message):
    if not _is_allowed(m.from_user.id if m.from_user else None):
        return
    db = next(_db())
    admins = sorted(svc_admins.list_admins(db), key=lambda a: (a.display or "").lower())
    if not admins:
        await m.answer("Адмінів поки немає.")
        return
    lines = []
    for idx, a in enumerate(admins, start=1):
        display = (a.display or "").strip() or f"id={a.id}"
        details = []
        if a.username:
            details.append(f"@{a.username}")
        details.append(f"id={a.id}")
        if a.tg_id is not None:
            details.append(f"tg_id={a.tg_id}")
        lines.append(f"{idx}. {display} ({', '.join(details)})")
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

    add_only = bool(data.get("add_only"))
    raw_texts: list[str] = data.get("raw_texts") or []
    raw_htmls: list[str] = data.get("raw_htmls") or raw_texts
    raw_text = "\n".join(raw_texts) if raw_texts else ""
    raw_html = "\n".join(raw_htmls) if raw_htmls else raw_text
    entities = data.get("entities") or []
    if add_only:
        batch_id = f"missing-add:{cb.message.chat.id}:{int(time.time())}"
        log.info(
            "missing_add_collect_go: enqueue batch_id=%s admin_id=%s urls=%s",
            batch_id,
            admin.id,
            len(urls),
        )
        added = link_queue.enqueue(
            urls,
            batch_id=batch_id,
            origin_chat=cb.message.chat.id if cb.message else None,
            origin_msg=getattr(cb.message, "message_id", None),
            owner_display=admin.display,
            owner_username=admin.username,
            adopt_existing=True,
            reset_next_try=True,
        )
        progress_anchor = await cb.message.answer(
            f"Додано у чергу {added}/{len(urls)} посилань. Починаю обробку…"
        )
        await state.clear()
        await cb.answer("Запускаю підписку…", show_alert=False)
        asyncio.create_task(
            process_batch(
                batch_id=batch_id,
                chat_id=cb.message.chat.id if cb.message else 0,
                reply_msg=progress_anchor,
                admin_display=admin.display or "",
                admin_username=admin.username,
                admin_tg_id=admin.tg_id,
                raw_text=raw_text,
                raw_html=raw_html,
                entities=entities,
                original_urls=urls,
            )
        )
        return

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
