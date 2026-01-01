from typing import Optional, List, Any, Callable
import os
import re
import logging
import json

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from app.bot.states import CreateWatch
from app.services import channel_db
from app.sheet_bot.services import gsheets_writer as gsw
from app.sheet_bot.services import gsheets_buffer as gsb
from app.bot.keyboards import main_menu_kb, back_to_menu_kb, yes_no_kb
from app.services.posts_watch_result_db import create_watch, insert_watch_event
from app.services.time_utils import msk_now
from app.bot.services.channels_repo import resolve_cid_by_target, normalize_target_link, get_links_by_channel_ids
from app.utils.tg_links import sanitize_link

router = Router()
log = logging.getLogger("bot_create_watch")

_LINK_RE = re.compile(r'(?i)\b((?:https?://|tg://|t\.me/)[^\s<>"\'\]\)]+)')


def _try_int(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _control_chat_id() -> Optional[int]:
    raw = os.getenv("CONTROL_CHAT") or os.getenv("CONTROL_PEER")
    if not raw:
        return None
    try:
        return int(str(raw).strip())
    except Exception:
        return None


def _project_kb(prefix: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="ALI", callback_data=f"{prefix}:ALI"),
                InlineKeyboardButton(text="PATRON", callback_data=f"{prefix}:PATRON"),
                InlineKeyboardButton(text="EXPRESS", callback_data=f"{prefix}:EXPRESS"),
            ]
        ]
    )


def _extract_urls(text: str) -> List[str]:
    try:
        from app.utils.link_parser import extract_links_any
        return extract_links_any(text) or []
    except Exception as e:
        log.exception(f"extract_urls failed: {e}")
        return []


def _extract_targets(text: str) -> List[str]:
    urls = _extract_urls(text)
    if urls:
        return urls
    parts: List[str] = []
    for line in (text or "").splitlines():
        for p in line.split():
            p = p.strip()
            if p:
                parts.append(p)
    return parts


