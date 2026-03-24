from typing import Optional, List, Any, Callable
import os
import re
import logging
import json
import math
import html
from datetime import timedelta, date
from difflib import SequenceMatcher

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from app.config import TEMPLATE_MEDIA_VAULT_CHAT_ID
from app.watch_bot.states import CreateWatch, TemplateCreate
from app.DAL import SessionLocal
from app.DAL import sheet_projects_operations as spo
from app.DAL import post_templates_operations as post_watch_db
from app.DAL import watch_posts_operations as watch_posts_db
from app.DAL import watch_events_operations as watch_events_db
from app.DAL.channel_subscription_audit_operations import (
    count_missing_channels_for_all_admins,
)
from app.sheet_bot.services import gsheets_writer as gsw
from app.sheet_bot.services import gsheets_buffer as gsb
from app.watch_bot.keyboards import main_menu_kb, back_to_menu_kb, yes_no_kb, templates_kb
from app.services.time_utils import msk_now
from app.watch_bot.services.channels_repo import (
    resolve_cid_by_target,
    normalize_target_link,
    get_links_by_channel_ids,
    get_titles_by_channel_ids,
)
from app.utils.link_parser import sanitize_link
from app.utils.watch_link_extractor import normalize_links_for_watch
from app.admin_bot.services import admins as svc_admins
from app.admin_bot.services import networks as svc_networks
from app.admin_bot.services.networks import channel_hyperlink
from app.admin_bot.db.session import SessionLocal as AdminSession
from app.admin_bot.db import models as adm_models
from app.DAL import channels_operations as cho

router = Router()
log = logging.getLogger("bot_create_watch")

_LINK_RE = re.compile(r'(?i)\b((?:https?://|tg://|t\.me/)[^\s<>"\'\]\)]+)')
_ADMINS_PER_ROW = 2
_ADMINS_PER_PAGE = 36
_V2_MEDIA_PREFIX = "v2media:"


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


def _admin_session():
    db = AdminSession()
    try:
        yield db
    finally:
        db.close()


def _load_template(template_id: int) -> Optional[dict]:
    """
    Завантажує шаблон із SQLite (post_template) і повертає словник із HTML та links_json.
    """
    try:
        tpl = post_watch_db.get_template_by_id(int(template_id))
        if not tpl:
            return None
        _, tpl_html, tpl_mode, tpl_thr, created_at, tpl_title, tpl_links_json, tpl_photo_id = tpl
        return {
            "html": tpl_html,
            "links_json": tpl_links_json,
            "mode": tpl_mode,
            "threshold": tpl_thr,
            "title": tpl_title,
            "created_at": created_at,
            "photo_id": tpl_photo_id,
            "is_reply": bool(post_watch_db.is_template_reply(int(template_id))),
        }
    except Exception:
        log.warning("watch_net: failed to load template id=%s", template_id, exc_info=True)
        return None


def _template_preview_kb(template_id: int, is_reply: bool) -> InlineKeyboardMarkup:
    toggle_text = "💬 Ответка: Вкл" if is_reply else "💬 Ответка: Выкл"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data=f"tpl:toggle_reply:{template_id}")],
            [InlineKeyboardButton(text="⬅️ До шаблонів", callback_data="menu:list_templates")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")],
        ]
    )


def _render_template_preview_text(template_id: int, template_row: tuple, is_reply: bool) -> str:
    template_text = str(template_row[1] or "").strip()
    template_title = str(template_row[5] or f"Template #{template_id}").strip()
    reply_label = "Так" if is_reply else "Ні"
    preview_body = template_text[:3000]
    if len(template_text) > len(preview_body):
        preview_body = preview_body.rstrip() + "…"
    return (
        f"<b>Шаблон #{template_id}</b>\n"
        f"<b>Назва:</b> {html.escape(template_title)}\n"
        f"<b>Ответка:</b> {reply_label}\n\n"
        f"{html.escape(preview_body)}"
    )


def _admins_kb(page: int = 0):
    db = next(_admin_session())
    admins = svc_admins.list_admins(db)
    admins = sorted(admins, key=lambda a: (a.display or a.username or f"{a.id}"))
    total_pages = max(1, math.ceil(len(admins) / _ADMINS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))
    start = page * _ADMINS_PER_PAGE
    end = start + _ADMINS_PER_PAGE
    admins_page = admins[start:end]
    rows = []
    row = []
    for a in admins_page:
        label = a.display or a.username or f"id={a.id}"
        row.append(InlineKeyboardButton(text=label, callback_data=f"watchnet:admin:{a.id}"))
        if len(row) == _ADMINS_PER_ROW:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav = []
    if total_pages > 1:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"watchnet:page:{(page-1)%total_pages}"))
        nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"watchnet:page:{(page+1)%total_pages}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _networks_kb(admin_id: int):
    db = next(_admin_session())
    nets = svc_networks.list_networks_by_admin(db, admin_id)
    nets = sorted(nets, key=lambda n: (n.name or ""))
    rows = []
    row = []
    for n in nets:
        row.append(InlineKeyboardButton(text=n.name, callback_data=f"watchnet:net:{admin_id}:{n.id}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Адміни", callback_data="menu:add_watch_net")])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _targets_from_network(net_id: int) -> List[str]:
    db = next(_admin_session())
    rows = (
        db.query(adm_models.Channel)
        .join(adm_models.NetworkChannel, adm_models.NetworkChannel.channel_id == adm_models.Channel.channel_id)
        .filter(adm_models.NetworkChannel.network_id == net_id)
        .order_by(adm_models.Channel.title)
        .all()
    )
    targets: List[str] = []
    seen = set()
    for ch in rows:
        if ch.username:
            t = f"@{ch.username}"
        else:
            t = str(ch.channel_id)
        if t not in seen:
            seen.add(t)
            targets.append(t)
    return targets


