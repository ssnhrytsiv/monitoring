from typing import Optional, List, Any, Callable
import os
import re
import logging
from datetime import timedelta
import json

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from app.bot.states import CreateWatch, BotWatch
from app.bot.keyboards import main_menu_kb, back_to_menu_kb, yes_no_kb
from app.services.posts_watch_result_db import create_watch, insert_watch_event
from app.services.time_utils import msk_now
from app.bot.services.channels_repo import resolve_cid_by_target, normalize_target_link, get_links_by_channel_ids
from app.utils.tg_links import sanitize_link
from app.utils.tg_links import extract_bot_username
from app.services import bot_watch_db

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


async def _send_watch_from_links_batch_bot(bot, targets: List[str], mins: int, template_id: int) -> bool:
    try:
        control_id = _control_chat_id()
        if not control_id:
            return False
        header = f"/watch_from_links {int(template_id)} --window-min {int(mins)}"
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


@router.callback_query(F.data == "menu:add_watch")
async def menu_add_watch(cb: CallbackQuery, state: FSMContext):
    await state.set_state(CreateWatch.channel_input)
    await cb.message.edit_text(
        "Введи t.me лінк(и) / інвайти / @username каналів, які треба моніторити:",
        reply_markup=back_to_menu_kb()
    )


@router.callback_query(F.data == "menu:add_bot_watch")
async def menu_add_bot_watch(cb: CallbackQuery, state: FSMContext):
    await state.set_state(BotWatch.bot_input)
    await cb.message.edit_text(
        "Надішли лінк/username бота (t.me/... або @username), якого треба відстежити. "
        "Після цього я попрошу текст очікуваної відповіді.",
        reply_markup=back_to_menu_kb()
    )


# --- Bot watch flow ---


@router.message(BotWatch.bot_input)
async def bot_watch_bot_input(m: Message, state: FSMContext):
    raw = (m.text or "").strip()
    username = extract_bot_username(raw)
    if not username:
        await m.answer("Це не схоже на бота (username має закінчуватись на bot/_bot). Надішли інший лінк/username.")
        return
    await state.update_data(bot_username=username)
    await state.set_state(BotWatch.expected_input)
    await m.answer(
        f"Бот: @{username}. Надішли текст/повідомлення, який очікуєш отримати від бота (буде порівнюватись дослівно після нормалізації).",
        reply_markup=back_to_menu_kb()
    )


@router.message(BotWatch.expected_input)
async def bot_watch_expected_input(m: Message, state: FSMContext):
    text = (m.text or "").strip()
    if not text:
        await m.answer("Очікуваний текст не може бути порожнім. Надішли повідомлення з текстом.")
        return
    data = await state.get_data()
    username = data.get("bot_username")
    if not username:
        await m.answer("Не зберіг бота, почни заново.", reply_markup=main_menu_kb())
        await state.clear()
        return

    try:
        wid = bot_watch_db.add_watch(username, text)
        await m.answer(f"Bot-watch створено: @{username}, watch_id={wid}. Меню:", reply_markup=main_menu_kb())
    except Exception as e:
        log.exception("Failed to add bot_watch: %s", e)
        await m.answer("Не зміг створити bot-watch, спробуй ще раз.", reply_markup=main_menu_kb())
    await state.clear()


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

    # За бажанням можна трохи зсунути старт назад, але не обов'язково:
    # tw_start_dt = now - timedelta(seconds=5)
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
    await state.set_state(CreateWatch.confirm)
    await m.answer(
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

    created: List[str] = []
    failed: List[str] = []

    control_id = _control_chat_id()

    sent_ok = False
    if control_id and tid:
        sent_ok = await _send_watch_from_links_batch_bot(cb.bot, targets, mins, int(tid))
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
                )
                try:
                    insert_watch_event(wid, "created", {"via": "bot_fallback"})
                except Exception:
                    pass
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
