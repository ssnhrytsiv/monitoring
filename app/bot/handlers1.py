from typing import Optional, List, Any, Callable, Dict, Tuple
import os
import re
import logging
from datetime import timedelta, datetime
import json

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from app.bot.states import CreateWatch
from app.bot.keyboards import main_menu_kb, back_to_menu_kb, yes_no_kb
from app.services.posts_watch_result_db import create_watch, raw_connection, insert_watch_event
from app.services.time_utils import msk_now

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
                piece = plain_text[off:off+ln].strip()
                if piece:
                    links.append(piece)
        except Exception:
            continue
    for m in _LINK_RE.finditer(plain_text or ""):
        u = m.group(1)
        if u:
            links.append(u)
    return _unique_preserve(links)

def _parse_links_unique(links_json: Optional[str]) -> List[str]:
    if not links_json:
        return []
    try:
        arr = json.loads(links_json)
        if not isinstance(arr, list):
            return []
        out: List[str] = []
        seen = set()
        for x in arr:
            u = str(x).strip()
            if not u or u in seen:
                continue
            seen.add(u)
            out.append(u)
        return out
    except Exception:
        return []

def _fmt_tw_end(s: Optional[str]) -> str:
    if not s:
        return "—"
    try:
        dt = datetime.strptime(str(s), "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d.%m %H:%M:%S")
    except Exception:
        return str(s)

def _short_title(title: Optional[Any], tid: Optional[int]) -> str:
    if title is None:
        return f"tpl#{tid}" if tid else "—"
    t = str(title).strip()
    if not t:
        return f"tpl#{tid}" if tid else "—"
    return t.split()[0]

def _load_templates_map() -> Dict[int, Dict[str, Any]]:
    try:
        from app.services import post_watch_db as pdb
        fn = getattr(pdb, "list_templates_full", None)
        if not fn:
            return {}
        rows = fn()
        mp: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            try:
                tid = int(r[0])
                title = r[4] if len(r) > 4 else None
                links_json = r[5] if len(r) > 5 else None
                mp[tid] = {"title": title, "links_json": links_json}
            except Exception:
                continue
        return mp
    except Exception:
        return {}

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
        log.warning("create_template no text found")
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
        log.warning("create_template add_template not found")
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
                except Exception as e:
                    log.exception(f"create_template add_template positional failed: {e}")
            except Exception as e:
                log.exception(f"create_template add_template failed: {e}")
        except Exception as e:
            log.exception(f"create_template add_template failed: {e}")
    except Exception as e:
        log.exception(f"create_template add_template failed: {e}")

    return None

async def _send_watch_from_links_batch_bot(bot, targets: List[str], mins: int, template_id: int) -> bool:
    try:
        control_id = _control_chat_id()
        log.info(f"send_batch_bot control_id={control_id} template_id={template_id} mins={mins} targets_count={len(targets)}")
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

@router.message(CreateWatch.channel_input)
async def step_channel_input(m: Message, state: FSMContext):
    text = (m.text or "").strip()
    targets = _extract_targets(text)
    if not targets:
        await m.answer("Не знайшов валідних t.me лінків або target'ів. Спробуй ще раз.")
        return
    await state.update_data(targets=targets)
    await state.set_state(CreateWatch.template_pick)
    await m.answer(
        "Надішли ID шаблону числом або перешли/відповідай повідомленням з шаблоном (я додам його в базу і візьму новий ID).",
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
                "Вкажи тривалість вікна у хвилинах (наприклад 120).",
                reply_markup=back_to_menu_kb()
            )
            return

    src = m.reply_to_message if has_reply else m
    tid = await _create_template_from_source(src)

    if not tid:
        await m.answer("Не зміг створити шаблон з цього повідомлення. Надішли числовий template_id або інший пост-шаблон.")
        return

    await state.update_data(template_id=tid)
    await state.set_state(CreateWatch.time_window)
    await m.answer(
        f"Шаблон додано в базу (id={tid}). Вкажи тривалість вікна у хвилинах (наприклад 120).",
        reply_markup=back_to_menu_kb()
    )

@router.message(CreateWatch.time_window)
async def step_time_window(m: Message, state: FSMContext):
    mins = _try_int(m.text or "")
    if not mins or mins <= 0:
        await m.answer("Введи число хвилин, наприклад 120.")
        return
    data = await state.get_data()
    targets: List[str] = data.get("targets") or []
    tid = data.get("template_id")
    now = msk_now()
    tw_start = now.strftime("%Y-%m-%d %H:%M:%S")
    tw_end = (now + timedelta(minutes=mins)).strftime("%Y-%m-%d %H:%M:%S")
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
    await m.answer(txt, reply_markup=yes_no_kb("watch:confirm_yes", "watch:confirm_no"))

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
        for t in targets:
            cid = _try_int(t)
            if not cid or not tid:
                failed.append(t)
                continue
            try:
                wid = create_watch(
                    channel_id=int(cid),
                    template_id=int(tid),
                    expected_text_hash=None,
                    expected_text_norm_len=None,
                    expected_links_json=None,
                    expected_media_fingerprint=None,
                    time_window_start=data.get("time_window_start"),
                    time_window_end=data.get("time_window_end"),
                    source_url=None,
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

    await cb.message.edit_text("\n\n".join(msg_parts), reply_markup=main_menu_kb())

@router.callback_query(F.data.startswith("watch:links:"))
async def watch_links(cb: CallbackQuery):
    wid = None
    try:
        wid = int(cb.data.split(":")[-1])
    except Exception:
        wid = None
    if not wid:
        await cb.answer("bad id", show_alert=True)
        return

    templates_map = _load_templates_map()

    try:
        conn = raw_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT template_id, expected_links_json FROM watch_posts WHERE id=?",
            (wid,),
        )
        row = cur.fetchone()
        tid = int(row[0]) if row and row[0] is not None else None
        w_links_json = row[1] if row else None
    except Exception:
        tid = None
        w_links_json = None

    t_links_json = None
    if tid and tid in templates_map:
        t_links_json = templates_map[tid].get("links_json")

    links = _parse_links_unique(w_links_json) or _parse_links_unique(t_links_json)
    if not links:
        await cb.answer("Посилань немає", show_alert=True)
        return

    txt = "\n".join(links)
    if len(txt) > 3500:
        txt = txt[:3500] + "…"
    await cb.answer(txt, show_alert=True)

