
from typing import Optional, List, Any, Callable
import os
import re
import logging
from datetime import timedelta, datetime
import json

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

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
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d.%m %H:%M:%S")
    except Exception:
        return s

def _short_title(title: Optional[str], tid: Optional[int]) -> str:
    t = (title or "").strip()
    if not t:
        return f"tpl#{tid}" if tid else "—"
    return t.split()[0]

async def _create_template_from_source(src: Message) -> Optional[int]:
    html_text = (
        getattr(src, "html_text", None)
        or getattr(src, "text_html", None)
        or getattr(src, "html_caption", None)
        or getattr(src, "caption_html", None)
    )
    plain_text = (getattr(src, "text", None) or getattr(src, "caption", None) or "").strip()
    text_for_template = (html_text or plain_text or "").strip()

    proposed_texts: List[str] = []
    if text_for_template:
        proposed_texts.append(text_for_template)

    log.info(f"create_template proposed_texts_lens={[len(t) for t in proposed_texts]}")

    text = text_for_template

    log.info(f"create_template picked_text_len={len(text)}")

    if not text:
        log.warning("create_template no text found")
        return None

    try:
        parsed_links = _collect_links_from_aiogram(src, plain_text)
        links_json = json.dumps(parsed_links, ensure_ascii=False) if parsed_links else None
    except Exception:
        parsed_links = []
        links_json = None

    log.info(f"create_template parsed_links={parsed_links!r}")

    title = _first_line_title(plain_text or text)
    log.info(f"create_template title={title!r}")

    try:
        from app.services import post_watch_db as pdb
        log.info("create_template imported post_watch_db")
    except Exception as e:
        log.exception(f"create_template import failed: {e}")
        return None

    log.info(f"create_template available_fns_sample={[x for x in dir(pdb) if 'template' in x.lower()][:30]}")

    fn: Optional[Callable[..., Any]] = getattr(pdb, "add_template", None)
    if not fn:
        log.warning("create_template add_template not found")
        return None

    try:
        log.info("create_template try fn=add_template kwargs text+title+mode+links")
        res = fn(text=text, title=title, mode="exact", links=links_json)
        tid = _parse_template_id(res)
        log.info(f"create_template fn=add_template res={res!r} tid={tid}")
        if tid:
            return tid
    except TypeError as e1:
        log.warning(f"create_template add_template TypeError={e1}, retry with text+title+links")
        try:
            res = fn(text=text, title=title, links=links_json)
            tid = _parse_template_id(res)
            log.info(f"create_template fn=add_template res={res!r} tid={tid}")
            if tid:
                return tid
        except TypeError as e2:
            log.warning(f"create_template add_template TypeError={e2}, retry with text+title")
            try:
                res = fn(text=text, title=title)
                tid = _parse_template_id(res)
                log.info(f"create_template fn=add_template res={res!r} tid={tid}")
                if tid:
                    return tid
            except TypeError as e3:
                log.warning(f"create_template add_template TypeError={e3}, retry positional")
                try:
                    res = fn(text)
                    tid = _parse_template_id(res)
                    log.info(f"create_template fn=add_template positional res={res!r} tid={tid}")
                    if tid:
                        return tid
                except Exception as e4:
                    log.exception(f"create_template add_template positional failed: {e4}")
            except Exception as e3x:
                log.exception(f"create_template add_template failed: {e3x}")
        except Exception as e2x:
            log.exception(f"create_template add_template failed: {e2x}")
    except Exception as e1x:
        log.exception(f"create_template add_template failed: {e1x}")

    log.warning("create_template add_template did not return id")
    return None

async def _send_watch_from_links_batch_bot(bot, targets: List[str], mins: int, template_id: int, created_by: int, project: Optional[str]) -> bool:
    try:
        control_id = _control_chat_id()
        log.info(f"send_batch_bot control_id={control_id} template_id={template_id} mins={mins} targets_count={len(targets)} created_by={created_by}")
        if not control_id:
            log.warning("send_batch_bot no control_id")
            return False
        header = f"/watch_from_links {int(template_id)} --window-min {int(mins)} --created-by {int(created_by)}"
        if project:
            header += f" --project {project}"
        body = "\n".join(targets)
        cmd = header + "\n" + body if body else header
        log.info(f"send_batch_bot cmd={cmd!r}")
        msg = await bot.send_message(control_id, cmd)
        log.info(f"send_batch_bot sent_ok msg_id={getattr(msg, 'message_id', None)}")
        return True
    except Exception as e:
        log.exception(f"send_batch_bot failed: {e}")
        return False

