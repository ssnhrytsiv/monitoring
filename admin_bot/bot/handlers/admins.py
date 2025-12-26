from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, StateFilter
import logging
import asyncio
import time
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramServerError

from admin_bot.db.session import SessionLocal
from admin_bot.services import admins as svc_admins
from admin_bot.config import ADMIN_ALLOWED_IDS
from admin_bot.bot.states import AddAdminFlow
from admin_bot.bot.keyboards import main_menu_kb
from admin_bot.services.queue_worker import process_batch
from admin_bot.utils.messages import extract_links_from_message
from app.services import link_queue

router = Router()
log = logging.getLogger("admin_bot.handlers.admins")


def _db():
    db = SessionLocal()
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


@router.message(AddAdminFlow.waiting_link)
async def on_link_message(m: Message, state: FSMContext):
    if not _is_allowed(m.from_user.id if m.from_user else None):
        return
    urls = extract_links_from_message(m)
    if not urls:
        await m.answer("Не знайшов посилання. Надішли t.me/... або tg://")
        return
    await state.update_data(
        urls=urls,
        raw_text=m.text or m.caption or "",
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
    urls = extract_links_from_message(m)
    if not urls:
        return
    log.info("auto-flow: detected %s urls in chat_id=%s", len(urls), m.chat.id if m.chat else None)
    await state.update_data(
        urls=urls,
        raw_text=m.text or m.caption or "",
    )
    await state.set_state(AddAdminFlow.waiting_name)
    log.info("auto-flow (no btn): state set to waiting_name chat_id=%s urls=%d", m.chat.id if m.chat else None, len(urls))
    await m.answer("Надішли ім'я адміна (обов'язково). Username опційний — вкажи через пробіл після імені.")


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
            )
        )

        await state.clear()
    except Exception:
        log.exception("on_admin_name failed")
        await state.clear()
        await m.answer("Сталася помилка під час обробки. Спробуй ще раз.")
