from typing import Optional, List, Any, Callable
import os
import re
import logging
import json
import math

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from app.bot.states import CreateWatch
from app.DAL import SessionLocal
from app.DAL import sheet_projects_operations as spo
from app.DAL import post_templates_operations as post_watch_db
from app.DAL import watch_posts_operations as watch_posts_db
from app.DAL import watch_events_operations as watch_events_db
from app.sheet_bot.services import gsheets_writer as gsw
from app.sheet_bot.services import gsheets_buffer as gsb
from app.bot.keyboards import main_menu_kb, back_to_menu_kb, yes_no_kb
from app.services.time_utils import msk_now
from app.bot.services.channels_repo import resolve_cid_by_target, normalize_target_link, get_links_by_channel_ids
from app.utils.link_parser import sanitize_link
from app.admin_bot.services import admins as svc_admins
from app.admin_bot.services import networks as svc_networks
from app.admin_bot.services.networks import channel_hyperlink
from app.admin_bot.db.session import SessionLocal as AdminSession
from app.admin_bot.db import models as adm_models

router = Router()
log = logging.getLogger("bot_create_watch")

_LINK_RE = re.compile(r'(?i)\b((?:https?://|tg://|t\.me/)[^\s<>"\'\]\)]+)')
_ADMINS_PER_ROW = 2
_ADMINS_PER_PAGE = 36


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
        _, tpl_html, tpl_mode, tpl_thr, created_at, tpl_title, tpl_links_json = tpl
        return {
            "html": tpl_html,
            "links_json": tpl_links_json,
            "mode": tpl_mode,
            "threshold": tpl_thr,
            "title": tpl_title,
            "created_at": created_at,
        }
    except Exception:
        log.warning("watch_net: failed to load template id=%s", template_id, exc_info=True)
        return None


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
        log.info("create_template: empty text_for_template (message_id=%s)", getattr(src, "message_id", None))
        return None

    try:
        parsed_links = _collect_links_from_aiogram(src, plain_text)
        links_json = json.dumps(parsed_links, ensure_ascii=False) if parsed_links else None
    except Exception:
        log.warning("create_template: failed to parse links (message_id=%s)", getattr(src, "message_id", None), exc_info=True)
        links_json = None

    title = _first_line_title(plain_text or text_for_template)

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
        res = fn(text=text_for_template, title=title, mode="exact", links=links_json)
        tid = _parse_template_id(res)
        if tid:
            log.info("create_template: created template id=%s title=%s", tid, title)
            return tid
    except TypeError:
        try:
            res = fn(text=text_for_template, title=title, links=links_json)
            tid = _parse_template_id(res)
            if tid:
                log.info("create_template: created template id=%s title=%s (fallback no mode)", tid, title)
                return tid
        except TypeError:
            try:
                res = fn(text=text_for_template, title=title)
                tid = _parse_template_id(res)
                if tid:
                    log.info("create_template: created template id=%s title=%s (fallback no links)", tid, title)
                    return tid
            except TypeError:
                try:
                    res = fn(text_for_template)
                    tid = _parse_template_id(res)
                    if tid:
                        log.info("create_template: created template id=%s (legacy signature)", tid)
                        return tid
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
    admin_id = data.get("admin_id")
    net_id = data.get("network_id")
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
        + (f"адмін: {admin_id}\n" if admin_id else "")
        + (f"сітка: {net_id}\n" if net_id else "")
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

    # Підготуємо нормалізовані посилання для control chat і fallback
    cids: List[int] = []
    for t in targets:
        cid = resolve_cid_by_target(t)
        if cid:
            cids.append(cid)
    links_map = get_links_by_channel_ids(cids)
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

    control_id = _control_chat_id()
    # для сіткового флоу вимикаємо control chat, щоб одразу ставити локально
    if net_id:
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
        if tid:
            tpl_meta = _load_template(int(tid))
            if not tpl_meta:
                log.warning("watch_net: template not found id=%s", tid)
                await cb.message.edit_text(f"Не знайшов шаблон #{tid}. Спробуй надіслати інший шаблон або ID.", reply_markup=main_menu_kb())
                await state.clear()
                return
            tpl_html = tpl_meta.get("html")
            tpl_links_json = tpl_meta.get("links_json")
            if not tpl_html:
                log.warning("watch_net: template id=%s has empty html", tid)

        group_id = None
        try:
            group_id = watch_posts_db.create_watch_group(
                project=project,
                title=None,
                created_by=cb.from_user.id if cb.from_user else None,
                created_via="bot_fallback",
                admin_id=admin_id,
                network_id=net_id,
            )
        except Exception:
            log.warning("create_watch_group (fallback) failed", exc_info=True)

        for t in targets:
            cid = resolve_cid_by_target(t)
            if not cid or not tid:
                failed.append(f"{t} (cid not found or no template)")
                continue
            try:
                wid = watch_posts_db.create_watch(
                    channel_id=int(cid),
                    template_id=int(tid),
                    expected_text_hash=tpl_html,
                    expected_text_norm_len=len(tpl_html or "") if tpl_html else None,
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
                created.append(f"{t} (fallback wid={wid})")
            except TypeError:
                failed.append(t)
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