def _first_line_title(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return "bot_template"
    first_word = text.split()[0]
    return first_word[:80]


def _parse_template_id(res: Any) -> Optional[int]:
    if res is None:
        return None
    if isinstance(res, int):
        return res
    if isinstance(res, dict):
        v = res.get("id") or res.get("template_id")
        if v is not None:
            return _try_int(v)
    return None


def _is_forward_message(m: Message) -> bool:
    if getattr(m, "forward_origin", None) is not None:
        return True
    if getattr(m, "forward_from_chat", None) is not None:
        return True
    if getattr(m, "forward_from", None) is not None:
        return True
    if getattr(m, "forward_sender_name", None):
        return True
    if getattr(m, "forward_date", None):
        return True
    if getattr(m, "forward_from_message_id", None):
        return True
    if getattr(m, "is_automatic_forward", None):
        return True
    if getattr(m, "is_forward", None):
        return True
    return False


def _unique_preserve(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in items:
        if not x:
            continue
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _collect_links_from_aiogram(src: Message, plain_text: str) -> List[str]:
    links: List[str] = []

    # 1) entities (text_link / url)
    entities = getattr(src, "entities", None) or getattr(src, "caption_entities", None) or []
    for e in entities:
        try:
            et = getattr(e, "type", None)
            if et == "text_link":
                u = getattr(e, "url", "") or ""
                if u:
                    links.append(u)
            elif et == "url":
                off = int(getattr(e, "offset", 0))
                ln = int(getattr(e, "length", 0))
                piece = plain_text[off:off + ln].strip()
                if piece:
                    links.append(piece)
        except Exception:
            continue

    # 2) "голі" URL у звичайному тексті
    for m_ in _LINK_RE.finditer(plain_text or ""):
        u = m_.group(1)
        if u:
            links.append(u)

    # 3) додатково — парсимо html_text через link_parser (там дістаються приховані t.me)
    html_text = (
        getattr(src, "html_text", None)
        or getattr(src, "text_html", None)
        or getattr(src, "html_caption", None)
        or getattr(src, "caption_html", None)
        or ""
    )
    try:
        from app.utils.link_parser import extract_links_any
        base_text = html_text or plain_text
        extra = extract_links_any(base_text) or []
    except Exception:
        extra = []

    if extra:
        merged: List[str] = list(links)
        for full in extra:
            full_s = str(full).strip()
            if not full_s:
                continue
            if full_s in merged:
                continue
            replaced = False
            # ⚠ тут ми більше НЕ віддаємо перевагу «довшому» рядку,
            # бо довший може містити HTML-хвіст. Просто додаємо, якщо ще не було.
            for cur in merged:
                if not cur:
                    continue
                if full_s.startswith(cur) and len(full_s) > len(cur):
                    # залишаємо коротший варіант
                    replaced = True
                    break
            if not replaced:
                merged.append(full_s)
        links = merged

    # 4) нормалізація + відрізання HTML-хвостів
    norm_links: List[str] = []
    for u in links:
        s = str(u).strip()
        if not s:
            continue

        # базова нормалізація (tg://, @user, tps:// → https://t.me/...)
        try:
            s = sanitize_link(s)
        except Exception:
            pass

        # якщо після t.me/... є шмат типу "">Текст</a — обрізаємо його
        low = s.lower()
        tpos = low.find("t.me/")
        if tpos != -1:
            cut = len(s)
            for ch in ('"', '<'):
                idx = s.find(ch, tpos)
                if idx != -1:
                    cut = min(cut, idx)
            if cut != len(s):
                s = s[:cut].rstrip('.,;:)]}>')
                try:
                    s = sanitize_link(s)
                except Exception:
                    pass

        if s:
            norm_links.append(s)

    return _unique_preserve(norm_links)


def _extract_targets_from_message(msg: Message) -> List[str]:
    plain_text = (getattr(msg, "text", None) or getattr(msg, "caption", None) or "").strip()
    links = _collect_links_from_aiogram(msg, plain_text)
    filtered: List[str] = []
    for u in links:
        s = str(u).strip()
        if not s:
            continue
        if "t.me/" in s or s.startswith("@") or s.startswith("tg://"):
            filtered.append(s)
    filtered = _unique_preserve(filtered)
    if filtered:
        return filtered
    return _extract_targets(plain_text)


async def _create_template_from_source(src: Message) -> Optional[int]:
    html_text = (
        getattr(src, "html_text", None)
        or getattr(src, "text_html", None)
        or getattr(src, "html_caption", None)
        or getattr(src, "caption_html", None)
    )
    plain_text = (getattr(src, "text", None) or getattr(src, "caption", None) or "").strip()
    text_for_template = (html_text or plain_text or "").strip()

    if not text_for_template:
        return None

    try:
        parsed_links = _collect_links_from_aiogram(src, plain_text)
        links_json = json.dumps(parsed_links, ensure_ascii=False) if parsed_links else None
    except Exception:
        links_json = None

    title = _first_line_title(plain_text or text_for_template)

    try:
        from app.services import post_watch_db as pdb
    except Exception as e:
        log.exception(f"create_template import failed: {e}")
        return None

    fn: Optional[Callable[..., Any]] = getattr(pdb, "add_template", None)
    if not fn:
        return None

    try:
        res = fn(text=text_for_template, title=title, mode="exact", links=links_json)
        tid = _parse_template_id(res)
        if tid:
            return tid
    except TypeError:
        try:
            res = fn(text=text_for_template, title=title, links=links_json)
            tid = _parse_template_id(res)
            if tid:
                return tid
        except TypeError:
            try:
                res = fn(text=text_for_template, title=title)
                tid = _parse_template_id(res)
                if tid:
                    return tid
            except TypeError:
                try:
                    res = fn(text_for_template)
                    tid = _parse_template_id(res)
                    if tid:
                        return tid
                except Exception:
                    return None
    except Exception:
        return None

    return None


async def _send_watch_from_links_batch_bot(bot, targets: List[str], mins: int, template_id: int, project: Optional[str]) -> bool:
    try:
        control_id = _control_chat_id()
        if not control_id:
            return False
        header = f"/watch_from_links {int(template_id)} --window-min {int(mins)}"
        if project:
            header += f" --project {project}"
        body = "\n".join(targets)
        cmd = header + "\n" + body if body else header
        await bot.send_message(control_id, cmd)
        return True
    except Exception as e:
        log.exception(f"send_batch_bot failed: {e}")
        return False


@router.message(F.text == "/start")
async def start_cmd(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Меню:", reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu:home")
async def menu_home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.edit_text("Меню:", reply_markup=main_menu_kb())
    except TelegramBadRequest:
        await cb.message.answer("Меню:", reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu:sheet_mgmt")
async def menu_sheet_mgmt(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Створити таблицю для цього місяця", callback_data="sheet:create")],
            [InlineKeyboardButton(text="📂 Архівні таблиці", callback_data="sheet:archive")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")],
        ]
    )
    await cb.message.edit_text("Управління таблицями:", reply_markup=kb)


@router.callback_query(F.data == "sheet:create")
async def sheet_create_pick(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Обери проєкт для створення таблиці цього місяця:", reply_markup=_project_kb("sheet:create_proj"))


def _sheet_title(project: str) -> str:
    now = msk_now()
    months = {
        1: "Январь",
        2: "Февраль",
        3: "Март",
        4: "Апрель",
        5: "Май",
        6: "Июнь",
        7: "Июль",
        8: "Август",
        9: "Сентябрь",
        10: "Октябрь",
        11: "Ноябрь",
        12: "Декабрь",
    }
    month_name = months.get(now.month, now.strftime("%m"))
    return f"Планувальщик для {project} [{month_name} {now.year}]"


@router.callback_query(F.data.startswith("sheet:create_proj:"))
async def sheet_create_project(cb: CallbackQuery, state: FSMContext):
    proj = cb.data.split("sheet:create_proj:", 1)[1]
    title = _sheet_title(proj)
    # Якщо вже є активна таблиця з цим самим місяцем/назвою — просто показуємо її
    existing = channel_db.get_active_sheet(proj)
    if existing and (existing.get("title") == title):
        ssid = existing.get("spreadsheet_id")
        url = f"https://docs.google.com/spreadsheets/d/{ssid}"
        await cb.message.edit_text(
            f"Для {proj} вже є активна таблиця цього місяця:\n{title}\n{url}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")]]),
            disable_web_page_preview=True,
        )
        return

    try:
        res = gsw.create_spreadsheet(title)
        if not res or not res.get("spreadsheet_id"):
            raise RuntimeError("create_spreadsheet returned no id")
        ssid = res["spreadsheet_id"]
        channel_db.set_active_sheet(proj, ssid, title)
        url = f"https://docs.google.com/spreadsheets/d/{ssid}"
        await cb.message.edit_text(
            f"Таблиця створена і встановлена як активна для {proj}:\n{title}\n{url}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")]]),
        )
    except Exception as e:
        log.exception("sheet create failed: %s", e)
        await cb.message.edit_text(
            f"Не вдалося створити таблицю: {e}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")]]),
        )


