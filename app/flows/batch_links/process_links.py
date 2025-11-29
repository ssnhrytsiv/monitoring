import logging
import os
import asyncio
from typing import List, Optional, Any, Dict
from html import escape as _escape

from telethon.tl import types as ttypes  # для читання MessageEntityTextUrl

import os
import re
from typing import Optional, List

from aiogram import Bot
from app.bot.processing_guard import set_processing

from app.plugins.progress_live import DebouncedProgress
from app.utils.link_parser import extract_links
from app.utils.throttle import throttle_between_links
from app.utils.formatting import fmt_result_line
from app.services.joiner import probe_channel_id, ensure_join
from app.services.account_pool import (
    iter_ready_pool_clients, bump_cooldown, mark_flood, mark_limit, session_name as _session_name
)

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from app.bot.processing_guard import get_processing, set_processing
from app.bot.keyboards import main_menu_kb
from app.bot.keyboards import back_to_menu_kb

from app.services.membership_db import (
    upsert_membership, get_membership, any_final_for_channel, url_get, url_put,
)
from app.services.link_queue import enqueue as lq_enqueue
from .common import display_name

from app.services import channel_db
from app.services import requested_reconciler_db as reqdb

# guard API
from app.services.owner_conflict_guard import begin as _guard_begin, end as _guard_end
# нормалізація tg-лінків
from app.utils.tg_links import sanitize_link

log = logging.getLogger("flow.batch_links.process")


# --------- Round-robin order helper (in-process) ---------
class _RoundRobinOrder:
    """
    In-process round-robin reordering for available pool slots.
    - Keeps a rotating ring of session names.
    - On each pick, returns slots ordered starting from the current head,
      then advances the head by one for the next call.
    - Respects availability: builds the ring only from currently available sessions
      (we pass only ready slots here).
    """
    def __init__(self) -> None:
        self._ring: List[str] = []
        self._pos: int = 0

    def _sid(self, slot: Any) -> str:
        client = getattr(slot, "client", slot)
        sid = _session_name(client)
        return str(sid)

    def pick_order(self, slots: List[Any]) -> List[Any]:
        if not slots:
            return []
        # map session -> slot and collect available ids
        id_to_slot: Dict[str, Any] = {}
        avail_ids: List[str] = []
        for s in slots:
            sid = self._sid(s)
            if sid not in id_to_slot:
                id_to_slot[sid] = s
                avail_ids.append(sid)

        # rebuild ring to contain only currently available (stable order: keep old order, append new)
        new_ring = [sid for sid in self._ring if sid in avail_ids]
        for sid in avail_ids:
            if sid not in new_ring:
                new_ring.append(sid)
        self._ring = new_ring

        if not self._ring:
            return []

        # normalize head position
        if self._pos >= len(self._ring):
            self._pos = self._pos % max(1, len(self._ring))

        head_idx = self._pos
        ordered_ids = self._ring[head_idx:] + self._ring[:head_idx]
        ordered_slots = [id_to_slot[sid] for sid in ordered_ids if sid in id_to_slot]

        # advance head for next call (one step per URL)
        self._pos = (head_idx + 1) % len(self._ring)

        return ordered_slots


_RR = _RoundRobinOrder()