def _network_channels_preview(net_id: int) -> tuple[list[str], list[str]]:
    db = next(_admin_session())
    rows = (
        db.query(adm_models.Channel)
        .join(adm_models.NetworkChannel, adm_models.NetworkChannel.channel_id == adm_models.Channel.channel_id)
        .filter(adm_models.NetworkChannel.network_id == net_id)
        .order_by(adm_models.Channel.title)
        .all()
    )
    seen = set()
    targets: List[str] = []
    lines: List[str] = []
    for ch in rows:
        if ch.username:
            target = f"@{ch.username}"
        else:
            target = str(ch.channel_id)
        if target in seen:
            continue
        seen.add(target)
        targets.append(target)
        lines.append(f"• {channel_hyperlink(db, ch)}")
    return targets, lines


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


def _parse_iso_date(value: str) -> Optional[date]:
    try:
        return date.fromisoformat(value)
    except Exception:
        return None


def _watch_day_kb() -> InlineKeyboardMarkup:
    now = msk_now()
    d0 = now.date()
    d1 = (now + timedelta(days=1)).date()
    d2 = (now + timedelta(days=2)).date()
    rows = [
        [
            InlineKeyboardButton(text="Сьогодні", callback_data=f"watch_day:{d0.isoformat()}"),
            InlineKeyboardButton(text=f"Завтра • {d1.strftime('%d.%m')}", callback_data=f"watch_day:{d1.isoformat()}"),
            InlineKeyboardButton(text=f"Післязавтра • {d2.strftime('%d.%m')}", callback_data=f"watch_day:{d2.isoformat()}"),
        ],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _watch_time_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="17:00", callback_data="watch_time:17:00"),
                InlineKeyboardButton(text="19:00", callback_data="watch_time:19:00"),
                InlineKeyboardButton(text="21:00", callback_data="watch_time:21:00"),
            ],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:home")],
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
    """
    Будує заголовок із перших двох слів, ігноруючи початкові символи/емодзі.
    Якщо слів немає — повертає обрізаний текст або резервний рядок.
    """
    import re

    text = (text or "").strip()
    if not text:
        return ""

    # прибираємо провідні не-алфанум символи (емодзі, знаки)
    text = re.sub(r"^\W+", "", text, flags=re.UNICODE)

    # вибираємо слова (букви/цифри/апостроф/дефіс)
    raw_tokens = re.findall(r"[\w’'\-]+", text, flags=re.UNICODE)
    tokens = [t for t in raw_tokens if re.search(r"\w", t, flags=re.UNICODE)]
    if not tokens:
        return text[:80]

    title = " ".join(tokens[:2])
    return title[:80]


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

    return normalize_links_for_watch(links)


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


def _extract_template_text_parts(src: Message) -> tuple[str, str, str]:
    html_text = (
        getattr(src, "html_text", None)
        or getattr(src, "text_html", None)
        or getattr(src, "html_caption", None)
        or getattr(src, "caption_html", None)
    )
    plain_text = (getattr(src, "text", None) or getattr(src, "caption", None) or "").strip()
    text_for_template = (html_text or plain_text or "").strip()
    return str(html_text or ""), plain_text, text_for_template


def _message_has_template_media(src: Message) -> bool:
    return bool(
        getattr(src, "photo", None)
        or getattr(src, "video", None)
        or getattr(src, "animation", None)
    )


def _build_vault_only_media_payload(chat_id: int, message_id: int) -> str:
    return (
        f'{_V2_MEDIA_PREFIX}'
        f'{{"type":"photo","ids":{{}},"vault":{{"chat_id":{int(chat_id)},"message_id":{int(message_id)}}}}}'
    )


async def _build_template_media_payload_from_source(src: Message) -> Optional[str]:
    if not _message_has_template_media(src):
        return None

    target_chat_id = int(TEMPLATE_MEDIA_VAULT_CHAT_ID or 0)
    if not target_chat_id:
        log.warning(
            "create_template: media present but TEMPLATE_MEDIA_VAULT_CHAT_ID is not configured; source=%s:%s",
            getattr(getattr(src, "chat", None), "id", None),
            getattr(src, "message_id", None),
        )
        return None

    bot = getattr(src, "bot", None)
    if bot is None:
        log.warning(
            "create_template: media present but message.bot is missing; source=%s:%s",
            getattr(getattr(src, "chat", None), "id", None),
            getattr(src, "message_id", None),
        )
        return None

    try:
        copied = await bot.copy_message(
            chat_id=target_chat_id,
            from_chat_id=int(src.chat.id),
            message_id=int(src.message_id),
            disable_notification=True,
        )
        copied_message_id = _try_int(getattr(copied, "message_id", None))
        if not copied_message_id:
            log.warning(
                "create_template: media vault copy returned empty message_id; source=%s:%s target=%s",
                getattr(src.chat, "id", None),
                getattr(src, "message_id", None),
                target_chat_id,
            )
            return None
        return _build_vault_only_media_payload(target_chat_id, copied_message_id)
    except Exception:
        log.exception(
            "create_template: media vault copy failed; source=%s:%s target=%s",
            getattr(src.chat, "id", None),
            getattr(src, "message_id", None),
            target_chat_id,
        )
        return None