@router.callback_query(F.data.startswith("watch:cancel:"))
async def watch_cancel(cb: CallbackQuery):
    leader_wid = None
    try:
        parts = cb.data.split(":")
        if len(parts) >= 3:
            leader_wid = int(parts[2])
    except Exception:
        leader_wid = None
    if not leader_wid:
        await cb.answer("bad id", show_alert=True)
        return

    try:
        conn = raw_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT template_id, time_window_end, created_by FROM watch_posts WHERE id=?",
            (leader_wid,),
        )
        row = cur.fetchone()
        if not row:
            await cb.answer("Не знайдено", show_alert=True)
            return
        tid, tw_end, cby = row
        tid_i = int(tid) if tid is not None else None
        tw_end_s = str(tw_end) if tw_end is not None else None
    except Exception:
        await cb.answer("Не зміг прочитати групу", show_alert=True)
        return

    cancelled_ok = False
    try:
        now_s = msk_now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            """
            UPDATE watch_posts
            SET status='cancelled', updated_at=?
            WHERE template_id IS ?
              AND time_window_end IS ?
              AND created_by IS ?
              AND status IN ('pending','matched')
            """,
            (now_s, tid_i, tw_end_s, cby),
        )
        conn.commit()
        cancelled_ok = True
    except Exception:
        cancelled_ok = False

    if not cancelled_ok:
        await cb.answer("Не зміг скасувати", show_alert=True)
        return

    try:
        insert_watch_event(leader_wid, "cancelled", {"watch_id": leader_wid})
    except Exception:
        pass

    await cb.answer("Скасовано", show_alert=False)
    await menu_list_active(cb)

@router.callback_query(F.data == "menu:list_active")
async def menu_list_active(cb: CallbackQuery):
    templates_map = _load_templates_map()

    try:
        conn = raw_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, template_id, status, time_window_end, created_by, expected_links_json
            FROM watch_posts
            WHERE (created_by=? OR created_by IS NULL)
              AND status IN ('pending','matched')
            ORDER BY id DESC
            LIMIT 200
            """,
            (cb.from_user.id,),
        )
        rows = cur.fetchall()
    except Exception as e:
        log.exception(f"menu:list_active query failed: {e}")
        rows = []

    if not rows:
        try:
            await cb.message.edit_text("Активних watch немає.", reply_markup=main_menu_kb())
        except TelegramBadRequest:
            await cb.message.answer("Активних watch немає.", reply_markup=main_menu_kb())
        return

    groups: Dict[Tuple[Optional[int], Optional[str], Optional[int], str], List[Tuple[Any, Optional[str]]]] = {}
    for wid, tid, st, tw_end, cby, w_links_json in rows:
        tid_i = int(tid) if tid is not None else None
        tw_end_s = str(tw_end) if tw_end is not None else None
        key = (tid_i, tw_end_s, cby, str(st))
        groups.setdefault(key, []).append((wid, w_links_json))

    ordered_keys = sorted(groups.keys(), key=lambda k: max(int(x[0]) for x in groups[k]), reverse=True)

    lines: List[str] = []
    kb = InlineKeyboardBuilder()

    for key in ordered_keys[:50]:
        tid_i, tw_end_s, cby, st = key
        items = groups[key]
        leader_wid = max(int(x[0]) for x in items)
        w_links_json = None
        for w, lj in items:
            if lj:
                w_links_json = lj
                break

        tpl_title = None
        tpl_links_json = None
        if tid_i and tid_i in templates_map:
            tpl_title = templates_map[tid_i].get("title")
            tpl_links_json = templates_map[tid_i].get("links_json")

        links = _parse_links_unique(w_links_json) or _parse_links_unique(tpl_links_json)
        links_n = len(links)
        title_short = _short_title(tpl_title, tid_i)
        tw_txt = _fmt_tw_end(tw_end_s)
        chans_n = len(items)

        lines.append(f"{leader_wid} | {title_short} | 🔗{links_n} | до {tw_txt} | chans {chans_n}")
        kb.button(text=f"🔗 {links_n}", callback_data=f"watch:links:{leader_wid}")
        kb.button(text="❌ Cancel", callback_data=f"watch:cancel:{leader_wid}")

    kb.adjust(2)

    text = "№ | Template | Links | Window | Channels\n\n" + "\n".join(lines)

    try:
        await cb.message.edit_text(text, reply_markup=kb.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=kb.as_markup())