@router.callback_query(F.data == "sheet:archive")
async def sheet_archive(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    projects = channel_db.list_sheet_projects()
    if not projects:
        await cb.message.edit_text(
            "Архів порожній.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")]]),
        )
        return
    row = [InlineKeyboardButton(text=p, callback_data=f"sheet:archive_proj:{p}") for p in projects]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            row,
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")],
        ]
    )
    await cb.message.edit_text("Оберіть проєкт для перегляду архіву:", reply_markup=kb)


@router.callback_query(F.data.startswith("sheet:archive_proj:"))
async def sheet_archive_project(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    proj = cb.data.split("sheet:archive_proj:", 1)[1]
    rows = channel_db.list_archived_sheets(project=proj)
    if not rows:
        txt = f"Архів порожній для проєкту {proj}."
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ До проєктів", callback_data="sheet:archive")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")],
            ]
        )
        await cb.message.edit_text(txt, reply_markup=kb, disable_web_page_preview=True)
        return

    # Сортуємо за датою архівації (новіші зверху), далі за назвою
    rows_sorted = sorted(
        rows,
        key=lambda r: (r.get("archived_at") or "", r.get("title") or ""),
        reverse=True,
    )

    def _btn_label(title: str) -> str:
        parts = title.strip().split()
        if len(parts) >= 2:
            # беремо останні два слова як "місяць рік"
            return " ".join(parts[-2:])
        return title[:32]

    buttons = []
    for r in rows_sorted[:30]:  # максимум 15 рядків по 2 кнопки
        title = r.get("title") or ""
        url = f"https://docs.google.com/spreadsheets/d/{r.get('spreadsheet_id')}"
        buttons.append(InlineKeyboardButton(text=_btn_label(title), url=url))

    kb_rows = []
    for i in range(0, len(buttons), 2):
        kb_rows.append(buttons[i:i + 2])
    kb_rows.append([InlineKeyboardButton(text="⬅️ До проєктів", callback_data="sheet:archive")])
    kb_rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await cb.message.edit_text(
        f"Архівні таблиці для {proj}:\n(кнопки відкривають таблицю)",
        reply_markup=kb,
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "menu:add_watch")
async def menu_add_watch(cb: CallbackQuery, state: FSMContext):
    await state.set_state(CreateWatch.channel_input)
    await cb.message.edit_text(
        "Введи t.me лінк(и) / інвайти / @username каналів, які треба моніторити:",
        reply_markup=back_to_menu_kb()
    )