async def _create_template_from_source(src: Message) -> Optional[tuple[int, str, bool]]:
    _html_text, plain_text, text_for_template = _extract_template_text_parts(src)

    if not text_for_template:
        log.info("create_template: empty text_for_template (message_id=%s)", getattr(src, "message_id", None))
        return None

    try:
        parsed_links = _collect_links_from_aiogram(src, plain_text)
        links_json = json.dumps(parsed_links, ensure_ascii=False) if parsed_links else None
    except Exception:
        log.warning("create_template: failed to parse links (message_id=%s)", getattr(src, "message_id", None), exc_info=True)
        links_json = None

    title = _first_line_title(plain_text or text_for_template)
    has_media = _message_has_template_media(src)
    photo_id = await _build_template_media_payload_from_source(src)
    media_ready = (not has_media) or bool(photo_id)

    try:
        from app.DAL import post_templates_operations as pdb
    except Exception as e:
        log.exception(f"create_template import failed: {e}")
        return None

    fn: Optional[Callable[..., Any]] = getattr(pdb, "add_template", None)
    if not fn:
        log.warning("create_template: add_template not found in post_templates_operations")
        return None

    try:
        res = fn(text=text_for_template, title=title, mode="exact", links=links_json, photo_id=photo_id)
        tid = _parse_template_id(res)
        if tid:
            log.info("create_template: created template id=%s title=%s", tid, title)
            return tid, title, media_ready
    except TypeError:
        try:
            res = fn(text=text_for_template, title=title, links=links_json, photo_id=photo_id)
            tid = _parse_template_id(res)
            if tid:
                log.info("create_template: created template id=%s title=%s (fallback no mode)", tid, title)
                return tid, title, media_ready
        except TypeError:
            try:
                res = fn(text=text_for_template, title=title)
                tid = _parse_template_id(res)
                if tid:
                    log.info("create_template: created template id=%s title=%s (fallback no links)", tid, title)
                    return tid, title, media_ready
            except TypeError:
                try:
                    res = fn(text_for_template)
                    tid = _parse_template_id(res)
                    if tid:
                        log.info("create_template: created template id=%s (legacy signature)", tid)
                        return tid, title, media_ready
                except Exception:
                    log.exception("create_template: add_template failed (legacy)")
                    return None
    except Exception:
        log.exception("create_template: add_template failed (main)")
        return None
    log.warning("create_template: failed to create template (message_id=%s)", getattr(src, "message_id", None))
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