@router.message(F.text == "/start")
async def start_cmd(m: Message, state: FSMContext):
    log.info(f"/start from_user={m.from_user.id if m.from_user else None}")
    await state.clear()
    await m.answer("Меню:", reply_markup=main_menu_kb())

@router.callback_query(F.data == "menu:home")
async def menu_home(cb: CallbackQuery, state: FSMContext):
    log.info(f"menu:home from_user={cb.from_user.id if cb.from_user else None}")
    await state.clear()
    await cb.message.edit_text("Меню:", reply_markup=main_menu_kb())

@router.callback_query(F.data == "menu:add_watch")
async def menu_add_watch(cb: CallbackQuery, state: FSMContext):
    log.info(f"menu:add_watch from_user={cb.from_user.id if cb.from_user else None}")
    await state.set_state(CreateWatch.channel_input)
    await cb.message.edit_text(
        "Введи t.me лінк(и) / інвайти / @username каналів, які треба моніторити:",
        reply_markup=back_to_menu_kb()
    )

@router.message(CreateWatch.channel_input)
async def step_channel_input(m: Message, state: FSMContext):
    text = (m.text or "").strip()
    targets = _extract_targets(text)
    log.info(f"channel_input text={text!r} targets={targets!r}")
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
    log.info(
        f"template_pick direct_text={direct_text!r} has_reply={has_reply} is_forward={is_forward} "
        f"msg_id={m.message_id} from_user={m.from_user.id if m.from_user else None}"
    )

    if (not has_reply) and (not is_forward) and direct_text and re.fullmatch(r"\d{1,9}", direct_text):
        direct_id = _try_int(direct_text)
        log.info(f"template_pick parsed_direct_id={direct_id}")
        if direct_id:
            await state.update_data(template_id=direct_id)
            await state.set_state(CreateWatch.time_window)
            await m.answer(
                "Вкажи тривалість вікна у хвилинах (наприклад 120).",
                reply_markup=back_to_menu_kb()
            )
            return

    src = m.reply_to_message if has_reply else m
    src_text = (getattr(src, "text", None) or getattr(src, "caption", None) or "")
    log.info(f"template_pick src_selected reply={has_reply} forward={is_forward} src_text_head={src_text[:160]!r}")

    tid = await _create_template_from_source(src)
    log.info(f"template_pick created_tid={tid}")

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
    log.info(f"time_window raw_text={(m.text or '').strip()!r} mins={mins}")
    if not mins or mins <= 0:
        await m.answer("Введи число хвилин, наприклад 120.")
        return
    data = await state.get_data()
    targets: List[str] = data.get("targets") or []
    tid = data.get("template_id")
    now = msk_now()
    tw_start = now.strftime("%Y-%m-%d %H:%M:%S")
    tw_end = (now + timedelta(minutes=mins)).strftime("%Y-%m-%d %H:%M:%S")
    log.info(f"time_window tid={tid} targets={targets!r} tw_start={tw_start} tw_end={tw_end}")
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
    log.info(f"confirm_no from_user={cb.from_user.id if cb.from_user else None}")
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
    log.info(f"confirm_yes control_id={control_id} tid={tid} mins={mins} targets={targets!r}")

    sent_ok = False
    if control_id and tid:
        sent_ok = await _send_watch_from_links_batch_bot(cb.bot, targets, mins, int(tid), cb.from_user.id, data.get("project"))
        log.info(f"confirm_yes sent_ok={sent_ok}")
        if sent_ok:
            created.extend(targets)
        else:
            failed.extend(targets)
    else:
        log.info("confirm_yes skip send_batch_bot (no control_id or no tid)")

    if (not control_id) or (control_id and not sent_ok):
        log.info("confirm_yes fallback start")
        for t in targets:
            cid = _try_int(t)
            log.info(f"confirm_yes fallback target={t!r} parsed_cid={cid}")
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
                    created_by=cb.from_user.id,
                    project=data.get("project"),
                )
                log.info(f"confirm_yes fallback created wid={wid} cid={cid} tid={tid}")
                try:
                    insert_watch_event(wid, "created", {"via": "bot_fallback"})
                except Exception as e:
                    log.exception(f"confirm_yes insert_watch_event failed: {e}")
                created.append(f"{t} (fallback wid={wid})")
            except Exception as e:
                log.exception(f"confirm_yes fallback create_watch failed for {t!r}: {e}")
                failed.append(t)

    await state.clear()

    msg_parts: List[str] = []
    if created:
        if control_id and sent_ok:
            msg_parts.append("✅ Команду /watch_from_links відправлено в CONTROL_CHAT для:\n" + "\n".join(f"• {x}" for x in created))
        else:
            msg_parts.append("✅ Watch(и) створено через fallback (CONTROL_CHAT недоступний або batch не відправився):\n" + "\n".join(f"• {x}" for x in created))
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
    try:
        conn = raw_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COALESCE(w.expected_links_json, t.links)
            FROM watch_posts w
            LEFT JOIN post_templates t ON t.id = w.template_id
            WHERE w.id=?
            """,
            (wid,),
        )
        row = cur.fetchone()
        links_json = row[0] if row else None
    except Exception:
        links_json = None
    links = _parse_links_unique(links_json)
    if not links:
        await cb.answer("Посилань немає", show_alert=True)
        return
    txt = "\n".join(links)
    if len(txt) > 3500:
        txt = txt[:3500] + "…"
    await cb.answer(txt, show_alert=True)

@router.callback_query(F.data.startswith("watch:cancel:"))
async def watch_cancel(cb: CallbackQuery):
    wid = None
    try:
        wid = int(cb.data.split(":")[-1])
    except Exception:
        wid = None
    if not wid:
        await cb.answer("bad id", show_alert=True)
        return

    cancelled_ok = False
    try:
        from app.services.posts_watch_result_db import mark_cancelled
        mark_cancelled(wid)
        cancelled_ok = True
    except Exception:
        cancelled_ok = False

    if not cancelled_ok:
        try:
            now = msk_now().strftime("%Y-%m-%d %H:%M:%S")
            conn = raw_connection()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE watch_posts
                SET status='cancelled', updated_at=?
                WHERE id=? AND status IN ('pending','matched')
                """,
                (now, wid),
            )
            conn.commit()
            cancelled_ok = True
        except Exception:
            cancelled_ok = False

    if not cancelled_ok:
        await cb.answer("Не зміг скасувати", show_alert=True)
        return

    try:
        insert_watch_event(wid, "cancelled", {"watch_id": wid, "by": cb.from_user.id})
    except Exception:
        pass

    await cb.answer("Скасовано", show_alert=False)
    await menu_list_active(cb)