def _build_full_footer(items: List[dict]) -> str:
    """
    Порядок секцій:
    1) Чисті (без конфліктів і без дублікатів)
    2) Конфлікти (згруповані за адміном)
    3) Інші без конфліктів, але з дублікатами (по одному "оригіналу" на channel_id)
    4) Приватні
    5) Недійсні/помилки
    6) Дублікати (усі «повтори» channel_id) — внизу

    У рядках статусів НЕ показувати 'owner_conflict(existing=...)' (прибираємо для читабельності).
    """
    import re
    from html import escape as _escape
    from typing import Optional, Any, Dict, List

    def _esc(s: str) -> str:
        return _escape(s or "")

    # Витягнути імʼя з owner_conflict(existing=...)
    RE_CONFLICT = re.compile(r"owner_conflict\(existing=([^)]+)\)", re.IGNORECASE)

    def _conflict_name(status: str) -> Optional[str]:
        if not status:
            return None
        m = RE_CONFLICT.search(status)
        return m.group(1).strip() if m else None

    # Прибрати маркер owner_conflict(...) з тексту статусу + почистити роздільники
    def _strip_conflict(status: str) -> str:
        if not status:
            return status or ""
        s = RE_CONFLICT.sub("", status)
        s = re.sub(r"\s*\|\s*\|\s*", " | ", s)   # подвійні |
        s = re.sub(r"^\s*\|\s*|\s*\|\s*$", "", s)  # крайові |
        s = re.sub(r"\s{2,}", " ", s).strip()      # зайві пробіли
        return s

    def _is_private(status: str) -> bool:
        s = (status or "").lower()
        return "private" in s

    def _is_invalid_or_error(status: str) -> bool:
        s = (status or "").lower()
        if _is_private(status):
            return False
        tokens = ("invalid", "error", "temp", "blocked", "too_many", "waiting")
        return any(tok in s for tok in tokens)

    def _link_line(idx: int, url: str, title: Optional[str], status: str, tag: str = "") -> str:
        clean_status = _strip_conflict(status)
        suffix = f" {tag}" if tag else ""
        if title:
            return f"{idx}. {_esc(title)}{suffix}\n   <a href=\"{_esc(url)}\">Посилання</a> — {clean_status}"
        else:
            return f"{idx}. <a href=\"{_esc(url)}\">Посилання</a>{suffix} — {clean_status}"

    # 0) Групування за channel_id і визначення дублікатів
    cid_to_items: Dict[Any, List[dict]] = {}
    for it in (items or []):
        cid = it.get("channel_id")
        if cid is None:
            continue
        cid_to_items.setdefault(cid, []).append(it)
    dup_cids = {cid for cid, lst in cid_to_items.items() if len(lst) > 1}

    # 0.1) Для кожного дублікатного channel_id обрати ПРЕДСТАВНИКА (оригінал, що лишається в секції):
    # - якщо у цього cid є рядки з конфліктом — обираємо той із мінімальним idx серед конфліктних (піде в "Конфлікти")
    # - інакше — рядок із мінімальним idx (піде в "Інші (мають дублікати)")
    rep_idx_by_cid: Dict[Any, int] = {}
    for cid in dup_cids:
        lst = cid_to_items[cid]
        conflict_items = [it for it in lst if _conflict_name(it.get("status") or "") is not None]
        rep = min(conflict_items or lst, key=lambda x: (x.get("idx") or 10**9))
        rep_idx_by_cid[cid] = rep.get("idx")

    # 1) Розподіл по секціях
    clean_unique: List[str] = []          # чисті (без конфліктів, без дублікатів)
    conflicts_by_admin: Dict[str, List[str]] = {}
    other_clean_dup_reps: List[str] = []  # представники без конфліктів, але з дублями
    privates: List[str] = []
    invalids: List[str] = []
    dup_lines_by_cid: Dict[Any, List[str]] = {}  # непредставники для блоку "Дублікати"
    title_by_cid: Dict[Any, Optional[str]] = {}

    for it in (items or []):
        idx: int = it.get("idx") or 0
        url: str = it.get("url") or ""
        title: Optional[str] = it.get("title")
        status: str = it.get("status") or ""
        cid = it.get("channel_id")
        admin = _conflict_name(status)

        # Якщо це дублікатний channel_id і не представник — піде в блок "Дублікати" (внизу)
        if cid is not None and cid in dup_cids and rep_idx_by_cid.get(cid) != idx:
            line = _link_line(idx, url, title, status, tag="[дублікат]")
            dup_lines_by_cid.setdefault(cid, []).append(line)
            if cid not in title_by_cid:
                title_by_cid[cid] = title
            continue

        # Представник або унікальний запис:
        if admin:
            line = _link_line(idx, url, title, status)
            conflicts_by_admin.setdefault(admin, []).append(line)
        elif _is_private(status):
            privates.append(_link_line(idx, url, title, status))
        elif _is_invalid_or_error(status):
            invalids.append(_link_line(idx, url, title, status))
        else:
            # чистий запис (без конфлікту)
            if cid is not None and cid in dup_cids:
                # представник дублікатного cid без конфлікту -> у секцію "інші (мають дублікати)"
                other_clean_dup_reps.append(_link_line(idx, url, title, status))
            else:
                # унікальний канал без конфлікту
                clean_unique.append(_link_line(idx, url, title, status))

    # 2) Рендер у потрібному порядку
    out: List[str] = []
    out.append("📊 Підсумок (всі):")

    # 2.1) Чисті унікальні першими
    if clean_unique:
        out.extend(clean_unique)

    # 2.2) Конфлікти (групами)
    for admin, lines in conflicts_by_admin.items():
        out.append("")
        out.append(f"⚠️ Адмін вже є для цих каналів: {admin}")
        out.extend(lines)

    # 2.3) Інші (мають дублікати) — представники без конфлікту
    if other_clean_dup_reps:
        out.append("")
        out.append("ℹ️ Канали (оригінали), які мають дублікати:")
        out.extend(other_clean_dup_reps)

    # 2.4) Приватні/недоступні
    if privates:
        out.append("")
        out.append("🔒 Приватні/недоступні:")
        out.extend(privates)

    # 2.5) Недійсні/помилки
    if invalids:
        out.append("")
        out.append("❌ Недійсні/помилки:")
        out.extend(invalids)

    # 2.6) Дублікати — внизу
    if dup_lines_by_cid:
        out.append("")
        out.append("🔁 Дублікати каналів (однаковий channel_id у кількох рядках):")
        for cid in sorted(dup_lines_by_cid.keys()):
            title = title_by_cid.get(cid)
            if not title:
                for it in cid_to_items.get(cid, []):
                    if it.get("title"):
                        title = it.get("title")
                        break
            header = f"• {title or 'Без назви'} (ID: {cid})"
            out.append(header)
            for line in dup_lines_by_cid[cid]:
                out.append("  " + line)

    return "\n".join(out)