@router.callback_query(F.data == "menu:missing_channels")
async def menu_missing_channels(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    total_missing_channels_count = count_missing_channels_for_all_admins()
    response_text = f"Missing к-сть каналів: {total_missing_channels_count}"
    try:
        await cb.message.edit_text(response_text, reply_markup=main_menu_kb())
    except TelegramBadRequest:
        await cb.message.answer(response_text, reply_markup=main_menu_kb())
    await cb.answer()


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
    db = SessionLocal()
    try:
        existing = None
        rec = spo.get_active_sheet(db, proj)
        if rec:
            existing = {
                "project": rec.project,
                "spreadsheet_id": rec.active_spreadsheet_id,
                "title": rec.active_title,
                "updated_at": rec.updated_at,
            }
    finally:
        db.close()
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
        db = SessionLocal()
        try:
            spo.set_active_sheet(db, proj, ssid, title)
        finally:
            db.close()
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
    db = SessionLocal()
    try:
        projects = sorted(set(spo.list_projects(db) or []))
    finally:
        db.close()
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
    db = SessionLocal()
    try:
        rows = spo.list_archives(db, project=proj)
    finally:
        db.close()
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


@router.callback_query(F.data == "menu:add_watch_net")
async def menu_add_watch_net(cb: CallbackQuery, state: FSMContext):
    await state.set_state(CreateWatch.admin_pick)
    log.info("watch_net: start admin pick")
    await cb.message.edit_text(
        "Оберіть адміна для вотчу:",
        reply_markup=_admins_kb(),
        disable_web_page_preview=True,
    )


@router.callback_query(CreateWatch.admin_pick, F.data.startswith("watchnet:admin:"))
async def pick_admin_for_watch(cb: CallbackQuery, state: FSMContext):
    try:
        admin_id = int(cb.data.split(":", 2)[2])
    except Exception:
        await cb.answer()
        return
    log.info("watch_net: admin picked id=%s by user=%s", admin_id, cb.from_user.id if cb.from_user else None)
    await state.update_data(admin_id=admin_id)
    await state.set_state(CreateWatch.network_pick)
    await cb.message.edit_text(
        "Оберіть сітку:",
        reply_markup=_networks_kb(admin_id),
        disable_web_page_preview=True,
    )
    await cb.answer()


@router.callback_query(F.data == "menu:list_templates")
async def list_templates(cb: CallbackQuery, state: FSMContext):
    templates = post_watch_db.list_templates_full(limit=50)
    items = []
    for t in templates:
        template_id = int(t[0])
        template_title = t[5]
        title_prefix = "💬 " if post_watch_db.is_template_reply(template_id) else ""
        items.append({"id": template_id, "title": f"{title_prefix}{template_title or f'Template #{template_id}'}"})
    kb = templates_kb(items)
    await state.clear()
    await cb.message.edit_text("Шаблони постів:", reply_markup=kb, disable_web_page_preview=True)
    await cb.answer()


@router.callback_query(F.data == "tpl:add")
async def tpl_add_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(TemplateCreate.title)
    await cb.message.edit_text("Надішли назву для шаблону.", reply_markup=back_to_menu_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("tpl:toggle_reply:"))
async def toggle_template_reply(cb: CallbackQuery, state: FSMContext):
    try:
        template_id = int(cb.data.split(":")[-1])
    except Exception:
        await cb.answer()
        return
    template_row = post_watch_db.get_template_by_id(template_id)
    if not template_row:
        await cb.answer("Шаблон не знайдено", show_alert=False)
        return
    current_value = post_watch_db.is_template_reply(template_id)
    updated_row = post_watch_db.set_template_reply(template_id, not current_value)
    updated_is_reply = bool(getattr(updated_row, "is_reply", False)) if updated_row is not None else (not current_value)
    await cb.message.edit_text(
        _render_template_preview_text(template_id, template_row, updated_is_reply),
        reply_markup=_template_preview_kb(template_id, updated_is_reply),
        disable_web_page_preview=True,
        parse_mode="HTML",
    )
    await cb.answer("Ответка включена" if updated_is_reply else "Ответка выключена")


@router.callback_query(F.data.startswith("tpl:"))
async def show_template_preview(cb: CallbackQuery, state: FSMContext):
    if cb.data == "tpl:add" or cb.data.startswith("tpl:toggle_reply:"):
        await cb.answer()
        return
    try:
        template_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    template_row = post_watch_db.get_template_by_id(template_id)
    if not template_row:
        await cb.answer("Шаблон не знайдено", show_alert=False)
        return
    is_reply = post_watch_db.is_template_reply(template_id)
    await state.clear()
    await cb.message.edit_text(
        _render_template_preview_text(template_id, template_row, is_reply),
        reply_markup=_template_preview_kb(template_id, is_reply),
        disable_web_page_preview=True,
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(TemplateCreate.title)
async def tpl_add_title(m: Message, state: FSMContext):
    title = (m.text or "").strip()
    if not title:
        await m.answer("Порожня назва. Надішли назву ще раз.", reply_markup=back_to_menu_kb())
        return
    await state.update_data(tpl_title=title)
    await state.set_state(TemplateCreate.body)
    await m.answer("Тепер надішли текст/пост для шаблону (буде збережений як є).", reply_markup=back_to_menu_kb())


@router.message(TemplateCreate.body)
async def tpl_add_body(m: Message, state: FSMContext):
    _html_text, _plain_text, body = _extract_template_text_parts(m)
    body = body.strip()
    if not body:
        await m.answer("Порожній текст. Надішли пост ще раз.", reply_markup=back_to_menu_kb())
        return
    data = await state.get_data()
    title = data.get("tpl_title") or "Без назви"
    has_media = _message_has_template_media(m)
    parsed_links = _collect_links_from_aiogram(m, str(getattr(m, "text", None) or getattr(m, "caption", None) or ""))
    links_json = json.dumps(parsed_links, ensure_ascii=False) if parsed_links else None
    photo_id = await _build_template_media_payload_from_source(m)
    tpl_id = post_watch_db.add_template(text=body, title=title, mode="exact", links=links_json, photo_id=photo_id)
    await state.clear()
    response_text = f"Шаблон збережено (id={tpl_id})."
    if has_media and not photo_id:
        response_text += (
            "\n\n⚠️ Media не збережене у monitoring, бо TEMPLATE_MEDIA_VAULT_CHAT_ID не налаштований "
            "або vault copy не вдався."
        )
    await m.answer(response_text, reply_markup=back_to_menu_kb())

@router.callback_query(CreateWatch.admin_pick, F.data.startswith("watchnet:page:"))
async def paginate_admins(cb: CallbackQuery):
    try:
        page = int(cb.data.split(":", 2)[2])
    except Exception:
        await cb.answer()
        return
    await cb.message.edit_text(
        "Оберіть адміна для вотчу:",
        reply_markup=_admins_kb(page),
        disable_web_page_preview=True,
    )
    log.info("watch_net: admin page=%s", page)
    await cb.answer()


@router.callback_query(CreateWatch.network_pick, F.data.startswith("watchnet:net:"))
async def pick_network_for_watch(cb: CallbackQuery, state: FSMContext):
    try:
        _, _, admin_id, net_id = cb.data.split(":", 3)
        admin_id = int(admin_id)
        net_id = int(net_id)
    except Exception:
        await cb.answer()
        return
    targets, lines = _network_channels_preview(net_id)
    if not targets:
        await cb.answer("У сітки немає каналів", show_alert=True)
        return
    await state.update_data(admin_id=admin_id, network_id=net_id, targets=targets)
    await state.set_state(CreateWatch.template_pick)
    log.info("watch_net: network picked admin=%s net=%s targets=%s", admin_id, net_id, targets)
    targets_txt = "\n".join(lines)
    await cb.message.edit_text(
        f"Знайдено {len(targets)} каналів у сітці.\n\n{targets_txt}\n\nНадішли ID шаблону або пост для шаблону.",
        reply_markup=back_to_menu_kb(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await cb.answer()



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
            tpl_meta = post_watch_db.get_template_by_id(int(direct_id))
            tpl_title = tpl_meta[5] if tpl_meta else None
            await state.update_data(template_id=direct_id, template_title=tpl_title)
            await state.set_state(CreateWatch.day_pick)
            await m.answer(
                "Обери день закінчення вікна:",
                reply_markup=_watch_day_kb(),
            )
            return

    src = m.reply_to_message if has_reply else m
    tpl_created = await _create_template_from_source(src)
    tid = tpl_created[0] if tpl_created else None
    tpl_title = tpl_created[1] if tpl_created else None
    media_ready = bool(tpl_created[2]) if tpl_created else True

    if not tid:
        await m.answer("Не зміг створити шаблон. Надішли числовий template_id або інший пост.")
        return

    await state.update_data(template_id=tid, template_title=tpl_title)
    await state.set_state(CreateWatch.day_pick)
    response_text = f"Шаблон додано (id={tid}). Обери день закінчення вікна:"
    if not media_ready:
        response_text += (
            "\n\n⚠️ Media не збережене у monitoring, бо TEMPLATE_MEDIA_VAULT_CHAT_ID не налаштований "
            "або vault copy не вдався."
        )
    await m.answer(response_text, reply_markup=_watch_day_kb())


@router.callback_query(CreateWatch.day_pick, F.data.startswith("watch_day:"))
async def step_day_pick(cb: CallbackQuery, state: FSMContext):
    selected_day_raw = cb.data.split("watch_day:", 1)[1].strip()
    selected_day = _parse_iso_date(selected_day_raw)
    now = msk_now()
    if not selected_day:
        await cb.answer("Невірна дата", show_alert=True)
        return
    if selected_day < now.date():
        await cb.answer("Оберіть сьогодні або майбутню дату", show_alert=True)
        return

    await state.update_data(selected_day=selected_day.isoformat())
    await state.set_state(CreateWatch.time_window)
    await cb.message.edit_text(
        f"Обрано день: {selected_day.strftime('%d.%m.%Y')}\n"
        "Обери час кнопкою або введи вручну у форматі HH:MM.",
        reply_markup=_watch_time_kb(),
    )
    await cb.answer()


def _parse_time_parts(text: str) -> tuple[int, int, int] | None:
    m_time = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", (text or "").strip())
    if not m_time:
        return None
    h = _try_int(m_time.group(1))
    mi = _try_int(m_time.group(2))
    s = _try_int(m_time.group(3) or "0")
    if h is None or mi is None or s is None:
        return None
    if not (0 <= h <= 23 and 0 <= mi <= 59 and 0 <= s <= 59):
        return None
    return h, mi, s


async def _process_time_window_value(
    *,
    state: FSMContext,
    time_text: str,
    respond: Callable[..., Any],
) -> bool:
    parsed = _parse_time_parts(time_text)
    if not parsed:
        await respond(
            "Введи час у форматі HH:MM (або обери кнопку нижче).",
            reply_markup=_watch_time_kb(),
        )
        return False
    h, mi, _ = parsed

    now = msk_now()
    data = await state.get_data()
    selected_day = _parse_iso_date(str(data.get("selected_day") or ""))
    if not selected_day:
        selected_day = now.date()

    tw_end_dt = now.replace(
        year=selected_day.year,
        month=selected_day.month,
        day=selected_day.day,
        hour=h,
        minute=mi,
        second=0,
        microsecond=0,
    )

    if tw_end_dt <= now:
        await respond(
            f"Для дати {selected_day.strftime('%d.%m.%Y')} час має бути пізніше за поточний момент. "
            "Вкажи інший час.",
            reply_markup=_watch_time_kb(),
        )
        return False

    delta = tw_end_dt - now
    mins = int(delta.total_seconds() // 60)
    if mins <= 0:
        await respond(
            "Вікно має бути хоча б кілька хвилин. Вкажи інший час.",
            reply_markup=_watch_time_kb(),
        )
        return False

    tw_start = now.strftime("%Y-%m-%d %H:%M:%S")
    tw_end = tw_end_dt.strftime("%Y-%m-%d %H:%M:%S")

    targets: List[str] = data.get("targets") or []
    tid = data.get("template_id")
    tpl_title = data.get("template_title")
    is_reply_template = bool(post_watch_db.is_template_reply(int(tid))) if tid else False

    await state.update_data(
        selected_day=selected_day.isoformat(),
        selected_time=f"{h:02d}:{mi:02d}",
        time_window_start=tw_start,
        time_window_end=tw_end,
        mins=mins,
    )

    cids: List[int] = []
    for t in targets:
        cid_val = resolve_cid_by_target(t)
        if cid_val:
            cids.append(cid_val)
    links_map = get_links_by_channel_ids(cids)
    # доповнюємо з channel_links/username/invite_map, якщо нема в links_map
    if cids:
        try:
            extra_links = cho.get_links_by_channel_ids(cids)
            for cid_val, link_val in extra_links.items():
                links_map.setdefault(cid_val, link_val)
            missing = [cid for cid in cids if cid not in links_map]
            if missing:
                db_tmp = AdminSession()
                try:
                    # ChannelLink fallback
                    rows = (
                        db_tmp.query(adm_models.ChannelLink.channel_id, adm_models.ChannelLink.link_url_norm)
                        .filter(adm_models.ChannelLink.channel_id.in_(missing))
                        .all()
                    )
                    for cid_val, link_val in rows:
                        if link_val:
                            links_map.setdefault(int(cid_val), str(link_val))
                    missing2 = [cid for cid in missing if cid not in links_map]
                    if missing2:
                        # останній raw_url із links як крайнє джерело
                        rows_links = (
                            db_tmp.query(adm_models.Link.channel_id, adm_models.Link.raw_url)
                            .filter(adm_models.Link.channel_id.in_(missing2), adm_models.Link.raw_url != None)  # noqa: E711
                            .order_by(adm_models.Link.id.desc())
                            .all()
                        )
                        for cid_val, raw_url in rows_links:
                            if raw_url:
                                try:
                                    href = sanitize_link(raw_url) or raw_url
                                except Exception:
                                    href = raw_url
                                links_map.setdefault(int(cid_val), str(href))
                finally:
                    db_tmp.close()
        except Exception:
            log.warning("watch_net: failed to enrich links_map from channel_links", exc_info=True)
    titles_map = get_titles_by_channel_ids(cids)
    targets_txt = "\n".join(
        f"• <a href=\"{links_map.get(resolve_cid_by_target(t), t)}\">"
        f"{titles_map.get(resolve_cid_by_target(t), t)}</a>"
        if resolve_cid_by_target(t) else f"• {t}"
        for t in targets
    )
    txt = (
        f"Підтверди створення watch:\n\n"
        f"targets:\n{targets_txt}\n\n"
        f"template_id: {tid or '—'}\n"
        f"Назва поста: {tpl_title or '—'}\n"
        f"Ответка: {'Так' if is_reply_template else 'Ні'}\n"
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
    await respond(
        txt + "\nОбери проєкт:",
        reply_markup=kb,
        parse_mode="HTML",
    )
    return True


@router.message(CreateWatch.time_window)
async def step_time_window(m: Message, state: FSMContext):
    await _process_time_window_value(
        state=state,
        time_text=(m.text or "").strip(),
        respond=m.answer,
    )


@router.callback_query(CreateWatch.time_window, F.data.startswith("watch_time:"))
async def step_time_window_button_pick(cb: CallbackQuery, state: FSMContext):
    time_text = cb.data.split("watch_time:", 1)[1].strip()
    is_success = await _process_time_window_value(
        state=state,
        time_text=time_text,
        respond=cb.message.answer,
    )
    if is_success:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await cb.answer()


@router.callback_query(CreateWatch.project_pick, F.data.startswith("watch_proj:"))
async def pick_project(cb: CallbackQuery, state: FSMContext):
    proj = cb.data.split("watch_proj:", 1)[1]
    await state.update_data(project=proj)
    data = await state.get_data()
    mins = int(data["mins"])
    tid = data.get("template_id")
    targets: List[str] = data.get("targets") or []
    admin_id = data.get("admin_id")
    net_id = data.get("network_id")
    tw_end = data.get("time_window_end")
    is_reply_template = bool(post_watch_db.is_template_reply(int(tid))) if tid else False
    proj_txt = proj
    cids: List[int] = []
    for t in targets:
        cid_val = resolve_cid_by_target(t)
        if cid_val:
            cids.append(cid_val)
    links_map = get_links_by_channel_ids(cids)
    titles_map = get_titles_by_channel_ids(cids)
    targets_txt = "\n".join(
        f"• <a href=\"{links_map.get(resolve_cid_by_target(t), t)}\">"
        f"{titles_map.get(resolve_cid_by_target(t), t)}</a>"
        if resolve_cid_by_target(t) else f"• {t}"
        for t in targets
    )
    txt = (
        f"Підтверди створення watch:\n\n"
        f"targets:\n{targets_txt}\n\n"
        f"template_id: {tid or '—'}\n"
        f"Ответка: {'Так' if is_reply_template else 'Ні'}\n"
        f"вікно: {mins} хв\n"
        f"до: {tw_end}\n"
        f"проєкт: {proj_txt}\n"
        + (f"адмін: {admin_id}\n" if admin_id else "")
        + (f"сітка: {net_id}\n" if net_id else "")
    )
    await state.set_state(CreateWatch.confirm)
    await cb.message.edit_text(
        txt,
        reply_markup=yes_no_kb("watch:confirm_yes", "watch:confirm_no"),
        parse_mode="HTML"
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
    admin_id = data.get("admin_id")
    net_id = data.get("network_id")
    log.info(
        "watch_net: confirm_yes admin=%s net=%s tid=%s mins=%s targets=%s project=%s",
        admin_id, net_id, tid, mins, targets, project,
    )

    if not tid:
        log.warning("watch_net: confirm_yes without template_id, state=%s", await state.get_data())

    created: List[str] = []
    failed: List[str] = []
    failed_reasons: List[tuple[str, str]] = []

    # Підготуємо нормалізовані посилання для control chat і fallback
    cids: List[int] = []
    for t in targets:
        cid = resolve_cid_by_target(t)
        if cid:
            cids.append(cid)
    links_map = get_links_by_channel_ids(cids)
    titles_map = get_titles_by_channel_ids(cids)
    targets_links: List[str] = []
    for t in targets:
        cid = resolve_cid_by_target(t)
        norm = normalize_target_link(t)
        if norm:
            targets_links.append(norm)
    targets_links = _unique_preserve(targets_links)
    log.info(
        "watch_net: normalized targets links=%s raw=%s links_map=%s",
        targets_links, targets, links_map,
    )

    # Потік через CONTROL_CHAT більше не використовується — створюємо вотчі одразу локально.
    control_id = None
    sent_ok = False
    if control_id and tid:
        control_targets = targets_links if targets_links else targets
        log.info("watch_net: sending to control chat=%s targets=%s", control_id, control_targets)
        sent_ok = await _send_watch_from_links_batch_bot(cb.bot, control_targets, mins, int(tid), project)
        if sent_ok:
            created.extend(control_targets)
        else:
            failed.extend(control_targets)

    if (not control_id) or (control_id and not sent_ok):
        tpl_html = None
        tpl_links_json = None
        tpl_plain = None
        tpl_is_reply = False
        if tid:
            tpl_meta = _load_template(int(tid))
            if not tpl_meta:
                log.warning("watch_net: template not found id=%s", tid)
                await cb.message.edit_text(f"Не знайшов шаблон #{tid}. Спробуй надіслати інший шаблон або ID.", reply_markup=main_menu_kb())
                await state.clear()
                return
            tpl_html = tpl_meta.get("html")
            tpl_links_json = tpl_meta.get("links_json")
            tpl_is_reply = bool(tpl_meta.get("is_reply"))
        if not tpl_html:
            log.warning("watch_net: template id=%s has empty html", tid)
        else:
            try:
                # Використовуємо той самий нормалізатор, що й у слухачі
                    from app.plugins.posts_watch_listener import _normalize_html_full, _strip_tags_to_text  # type: ignore
                    tpl_html_norm = _normalize_html_full(tpl_html)
                    tpl_plain = _strip_tags_to_text(tpl_html_norm)
                    tpl_html = tpl_html_norm
                    tpl_plain_len = len(tpl_plain or "")
                    log.debug(
                        "watch_net: tpl normalized tid=%s len_html=%s len_plain=%s sample_plain=%r",
                        tid,
                        len(tpl_html or ""),
                        tpl_plain_len,
                        (tpl_plain or "")[:120],
                    )
            except Exception:
                log.exception("watch_net: tpl normalization failed (tid=%s)", tid)
                tpl_plain_len = len(tpl_html or "")

        # Заголовок групи (перші два слова без провідних символів/емодзі)
        group_title_source = tpl_plain or tpl_html or (tpl_meta or {}).get("title") or ""
        group_title = _first_line_title(group_title_source)
        log.info(
            "watch_net: group title resolved -> '%s' (source len=%s, tid=%s)",
            group_title,
            len(group_title_source or ""),
            tid,
        )
        if not group_title:
            log.warning(
                "watch_net: empty group title, source_sample=%r", (group_title_source or "")[:120]
            )

        group_id = None
        try:
            group_id = watch_posts_db.create_watch_group(
                project=project,
                title=group_title,
                created_by=cb.from_user.id if cb.from_user else None,
                created_via="bot_fallback",
                admin_id=admin_id,
                network_id=net_id,
            )
            log.info("watch_net: created group id=%s title='%s'", group_id, group_title)
        except Exception:
            log.warning("create_watch_group (fallback) failed", exc_info=True)

        for t in targets:
            cid = resolve_cid_by_target(t)
            if not cid or not tid:
                failed.append(t)
                failed_reasons.append((t, "Не вдалося визначити channel_id або відсутній шаблон"))
                continue
            if not tpl_html:
                failed.append(t)
                failed_reasons.append((t, "Порожній HTML шаблону"))
                continue
            watch_title: Optional[str] = None  # двослівний заголовок далі
            if tpl_plain:
                try:
                    templates = post_watch_db.list_templates_full(limit=200)
                    best_ratio = 0.0
                    best_title = None
                    for tpl_id, tpl_text, tpl_mode, tpl_threshold, tpl_created_at, tpl_title, tpl_links, _tpl_photo_id in templates:
                        if not tpl_title:
                            continue
                        ratio = SequenceMatcher(None, tpl_plain, tpl_text or "").ratio()
                        if ratio >= 0.8 and ratio > best_ratio:
                            best_ratio = ratio
                            best_title = tpl_title
                    if best_title:
                        watch_title = best_title
                except Exception:
                    log.warning("watch_net: similarity match for title failed", exc_info=True)

            # якщо нічого не підійшло — беремо перші два слова з тексту шаблону
            base_title_source = watch_title or tpl_plain or tpl_html or titles_map.get(int(cid)) or ""
            watch_title = _first_line_title(base_title_source)
            log.debug(
                "watch_net: watch title resolved -> '%s' (cid=%s, tid=%s, group_id=%s)",
                watch_title,
                cid,
                tid,
                group_id,
            )
            if not watch_title:
                if group_title:
                    watch_title = group_title
                    log.info(
                        "watch_net: watch title empty, fallback to group title -> '%s' (cid=%s, tid=%s, group_id=%s)",
                        watch_title,
                        cid,
                        tid,
                        group_id,
                    )
                else:
                    watch_title = ""
                log.warning(
                    "watch_net: empty watch title for cid=%s tid=%s group_id=%s source_sample=%r",
                    cid,
                    tid,
                    group_id,
                    (base_title_source or "")[:120],
                )
            try:
                wid = watch_posts_db.create_watch(
                    channel_id=int(cid),
                    template_id=int(tid),
                    expected_text_hash=tpl_html,
                    expected_text_norm_len=tpl_plain_len if tpl_html else None,
                    expected_links_json=tpl_links_json,
                    expected_media_fingerprint=None,
                    time_window_start=data.get("time_window_start"),
                    time_window_end=data.get("time_window_end"),
                    source_url=links_map.get(int(cid)),
                    created_by=None,
                    project=project,
                    admin_id=admin_id,
                    network_id=net_id,
                    group_id=group_id,
                    title=watch_title,
                    is_reply=tpl_is_reply,
                )
                log.info(
                    "watch_net: created watch wid=%s cid=%s admin=%s net=%s project=%s links=%s",
                    wid,
                    cid,
                    admin_id,
                    net_id,
                    project,
                    links_map.get(int(cid)),
                )
                try:
                    watch_events_db.insert_watch_event(
                        wid,
                        "created",
                        json.dumps({"via": "bot_fallback"}),
                    )
                except Exception:
                    pass
                if project:
                    try:
                        db = SessionLocal()
                        try:
                            sheet = spo.get_active_sheet(db, project)
                        finally:
                            db.close()
                        if sheet and getattr(sheet, "active_spreadsheet_id", None):
                            log.info(
                                "watch %s bound to project %s sheet=%s",
                                wid,
                                project,
                                getattr(sheet, "active_spreadsheet_id", None),
                            )
                    except Exception:
                        log.exception("bind watch to project failed")
                created.append(
                    (
                        int(cid),
                        links_map.get(int(cid)) or t,
                        titles_map.get(int(cid)) or t,
                        wid,
                    )
                )
            except TypeError as e:
                failed.append(t)
                failed_reasons.append((t, f"TypeError: {e}"))
            except Exception as e:
                failed.append(t)
                failed_reasons.append((t, f"{e.__class__.__name__}: {e}"))

    await state.clear()

    msg_parts: List[str] = []
    if created:
        lines = []
        for cid, link, title, wid in created:
            try:
                safe_link = (link or "").strip().replace('"', "")
            except Exception:
                safe_link = link or ""
            try:
                safe_title = html.escape((title or "").strip())
            except Exception:
                safe_title = (title or "")
            safe_link_esc = html.escape(safe_link)
            lines.append(f'• <a href="{safe_link_esc}">{safe_title}</a> (fallback wid={wid})')
        msg_parts.append("✅ Watch(и) створено:\n" + "\n".join(lines))
    if failed:
        lines = []
        reasons_map = {t: r for t, r in failed_reasons}
        for item in failed:
            cid = resolve_cid_by_target(item)
            reason = reasons_map.get(item, "")
            safe_link = item
            safe_title = item
            if cid:
                safe_link = links_map.get(cid, item)
                safe_title = titles_map.get(cid, item)
            try:
                safe_link = (safe_link or "").replace('"', "").strip()
            except Exception:
                pass
            try:
                safe_title = html.escape((safe_title or "").strip())
            except Exception:
                safe_title = (safe_title or "")
            safe_link_esc = html.escape(safe_link or "")
            text = f'• <a href="{safe_link_esc}">{safe_title}</a>'
            if reason:
                text = f"{text} — {reason}"
            lines.append(text)
        msg_parts.append("⚠️ Не вдалося створити watch для:\n" + "\n".join(lines))
    if not msg_parts:
        msg_parts.append("❌ Не вдалося створити watch.")

    await cb.message.edit_text("\n\n".join(msg_parts), reply_markup=main_menu_kb(), parse_mode="HTML")