@router.message(CreateWatch.channel_input)
async def step_channel_input(m: Message, state: FSMContext):
    targets = _extract_targets_from_message(m)
    if not targets:
        await m.answer("Не знайшов валідних t.me лінків або target'ів. Спробуй ще раз.")
        return
    await state.update_data(targets=targets)
    await state.set_state(CreateWatch.template_pick)
    await m.answer(
        "Надішли ID шаблону числом або перешли/відповідай повідомленням з шаблоном.",
        reply_markup=back_to_menu_kb()
    )


@router.message(CreateWatch.template_pick)
async def step_template_pick_manual(m: Message, state: FSMContext):
    direct_text = (m.text or "").strip()
    has_reply = m.reply_to_message is not None
    is_forward = _is_forward_message(m)

    if (not has_reply) and (not is_forward) and direct_text and re.fullmatch(r"\d{1,9}", direct_text):
        direct_id = _try_int(direct_text)
        if direct_id:
            await state.update_data(template_id=direct_id)
            await state.set_state(CreateWatch.time_window)
            await m.answer(
                "Вкажи час закінчення вікна СЬОГОДНІ у форматі HH:MM, наприклад 23:30.",
                reply_markup=back_to_menu_kb()
            )
            return

    src = m.reply_to_message if has_reply else m
    tid = await _create_template_from_source(src)

    if not tid:
        await m.answer("Не зміг створити шаблон. Надішли числовий template_id або інший пост.")
        return

    await state.update_data(template_id=tid)
    await state.set_state(CreateWatch.time_window)
    await m.answer(
        f"Шаблон додано (id={tid}). Вкажи час закінчення вікна СЬОГОДНІ у форматі HH:MM, наприклад 23:30.",
        reply_markup=back_to_menu_kb()
    )


@router.message(CreateWatch.time_window)
async def step_time_window(m: Message, state: FSMContext):
    text = (m.text or "").strip()
    m_time = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text)
    if not m_time:
        await m.answer("Введи час у форматі HH:MM, наприклад 23:30.")
        return

    h = _try_int(m_time.group(1))
    mi = _try_int(m_time.group(2))
    s = _try_int(m_time.group(3) or "0")
    if h is None or mi is None or s is None or not (0 <= h <= 23) or not (0 <= mi <= 59) or not (0 <= s <= 59):
        await m.answer("Невірний час. Приклад: 23:30.")
        return

    now = msk_now()

    # НОРМАЛІЗАЦІЯ: вікно "до HH:MM" → завжди секунда = 0
    tw_end_dt = now.replace(hour=h, minute=mi, second=0, microsecond=0)

    if tw_end_dt <= now:
        await m.answer("Час закінчення має бути пізніше за поточний. Вкажи інший час.")
        return

    delta = tw_end_dt - now
    mins = int(delta.total_seconds() // 60)
    if mins <= 0:
        await m.answer("Вікно має бути хоча б кілька хвилин. Вкажи інший час.")
        return

    tw_start_dt = now

    tw_start = tw_start_dt.strftime("%Y-%m-%d %H:%M:%S")
    tw_end = tw_end_dt.strftime("%Y-%m-%d %H:%M:%S")

    data = await state.get_data()
    targets: List[str] = data.get("targets") or []
    tid = data.get("template_id")

    await state.update_data(time_window_start=tw_start, time_window_end=tw_end, mins=mins)

    targets_txt = "\n".join(f"• {t}" for t in targets)
    txt = (
        f"Підтверди створення watch:\n\n"
        f"targets:\n{targets_txt}\n\n"
        f"template_id: {tid or '—'}\n"
        f"вікно: {mins} хв\n"
        f"до: {tw_end}\n"
    )
    await state.set_state(CreateWatch.project_pick)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="ALI", callback_data="watch_proj:ALI"),
                InlineKeyboardButton(text="PATRON", callback_data="watch_proj:PATRON"),
                InlineKeyboardButton(text="EXPRESS", callback_data="watch_proj:EXPRESS"),
            ]
        ]
    )
    await m.answer(
        txt + "\nОбери проєкт:",
        reply_markup=kb,
        parse_mode=None
    )