@router.callback_query(F.data == "menu:list_active")
async def menu_list_active(cb: CallbackQuery):
    log.info(f"menu:list_active from_user={cb.from_user.id if cb.from_user else None}")
    try:
        conn = raw_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                w.id,
                w.channel_id,
                w.template_id,
                w.status,
                w.time_window_end,
                w.created_by,
                t.title,
                COALESCE(w.expected_links_json, t.links)
            FROM watch_posts w
            LEFT JOIN post_templates t ON t.id = w.template_id
            WHERE (w.created_by=? OR w.created_by IS NULL)
              AND w.status IN ('pending','matched')
            ORDER BY w.id DESC
            LIMIT 50
            """,
            (cb.from_user.id,),
        )
        rows = cur.fetchall()
        log.info(f"menu:list_active rows_count={len(rows)}")
    except Exception as e:
        log.exception(f"menu:list_active query failed: {e}")
        rows = []

    if not rows:
        await cb.message.edit_text("Активних watch немає.", reply_markup=main_menu_kb())
        return

    lines: List[str] = []
    kb = InlineKeyboardBuilder()

    for r in rows:
        wid, cid, tid, st, tw_end, created_by, tpl_title, links_json = r
        links = _parse_links_unique(links_json)
        links_n = len(links)
        title_short = _short_title(tpl_title, tid)
        owner_txt = str(created_by) if created_by else "—"
        tw_txt = _fmt_tw_end(tw_end)
        lines.append(f"{wid} | {title_short} | 🔗{links_n} | by {owner_txt} | до {tw_txt}")
        kb.button(text=f"🔗 {links_n}", callback_data=f"watch:links:{wid}")
        kb.button(text="❌ Cancel", callback_data=f"watch:cancel:{wid}")

    kb.adjust(2)

    text = "№ | Template | Links | Owner | Window\n\n" + "\n".join(lines)
    await cb.message.edit_text(text, reply_markup=kb.as_markup())
