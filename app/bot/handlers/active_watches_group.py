from typing import Optional, List, Any, Dict
import logging
import re

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from app.bot.states import EditWatch
from app.bot.keyboards import main_menu_kb
from app.services.time_utils import msk_now

from app.bot.services.templates_repo import load_templates_map
from app.bot.services.channels_repo import (
    get_links_by_channel_ids,
    get_owners_by_channel_ids,
    get_titles_by_channel_ids,
)
from app.bot.services.active_watches_service import (
    get_group_leader_key,
    load_group_items,
    load_group_channels,
    cancel_group_watches,
    get_watch_by_id,
)
from app.bot.services.edit_watch_service import (
    set_watch_status_pending,
    update_watch_time_window,
    manual_match_watch_from_message,
)
from app.bot.utils.active_watches_formatters import (
    fmt_tw_end_human,
    short_title,
    status_to_emoji,
    build_group_table,
    format_single_watch,
)
from app.bot.utils.active_watches_pagination import (
    paginate_items,
    build_group_keyboard,
    PAGE_SIZE,
)

log = logging.getLogger("bot_active_watches.group")
router = Router()





def _edit_back_kb(wid: int) -> InlineKeyboardBuilder:
    """
    Клавіатура з кнопкою 'Back' для повернення в картку редагування watch'а.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Back", callback_data=f"watch:edit:{wid}")
    return kb


@router.callback_query(F.data == "watch:noop")
async def watch_noop(cb: CallbackQuery):
    await cb.answer()


@router.callback_query(F.data.startswith("watch:channels:"))
async def watch_channels(cb: CallbackQuery):
    """
    Показує список посилань каналів для групи leader_wid.
    """
    try:
        leader_wid = int(cb.data.split(":")[-1])
    except Exception:
        leader_wid = None

    if not leader_wid:
        await cb.answer("bad id", show_alert=True)
        return

    cids = load_group_channels(leader_wid)
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
    """
    Скасовує всі watch'і групи leader_wid (pending/matched/expired -> cancelled).
    """
    try:
        leader_wid = int(cb.data.split(":")[-1])
    except Exception:
        leader_wid = None
    if not leader_wid:
        await cb.answer("bad id", show_alert=True)
        return

    ok = False
    try:
        ok = cancel_group_watches(leader_wid)
    except Exception as e:
        log.exception("cancel_group_watches failed: %s", e)

    if not ok:
        await cb.answer("Не зміг скасувати", show_alert=True)
        return

    await cb.answer("Скасовано", show_alert=False)

    # Щоб оновити список, імпортуємо хендлер меню тут
    from app.bot.handlers.active_watches_menu import menu_list_active

    await menu_list_active(cb)


@router.callback_query(F.data.startswith("watch:group:"))
async def watch_group_details(cb: CallbackQuery):
    """
    Деталізація групи вотчів для leader_wid з пагінацією по кнопках.
    """
    parts = cb.data.split(":")
    leader_wid: Optional[int] = None
    page = 1
    try:
        if len(parts) == 3:
            leader_wid = int(parts[2])  # watch:group:<leader_wid>
        elif len(parts) == 4:
            leader_wid = int(parts[2])  # watch:group:<leader_wid>:<page>
            page = int(parts[3]) or 1
        else:
            leader_wid = int(parts[-1])
    except Exception:
        leader_wid = None

    if not leader_wid:
        await cb.answer("bad id", show_alert=True)
        return

    if page < 1:
        page = 1

    # 1) Читаємо ключ групи
    try:
        key = get_group_leader_key(leader_wid)
    except Exception as e:
        log.exception("get_group_leader_key failed: %s", e)
        key = None

    if not key:
        await cb.answer("Не знайдено", show_alert=True)
        return

    tid_i, tw_key, cby, leader_cid = key

    # 2) Витягуємо всі watch'і групи
    try:
        all_items = load_group_items(tid_i, tw_key, cby)
    except Exception as e:
        log.exception("load_group_items failed: %s", e)
        all_items = []

    if not all_items:
        await cb.answer("Група порожня", show_alert=True)
        return

    # 3) Пагінація
    page_items, page, total_pages = paginate_items(all_items, page, PAGE_SIZE)

    # 4) Підготовка мап (шаблони, назви каналів, owner-и)
    templates_map = load_templates_map()

    cids: List[int] = [cid_i for _, cid_i, _, _, _ in all_items if cid_i]

    channel_names_map: Dict[int, str] = {}
    owners_map: Dict[int, str] = {}
    if cids:
        channel_names_map = get_titles_by_channel_ids(cids) or {}
        owners_map = get_owners_by_channel_ids(cids) or {}

    # owner у першому рядку таблиці (і в заголовку повідомлення)
    owner_for_header = "—"
    try:
        if cids:
            first_cid = cids[0]
            owner_for_header = owners_map.get(
                first_cid,
                channel_names_map.get(first_cid, "—"),
            )
    except Exception:
        pass

    # 5) Таблиця
    table_block = build_group_table(
        all_items,
        templates_map=templates_map,
        channel_titles=channel_names_map,
        owner_display=owner_for_header,
    )

    # 6) Клавіатура для поточної сторінки
    kb = build_group_keyboard(
        page_items=page_items,
        leader_wid=leader_wid,
        page=page,
        total_pages=total_pages,
        status_to_emoji=status_to_emoji,
        get_title_for_tpl=lambda tpl_id: short_title(
            templates_map.get(tpl_id, {}).get("title"),
            tpl_id,
        ),
    )

    # Back
    kb.row(InlineKeyboardButton(text="⬅️ Back", callback_data="menu:list_active"))

    # 7) Заголовок повідомлення
    tw_txt = fmt_tw_end_human(tw_key)
    header = (
        f"Вотч для {owner_for_header}, час вікна до {tw_txt} — вотч активний і працює"
    )

    text = header + "\n\n" + table_block

    try:
        await cb.message.edit_text(
            text,
            reply_markup=kb.as_markup(),
            parse_mode="Markdown",
        )
    except TelegramBadRequest:
        await cb.message.answer(
            text,
            reply_markup=kb.as_markup(),
            parse_mode="Markdown",
        )


@router.callback_query(F.data.startswith("watch:edit:"))
async def watch_edit(cb: CallbackQuery):
    """
    Екран редагування одного watch'а:
      - показує деталі;
      - дві кнопки: Додати пост, Змінити статус;
      - Back поки що повертає в меню активних.
    """
    try:
        wid = int(cb.data.split(":")[-1])
    except Exception:
        wid = None

    if not wid:
        await cb.answer("bad id", show_alert=True)
        return

    # 1) Тягнемо watch з БД
    try:
        watch = get_watch_by_id(wid)
    except Exception as e:
        log.exception("get_watch_by_id failed: %s", e)
        watch = None

    if not watch:
        await cb.answer("Не знайшов цей watch", show_alert=True)
        return

    (
        wid_i,
        template_id,
        status,
        time_window_end,
        created_by,
        channel_id,
        source_url,
    ) = watch

    # 2) Потрібні довідники: шаблони, назви каналів, owner (опційно)
    templates_map = load_templates_map()
    cids: List[int] = []
    if channel_id:
        try:
            cids.append(int(channel_id))
        except Exception:
            pass

    channel_names_map: Dict[int, str] = {}
    owners_map: Dict[int, str] = {}
    if cids:
        channel_names_map = get_titles_by_channel_ids(cids) or {}
        owners_map = get_owners_by_channel_ids(cids) or {}

    owner_for_header = "—"
    try:
        if cids:
            first_cid = cids[0]
            owner_for_header = owners_map.get(
                first_cid,
                channel_names_map.get(first_cid, "—"),
            )
    except Exception:
        pass

    # 3) Будуємо текст (Plain Text, без Markdown)
    text = format_single_watch(
        watch=watch,
        templates_map=templates_map,
        channel_titles=channel_names_map,
        owner_display=owner_for_header,
    )

    # 4) Кнопки: Додати пост, Змінити статус, Back
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Додати пост", callback_data=f"watch:add_post:{wid_i}")
    kb.button(text="🔄 Змінити статус", callback_data=f"watch:change_status:{wid_i}")
    kb.row(
        InlineKeyboardButton(
            text="⬅️ Back",
            callback_data="menu:list_active",
        )
    )

    try:
        await cb.message.edit_text(
            text,
            reply_markup=kb.as_markup(),
        )
    except TelegramBadRequest:
        await cb.message.answer(
            text,
            reply_markup=kb.as_markup(),
        )


@router.callback_query(F.data.startswith("watch:change_status:"))
async def watch_change_status(cb: CallbackQuery, state: FSMContext):
    """
    Крок 1: користувач натиснув 'Змінити статус' для конкретного wid.
    - Переводимо цей watch у pending (через service).
    - Просимо ввести новий час закінчення вікна у форматі HH:MM.
    - Запам'ятовуємо wid у FSM і чекаємо повідомлення.
    """
    try:
        wid = int(cb.data.split(":")[-1])
    except Exception:
        wid = None

    if not wid:
        await cb.answer("bad id", show_alert=True)
        return

    ok = set_watch_status_pending(wid)
    if not ok:
        await cb.answer("Не зміг змінити статус", show_alert=True)
        return

    await state.set_state(EditWatch.time_window)
    await state.update_data(edit_wid=wid)

    kb = _edit_back_kb(wid)

    await cb.message.edit_text(
        f"Статус watch #{wid} змінено на pending.\n"
        f"Введи новий час закінчення вікна СЬОГОДНІ у форматі HH:MM, наприклад 23:30.",
        reply_markup=kb.as_markup(),
    )


@router.message(EditWatch.time_window)
async def edit_watch_time_window(m: Message, state: FSMContext):
    """
    Крок 2: користувач ввів новий час HH:MM для вже існуючого watch'а.
    - парсимо час;
    - перевіряємо, що в майбутньому;
    - оновлюємо time_window_start/time_window_end для wid (через service);
    - показуємо підтвердження.
    """
    data = await state.get_data()
    wid = data.get("edit_wid")
    kb = _edit_back_kb(wid) if wid else None

    text = (m.text or "").strip()
    m_time = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text)

    if not m_time:
        await m.answer(
            "Введи час у форматі HH:MM, наприклад 23:30.",
            reply_markup=kb.as_markup() if kb else None,
        )
        return

    def _try_int_local(s: str) -> Optional[int]:
        try:
            return int(str(s).strip())
        except Exception:
            return None

    h = _try_int_local(m_time.group(1))
    mi = _try_int_local(m_time.group(2))
    s_val = _try_int_local(m_time.group(3) or "0")
    if (
        h is None
        or mi is None
        or s_val is None
        or not (0 <= h <= 23)
        or not (0 <= mi <= 59)
        or not (0 <= s_val <= 59)
    ):
        await m.answer(
            "Невірний час. Приклад: 23:30.",
            reply_markup=kb.as_markup() if kb else None,
        )
        return

    now = msk_now()
    tw_end_dt = now.replace(hour=h, minute=mi, second=0, microsecond=0)

    if tw_end_dt <= now:
        await m.answer(
            "Час закінчення має бути пізніше за поточний. Вкажи інший час.",
            reply_markup=kb.as_markup() if kb else None,
        )
        return

    delta = tw_end_dt - now
    mins = int(delta.total_seconds() // 60)
    if mins <= 0:
        await m.answer(
            "Вікно має бути хоча б кілька хвилин. Вкажи інший час.",
            reply_markup=kb.as_markup() if kb else None,
        )
        return

    if not wid:
        await m.answer("Не знайшов поточний watch. Почни редагування заново.")
        await state.clear()
        return

    tw_start_dt = now
    tw_start = tw_start_dt.strftime("%Y-%m-%d %H:%M:%S")
    tw_end = tw_end_dt.strftime("%Y-%m-%d %H:%M:%S")

    ok = update_watch_time_window(int(wid), tw_start, tw_end)
    if not ok:
        await m.answer(
            "Не зміг оновити вікно. Спробуй ще раз пізніше.",
            reply_markup=kb.as_markup() if kb else None,
        )
        return

    await state.clear()

    await m.answer(
        f"Вікно для watch #{wid} оновлено.\n"
        f"Нове вікно: {mins} хв, до {tw_end}",
        reply_markup=main_menu_kb(),
    )


# ---------- ДОДАТИ ПОСТ (емуляція matched) ----------


@router.callback_query(F.data.startswith("watch:add_post:"))
async def watch_add_post_start(cb: CallbackQuery, state: FSMContext):
    """
    Крок 1: користувач натиснув 'Додати пост' для конкретного wid.
    - Просимо переслати/дати сам пост (forward/reply).
    - Запам'ятовуємо wid у FSM (edit_wid_source).
    """
    try:
        wid = int(cb.data.split(":")[-1])
    except Exception:
        wid = None

    if not wid:
        await cb.answer("bad id", show_alert=True)
        return

    await state.set_state(EditWatch.source_input)
    await state.update_data(edit_wid_source=wid)

    kb = _edit_back_kb(wid)

    await cb.message.edit_text(
        f"Додати пост для watch #{wid}.\n"
        f"Перешли повідомлення з постом з каналу або зроби reply на нього тут.",
        reply_markup=kb.as_markup(),
    )


@router.message(EditWatch.source_input)
async def watch_add_post_receive(m: Message, state: FSMContext):
    """
    Крок 2: отримуємо пост (forward або reply) і емітуємо matched для цього watch'а.
    """
    data = await state.get_data()
    wid = data.get("edit_wid_source")
    if not wid:
        await m.answer("Не знайшов поточний watch. Почни редагування заново.")
        await state.clear()
        return

    kb = _edit_back_kb(wid)

    # беремо саме повідомлення-джерело:
    # - якщо користувач зробив reply на пост → m.reply_to_message
    # - якщо просто переслав пост → саме m
    src_msg = m.reply_to_message or m
    if not src_msg:
        await m.answer(
            "Не бачу повідомлення з постом. Перешли, будь ласка, сам пост з каналу "
            "або зроби reply на нього тут.",
            reply_markup=kb.as_markup(),
        )
        return

    try:
        ok = await manual_match_watch_from_message(int(wid), src_msg)
    except Exception as e:
        log.exception("watch_add_post_receive: manual_match failed wid=%s: %s", wid, e)
        ok = False

    if not ok:
        await m.answer(
            "Не вдалось привʼязати цей пост до watch. Перевір, що це пост з того самого каналу "
            "і що для watch заданий коректний source_url.",
            reply_markup=kb.as_markup(),
        )
        return

    await state.clear()

    await m.answer(
        f"Для watch #{wid} пост привʼязано як matched.\n"
        f"Він буде оброблятися як звичайний матч (views/deleted/Excel).",
        reply_markup=main_menu_kb(),
    )