async def _short_pause():
    try:
        await asyncio.sleep(0.08)
    except Exception:
        pass


def _extract_hidden_links_from_message(msg) -> List[str]:
    urls: List[str] = []
    try:
        entities = getattr(msg, "entities", None)
        if not entities:
            return urls
        text = getattr(msg, "message", "") or ""
        for ent in entities:
            if isinstance(ent, ttypes.MessageEntityTextUrl):
                u = getattr(ent, "url", None)
                if u:
                    urls.append(u.strip())
            elif isinstance(ent, ttypes.MessageEntityUrl):
                o: int = getattr(ent, "offset", 0)
                l: int = getattr(ent, "length", 0)
                try:
                    u = text[o:o+l]
                    if u:
                        urls.append(u.strip())
                except Exception:
                    pass
    except Exception:
        pass
    return urls


def _norm_user(u: Optional[str]) -> Optional[str]:
    if not u:
        return None
    return u.lstrip("@").lower()


# --- Додано: локальний хелпер для запису конфліктів у owner_conflicts
def _persist_owner_conflict(channel_id: Optional[int],
                            new_owner_display: Optional[str],
                            new_owner_username: Optional[str],
                            source_ref: Optional[str],
                            reason: str) -> bool:
    """
    Пише запис у owner_conflicts. Повертає True, якщо запис створено.
    channel_id: Telegram channel_id (не внутрішній id). Якщо None — пропускаємо (не буде прив'язки у звіті).
    source_ref: invite_hash або URL (для дебагу).
    reason: 'probe_mismatch' | 'cached_mismatch' | 'upsert_mismatch' | ін.
    """
    try:
        owner_key = ((new_owner_display or "").lstrip("@").strip()
                     or ((new_owner_username or "").lstrip("@").strip()))
        if not owner_key:
            return False
        if channel_id is None:
            return False
        import sqlite3
        db_path = os.getenv("DB_PATH", "post_watchdog.sqlite3")
        with sqlite3.connect(db_path) as con:
            cur = con.cursor()
            cur.execute(
                """
                INSERT INTO owner_conflicts(owner, channel_id, source_ref, reason, created_at)
                VALUES(?, ?, ?, ?, strftime('%s','now'))
                """,
                (owner_key, int(channel_id), source_ref or "", reason or "unknown")
            )
            con.commit()
        return True
    except Exception:
        log.exception("failed to insert owner_conflict channel_id=%s owner=%s", channel_id,
                      (new_owner_username or new_owner_display))
        return False