@router.callback_query(CreateWatch.project_pick, F.data.startswith("watch_proj:"))
async def pick_project(cb: CallbackQuery, state: FSMContext):
    proj = cb.data.split("watch_proj:", 1)[1]
    await state.update_data(project=proj)
    data = await state.get_data()
    mins = int(data["mins"])
    tid = data.get("template_id")
    targets: List[str] = data.get("targets") or []
    tw_end = data.get("time_window_end")
    proj_txt = proj
    targets_txt = "\n".join(f"• {t}" for t in targets)
    txt = (
        f"Підтверди створення watch:\n\n"
        f"targets:\n{targets_txt}\n\n"
        f"template_id: {tid or '—'}\n"
        f"вікно: {mins} хв\n"
        f"до: {tw_end}\n"
        f"проєкт: {proj_txt}\n"
    )
    await state.set_state(CreateWatch.confirm)
    await cb.message.edit_text(
        txt,
        reply_markup=yes_no_kb("watch:confirm_yes", "watch:confirm_no"),
        parse_mode=None
    )


@router.callback_query(CreateWatch.confirm, F.data == "watch:confirm_no")
async def confirm_no(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Скасовано.", reply_markup=main_menu_kb())


@router.callback_query(CreateWatch.confirm, F.data == "watch:confirm_yes")
async def confirm_yes(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    mins = int(data["mins"])
    tid = data.get("template_id")
    targets: List[str] = data.get("targets") or []
    project = data.get("project")

    created: List[str] = []
    failed: List[str] = []

    control_id = _control_chat_id()

    sent_ok = False
    if control_id and tid:
        sent_ok = await _send_watch_from_links_batch_bot(cb.bot, targets, mins, int(tid), project)
        if sent_ok:
            created.extend(targets)
        else:
            failed.extend(targets)

    if (not control_id) or (control_id and not sent_ok):
        cids: List[int] = []
        for t in targets:
            cid = resolve_cid_by_target(t)
            if cid:
                cids.append(cid)
        links_map = get_links_by_channel_ids(cids)
        targets_links: List[str] = []
        for t in targets:
            cid = resolve_cid_by_target(t)
            link = links_map.get(cid) if cid else None
            norm = normalize_target_link(t, link)
            if norm:
                targets_links.append(norm)
        targets_links = _unique_preserve(targets_links)
        channels_links_json = json.dumps(targets_links, ensure_ascii=False) if targets_links else None

        for t in targets:
            cid = resolve_cid_by_target(t)
            if not cid or not tid:
                failed.append(t)
                continue
            try:
                wid = create_watch(
                    channel_id=int(cid),
                    template_id=int(tid),
                    expected_text_hash=None,
                    expected_text_norm_len=None,
                    expected_links_json=channels_links_json,
                    expected_media_fingerprint=None,
                    time_window_start=data.get("time_window_start"),
                    time_window_end=data.get("time_window_end"),
                    source_url=links_map.get(int(cid)),
                    created_by=None,
                    project=project,
                )
                try:
                    insert_watch_event(wid, "created", {"via": "bot_fallback"})
                except Exception:
                    pass
                if project:
                    try:
                        sheet = channel_db.get_active_sheet(project)
                        if sheet and sheet.get("spreadsheet_id"):
                            log.info("watch %s bound to project %s sheet=%s", wid, project, sheet.get("spreadsheet_id"))
                    except Exception:
                        log.exception("bind watch to project failed")
                created.append(f"{t} (fallback wid={wid})")
            except Exception:
                failed.append(t)

    await state.clear()

    msg_parts: List[str] = []
    if created:
        if control_id and sent_ok:
            msg_parts.append("✅ Команду /watch_from_links відправлено в CONTROL_CHAT для:\n" + "\n".join(f"• {x}" for x in created))
        else:
            msg_parts.append("✅ Watch(и) створено через fallback:\n" + "\n".join(f"• {x}" for x in created))
    if failed:
        msg_parts.append("⚠️ Не вдалося створити watch для:\n" + "\n".join(f"• {x}" for x in failed))
    if not msg_parts:
        msg_parts.append("❌ Не вдалося створити watch. Перевір CONTROL_CHAT/CONTROL_PEER і доступ MAIN клієнта.")

    await cb.message.edit_text("\n\n".join(msg_parts), reply_markup=main_menu_kb(), parse_mode=None)