def _owner_conflict(channel_id: Optional[int],
                    new_owner_display: Optional[str],
                    new_owner_username: Optional[str]) -> tuple[bool, Optional[str]]:
    if channel_id is None:
        return (False, None)
    try:
        row = channel_db.find_channel(channel_id)
    except Exception:
        return (False, None)
    if not row:
        return (False, None)

    ex_disp = row.get("owner_display")
    ex_user = _norm_user(row.get("owner_username"))
    new_user = _norm_user(new_owner_username)

    if not ex_disp and not ex_user:
        return (False, None)
    if ex_user and new_user and ex_user == new_user:
        return (False, None)
    if (not ex_user or not new_user) and ex_disp and new_owner_display and ex_disp == new_owner_display:
        return (False, None)

    ex_repr = f"@{ex_user}" if ex_user else (ex_disp or "owner?")
    return (True, ex_repr)


def _invite_owner_conflict(invite_hash: Optional[str],
                           new_owner_display: Optional[str],
                           new_owner_username: Optional[str]) -> tuple[bool, Optional[str]]:
    """
    Перевірка конфлікту owner для випадку, коли ми маємо лише інвайт (channel_id ще невідомий)
    і статус може бути 'requested'. Джерело правди — channel_db.get_invite_owner(invite_hash).
    """
    if not invite_hash:
        return (False, None)
    try:
        row = channel_db.get_invite_owner(str(invite_hash))
    except Exception:
        row = None
    if not row:
        return (False, None)

    ex_disp = row.get("owner_display")
    ex_user = _norm_user(row.get("owner_username"))
    new_user = _norm_user(new_owner_username)

    if not ex_disp and not ex_user:
        return (False, None)
    if ex_user and new_user and ex_user == new_user:
        return (False, None)
    if (not ex_user or not new_user) and ex_disp and new_owner_display and ex_disp == new_owner_display:
        return (False, None)

    ex_repr = f"@{ex_user}" if ex_user else (ex_disp or "owner?")
    return (True, ex_repr)


async def process_links(message, text: str, owner_display: Optional[str] = None, owner_username: Optional[str] = None):
    bot_user_id: Optional[int] = None
    raw_text = text or ""
    first_line, _, rest_text = raw_text.partition("\n")
    m_uid = re.match(r"\[BOT_UID:(\d+)\]", first_line.strip())
    if m_uid:
        try:
            bot_user_id = int(m_uid.group(1))
        except Exception:
            bot_user_id = None
        text = rest_text
    else:
        text = raw_text

    od = owner_display
    ou = owner_username
    if od is None or ou is None:
        try:
            from app import runtime  # type: ignore
            mb = getattr(runtime, "monitor_buffer", None)
            if mb:
                if od is None:
                    od = getattr(mb, "owner_display", None)
                if ou is None:
                    ou = getattr(mb, "owner_username", None)
        except Exception:
            pass

    _chat = getattr(message, "chat", None)
    _cid = getattr(_chat, "id", None)
    _src = str(_cid or "")
    _owner_base = (ou or od) or f"no_owner:{_src}"
    _owner_key = f"{_owner_base}#msg:{message.id}"

    _started, _ = _guard_begin(_owner_key, _src, "process_links")
    if not _started:
        log.debug("[PL] guard denied start owner_key=%s src=%s", _owner_key, _src)
        return

    try:
        links_text = extract_links(text)
        hidden = _extract_hidden_links_from_message(message)

        # 🔍 ДЛЯ ДЕБАГУ: показати, що саме ми бачимо
        log.info("[PL] extract_links (plain) -> %r", links_text)
        log.info("[PL] hidden_links (entities) -> %r", hidden)

        links_all = links_text + hidden
        log.info("[PL] parsed links: raw=%d hidden=%d", len(links_text), len(hidden))

        seen, links = set(), []
        for u in links_all:
            if not u:
                continue
            nu = sanitize_link(u) or u
            if nu not in seen:
                seen.add(nu)
                links.append(nu)
        log.debug("[PL] unique links=%d", len(links))

        if not links:
            await message.reply("❌ Посилань не знайдено")
            return

        used: set[str] = set()
        results: List[str] = []
        result_items: List[dict] = []

        progress = DebouncedProgress(
            client=message.client, peer=message.chat_id, title="Пакет посилань", total=len(links)
        )
        await progress.start()
        log.info("batch start: raw=%d uniq=%d", len(links), len(set(links)))

        probe_client = None
        slots_probe = list(iter_ready_pool_clients())
        log.debug("[PL] probe slots available=%d", len(slots_probe))
        if slots_probe:
            probe_client = getattr(slots_probe[0], "client", slots_probe[0])

        try:
            REQ_START = int(os.getenv("REQUESTED_RECONCILE_BACKOFF_START", "21600"))
        except Exception:
            REQ_START = 21600
        log.debug("[PL] REQ_START=%s", REQ_START)

        for idx, url in enumerate(links, start=1):
            progress.set_current(url)
            title_current: Optional[str] = None
            channel_id: Optional[int] = None
            kind_for_link: Optional[str] = None
            invite_owner_conflict_repr: Optional[str] = None
            probe_kind: Optional[str] = None
            probe_invite: Optional[str] = None
            invite_hash_var: Optional[str] = None
            conflict_logged: bool = False

            log.debug("[PL] #%d start url=%s", idx, url)

            if url in used:
                log.debug("[PL] #%d duplicate, skipping ensure_join", idx)
                line = fmt_result_line(idx, url, "duplicate")
                results.append(line)
                progress.add_status("already")
                status_part = line.split(" — ", 1)[1] if " — " in line else line
                result_items.append({"idx": idx, "url": url, "title": None, "status": status_part})
                try:
                    channel_db.add_link(None, url, None, message.id, od, ou)
                except Exception:
                    pass
                await _short_pause()
                continue
            used.add(url)

            if probe_client is not None:
                try:
                    log.debug("[PL] #%d probe_channel_id(url=%s)", idx, url)
                    cid, title_probe, probe_kind, probe_invite = await probe_channel_id(probe_client, url)
                    log.debug("[PL] #%d probe result: cid=%s title=%s kind=%s invite=%s", idx, cid, title_probe, probe_kind, probe_invite)

                    if cid is None and probe_kind == "invite" and probe_invite:
                        try:
                            row_inv = channel_db.get_invite_owner(str(probe_invite))
                        except Exception:
                            row_inv = None
                        if row_inv is None:
                            try:
                                channel_db.set_invite_owner(str(probe_invite), od, ou)
                            except Exception:
                                pass
                        else:
                            try:
                                _ic_probe, _ex_probe = _invite_owner_conflict(str(probe_invite), od, ou)
                                if _ic_probe:
                                    invite_owner_conflict_repr = _ex_probe
                            except Exception:
                                pass

                    if cid is not None:
                        channel_id = cid
                        if title_probe:
                            title_current = title_probe
                        try:
                            is_conflict, _ = _owner_conflict(channel_id, od, ou)
                            if not is_conflict:
                                channel_db.upsert_channel(channel_id, None, title_current, od, ou, "probe")
                            else:
                                if not conflict_logged:
                                    if _persist_owner_conflict(channel_id, od, ou, probe_invite or url, "probe_mismatch"):
                                        conflict_logged = True
                                log.debug("[PL] #%d owner conflict on probe, skip upsert", idx)
                        except Exception:
                            pass
                except Exception as e:
                    log.debug("[PL] #%d probe_channel_id error: %s", idx, e)
                    channel_id = None

            if channel_id is not None:
                final = any_final_for_channel(channel_id)
                log.debug("[PL] #%d any_final_for_channel(%s) -> %s", idx, channel_id, final)
                if final:
                    line = fmt_result_line(idx, url, "cached", extra=final)
                    is_conflict, ex_owner = _owner_conflict(channel_id, od, ou)
                    if is_conflict:
                        line = f"{line} | owner_conflict(existing={ex_owner})"
                        if not conflict_logged:
                            if _persist_owner_conflict(channel_id, od, ou, probe_invite or url, "cached_mismatch"):
                                conflict_logged = True
                        log.debug("[PL] #%d owner conflict on cached, not updating channel row", idx)
                    results.append(line)
                    if final == "joined":
                        progress.add_status("joined")
                    elif final == "already":
                        progress.add_status("already")
                    elif final == "requested":
                        progress.add_status("requested")
                    else:
                        progress.add_status("invalid")
                    status_part = line.split(" — ", 1)[1] if " — " in line else line
                    if is_conflict:
                        status_part += f" | owner_conflict(existing={ex_owner})"
                    result_items.append({"idx": idx, "url": url, "title": title_current, "status": status_part, "channel_id": channel_id})
                    if not is_conflict:
                        try:
                            channel_db.upsert_channel(channel_id, None, title_current, od, ou, final)
                        except Exception:
                            pass
                    try:
                        channel_db.add_link(channel_id, url, None, message.id, od, ou)
                    except Exception:
                        pass
                    await _short_pause()
                    continue
            else:
                ust = url_get(url)
                log.debug("[PL] #%d url_get(%s) -> %s", idx, url, ust)
                if ust in ("joined", "already", "requested", "invalid", "private"):
                    if ust == "requested" and probe_kind == "invite" and probe_invite:
                        try:
                            sess_list = reqdb.get_invite_sessions(str(probe_invite))
                            if sess_list:
                                for sess0 in sess_list:
                                    reqdb.note_requested_invite(sess0, str(probe_invite), start_after_sec=REQ_START)
                            else:
                                log.debug("[PL] requested+invite cached but no invite sessions recorded; skip creating new check")
                        except Exception:
                            pass

                    line = fmt_result_line(idx, url, "cached", extra=ust)
                    _ic_req_inv, _ex_req_inv = (False, None)
                    if ust == "requested" and probe_kind == "invite" and probe_invite:
                        try:
                            _ic_req_inv, _ex_req_inv = _invite_owner_conflict(str(probe_invite), od, ou)
                            if _ic_req_inv:
                                line = f"{line} | owner_conflict(existing={_ex_req_inv})"
                        except Exception:
                            _ic_req_inv, _ex_req_inv = (False, None)

                    results.append(line)
                    status_part = line.split(" — ", 1)[1] if " — " in line else line
                    if _ic_req_inv and _ex_req_inv:
                        status_part += f" | owner_conflict(existing={_ex_req_inv})"
                    result_items.append({"idx": idx, "url": url, "title": title_current, "status": status_part, "channel_id": channel_id})
                    if ust == "joined":
                        progress.add_status("joined")
                    elif ust == "already":
                        progress.add_status("already")
                    elif ust == "requested":
                        progress.add_status("requested")
                    else:
                        progress.add_status("invalid")
                    try:
                        channel_db.add_link(None, url, None, message.id, od, ou)
                    except Exception:
                        pass
                    await _short_pause()
                    continue

            slots_raw = list(iter_ready_pool_clients())
            slots = _RR.pick_order(slots_raw)
            if not slots:
                log.debug("[PL] no available pool slots -> enqueue rest of URLs")
                rest = [url] + [u for u in links[idx:] if u not in used]
                added = lq_enqueue(
                    rest, batch_id=f"batch:{message.id}",
                    origin_chat=message.chat_id, origin_msg=message.id,
                    owner_display=od, owner_username=ou
                )
                line = f"{idx}. {url} — 💤 Немає вільних акаунтів; додано у чергу: {added} URL"
                results.append(line)
                status_part = line.split(" — ", 1)[1] if " — " in line else line
                result_items.append({"idx": idx, "url": url, "title": title_current, "status": status_part, "channel_id": channel_id})
                progress.add_status("flood_wait")
                try:
                    channel_db.add_link(None, url, None, message.id, od, ou)
                except Exception:
                    pass
                break
            log.debug("[PL] slots available for ensure_join=%d for url=%s (RR applied)", len(slots), url)

            line = None
            last_kind = None
            cid_eff: Optional[int] = channel_id

            for slot in slots:
                client = getattr(slot, "client", slot)
                who_display = display_name(slot)
                who_sess = _session_name(client)

                progress.set_current(url, actor=who_display)
                log.debug("[PL] #%d try with session=%s (display=%s) cid_eff=%s", idx, who_sess, who_display, cid_eff)

                if cid_eff is not None:
                    try:
                        if reqdb.is_requested(who_sess, cid_eff):
                            log.debug("[PL] #%d session=%s has pending requested for cid=%s -> skip ensure_join", idx, who_sess, cid_eff)
                            line = fmt_result_line(idx, url, "requested", who_display)
                            progress.add_status("requested")
                            break
                    except Exception:
                        pass

                    acc_status = get_membership(who_sess, cid_eff)
                    log.debug("[PL] #%d membership(%s, %s) -> %s", idx, who_sess, cid_eff, acc_status)
                    if acc_status in ("joined", "already", "requested", "invalid", "private", "blocked", "too_many"):
                        if acc_status == "requested":
                            line = fmt_result_line(idx, url, "requested", who_display)
                            progress.add_status("requested")
                            break
                        continue

                log.debug("[PL] #%d ensure_join start (session=%s, url=%s)", idx, who_sess, url)
                status, title, kind, cid_after, invite_hash = await ensure_join(client, url)
                log.debug("[PL] #%d ensure_join done: status=%s kind=%s cid_after=%s invite_hash=%s", idx, status, kind, cid_after, invite_hash)

                invite_hash_var = invite_hash or invite_hash_var

                last_kind = kind
                if cid_eff is None:
                    cid_eff = cid_after
                if title and not title_current:
                    title_current = title

                if cid_eff is not None and status in ("joined", "already", "requested", "invalid", "private", "blocked", "too_many"):
                    upsert_membership(who_sess, cid_eff, status)
                if cid_eff is None and status in ("joined", "already", "requested", "invalid", "private"):
                    url_put(url, status)

                if cid_eff is not None:
                    try:
                        is_conflict, _ = _owner_conflict(cid_eff, od, ou)
                        if not is_conflict:
                            channel_db.upsert_channel(cid_eff, None, title_current, od, ou, status)
                        else:
                            if not conflict_logged:
                                if _persist_owner_conflict(cid_eff, od, ou, (invite_hash or invite_hash_var or url), "upsert_mismatch"):
                                    conflict_logged = True
                            log.debug("[PL] #%d owner conflict on upsert_channel -> skip", idx)
                    except Exception:
                        pass

                if status == "requested":
                    try:
                        if cid_eff is not None:
                            reqdb.note_requested(who_sess, cid_eff, start_after_sec=REQ_START)
                        elif kind == "invite" and invite_hash:
                            reqdb.note_requested_invite(who_sess, str(invite_hash), start_after_sec=REQ_START)
                    except Exception:
                        pass

                if cid_eff is not None and status in ("joined", "already", "invalid", "private", "blocked", "too_many"):
                    try:
                        reqdb.clear(who_sess, cid_eff)
                    except Exception:
                        pass

                if status == "already":
                    line = fmt_result_line(idx, url, "already", who_display)
                    progress.add_status("already")
                    break
                elif status == "joined":
                    line = fmt_result_line(idx, url, "joined", who_display)
                    progress.add_status("joined")
                    bump_cooldown(client, 8 if kind == "invite" else 3)
                    break
                elif status == "requested":
                    line = fmt_result_line(idx, url, "requested", who_display)
                    progress.add_status("requested")
                    bump_cooldown(client, 6)
                    break
                elif status == "invalid":
                    line = fmt_result_line(idx, url, "invalid", who_display)
                    progress.add_status("invalid")
                    break
                elif status == "private":
                    line = fmt_result_line(idx, url, "private", who_display)
                    progress.add_status("invalid")
                    break
                elif status == "blocked":
                    log.debug("[PL] #%d blocked on session=%s -> try next slot", idx, who_sess)
                    continue
                elif status == "too_many":
                    line = fmt_result_line(idx, url, "too_many", who_display)
                    try:
                        mark_limit(slot, days=2)
                    except Exception:
                        pass
                    continue
                elif isinstance(status, str) and status.startswith("flood_wait"):
                    try:
                        sec = int(str(status).split("_")[-1])
                    except Exception:
                        sec = 60
                    line = fmt_result_line(idx, url, "flood_wait", who_display, extra=f"{sec}s")
                    progress.add_status("flood_wait")
                    try:
                        mark_flood(client, int(sec))
                    except Exception:
                        pass
                    continue
                else:
                    line = fmt_result_line(idx, url, "temp", who_display, extra=status)
                    continue

            if not line:
                line = fmt_result_line(idx, url, "waiting")

            is_conflict, ex_owner = _owner_conflict(cid_eff, od, ou)
            invite_ex_owner = None
            if not is_conflict:
                _invite_eff = invite_hash_var or probe_invite
                if _invite_eff:
                    try:
                        _ic_inv, _ex_inv = _invite_owner_conflict(str(_invite_eff), od, ou)
                        if _ic_inv:
                            invite_ex_owner = _ex_inv
                    except Exception:
                        pass

            if is_conflict:
                line = f"{line} | owner_conflict(existing={ex_owner})"
            elif invite_ex_owner:
                line = f"{line} | owner_conflict(existing={invite_ex_owner})"

            results.append(line)
            status_part = line.split(" — ", 1)[1] if " — " in line else line
            if is_conflict:
                status_part += f" | owner_conflict(existing={ex_owner})"
            elif invite_ex_owner:
                status_part += f" | owner_conflict(existing={invite_ex_owner})"
            result_items.append({"idx": idx, "url": url, "title": title_current, "status": status_part, "channel_id": channel_id})

            try:
                channel_db.add_link(cid_eff, url, last_kind, message.id, od, ou)
            except Exception:
                pass

            if last_kind:
                await throttle_between_links(last_kind, url)
            else:
                await _short_pause()

        try:
            footer_full = _build_full_footer(result_items)
        except Exception:
            footer_full = "📊 Підсумок (всі):\n(помилка формування футера)"
        await progress.finish(footer=footer_full)
        log.info("batch done: total=%d uniq=%d", len(links), len(set(links)))

        if bot_user_id is not None:
            try:
                token = os.getenv("BOT_TOKEN")
                if token:
                    summary_text = progress._last_render or progress._render(
                        header_suffix="— готово ✅",
                        final=True,
                    )

                    async with Bot(
                            token=token,
                            default=DefaultBotProperties(parse_mode="HTML"),
                    ) as bot:
                        pdata = get_processing(bot_user_id) or {}
                        msg_id = pdata.get("msg_id")

                        log.debug(
                            "bot_notify_start",
                            extra={"user_id": bot_user_id, "msg_id": msg_id},
                        )

                        if msg_id:
                            try:
                                await bot.edit_message_text(
                                    chat_id=bot_user_id,
                                    message_id=msg_id,
                                    text=summary_text,
                                    reply_markup=back_to_menu_kb(),
                                    disable_web_page_preview=True,
                                )
                                log.info(
                                    "bot_notify_edited",
                                    extra={"user_id": bot_user_id, "msg_id": msg_id},
                                )
                            except Exception as e:
                                log.exception(
                                    "bot_notify_edit_failed",
                                    extra={
                                        "user_id": bot_user_id,
                                        "msg_id": msg_id,
                                        "err": str(e),
                                    },
                                )
                                await bot.send_message(
                                    bot_user_id,
                                    summary_text,
                                    reply_markup=back_to_menu_kb(),
                                    disable_web_page_preview=True,
                                )
                        else:
                            # fallback: msg_id немає – шлемо нове повідомлення
                            await bot.send_message(
                                bot_user_id,
                                summary_text,
                                reply_markup=back_to_menu_kb(),
                                disable_web_page_preview=True,
                            )
                set_processing(bot_user_id, False)
            except Exception as e:
                log.exception(
                    "bot_notify_failed",
                    extra={"user_id": bot_user_id, "err": str(e)},
                )
    finally:
        _guard_end(_owner_key, _src, "process_links", "done")