# app/flows/batch_links/process_links.py
import logging
import os
import asyncio
from typing import List, Optional
from html import escape as _escape

from telethon.tl import types as ttypes  # для читання MessageEntityTextUrl

from app.plugins.progress_live import DebouncedProgress
from app.utils.link_parser import extract_links
from app.utils.throttle import throttle_between_links
from app.utils.formatting import fmt_result_line
from app.services.joiner import probe_channel_id, ensure_join
from app.services.account_pool import (
    iter_pool_clients, bump_cooldown, mark_flood, mark_limit, session_name as _session_name
)
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


def _build_full_footer(items: List[dict]) -> str:
    """
    Рендер підсумку з новою логікою:
    1) Спочатку – всі “нормальні” (без owner_conflict)
    2) Далі – групи з конфліктами за іменем адміна: "⚠️ Адмін вже є для цих каналів: <ім'я>"
    3) Окремий блок для 'private'
    4) Окремий блок для 'invalid' та інших помилок (щоб не зливати з private)
    ВАЖЛИВО: у рядках статусів НЕ показувати 'owner_conflict(existing=...)'.
    """
    import re

    def _esc(s: str) -> str:
        return _escape(s or "")

    # Витягує імʼя з owner_conflict(existing=...)
    RE_CONFLICT = re.compile(r"owner_conflict\(existing=([^)]+)\)", re.IGNORECASE)

    def _conflict_name(status: str) -> Optional[str]:
        if not status:
            return None
        m = RE_CONFLICT.search(status)
        return m.group(1).strip() if m else None

    # Прибрати маркер owner_conflict(...) з тексту статусу + прибрати подвійні роздільники
    def _strip_conflict(status: str) -> str:
        if not status:
            return status
        s = RE_CONFLICT.sub("", status)
        # почистити зайві " | " після вилучення маркера
        s = re.sub(r"\s*\|\s*\|\s*", " | ", s)  # подвійні |
        s = re.sub(r"^\s*\|\s*|\s*\|\s*$", "", s)  # крайові |
        s = re.sub(r"\s{2,}", " ", s).strip()      # зайві пробіли
        return s

    def _is_private(status: str) -> bool:
        s = (status or "").lower()
        return "private" in s

    def _is_invalid_or_error(status: str) -> bool:
        s = (status or "").lower()
        # усе проблемне, окрім private: invalid, error/temp, blocked, too_many, waiting
        if _is_private(status):
            return False
        tokens = ("invalid", "error", "temp", "blocked", "too_many", "waiting")
        return any(tok in s for tok in tokens)

    def _link_line(idx: int, url: str, title: Optional[str], status: str) -> str:
        clean_status = _strip_conflict(status)
        if title:
            return f"{idx}. {_esc(title)}\n   <a href=\"{_esc(url)}\">Посилання</a> — {clean_status}"
        else:
            return f"{idx}. <a href=\"{_esc(url)}\">Посилання</a> — {clean_status}"

    normal: List[str] = []
    conflicts: dict[str, List[str]] = {}  # admin_name -> [lines]
    privates: List[str] = []
    invalids: List[str] = []

    for it in (items or []):
        idx: int = it.get("idx") or 0
        url: str = it.get("url") or ""
        title: Optional[str] = it.get("title")
        status: str = it.get("status") or ""

        admin = _conflict_name(status)
        line = _link_line(idx, url, title, status)

        if admin:
            conflicts.setdefault(admin, []).append(line)
        elif _is_private(status):
            privates.append(line)
        elif _is_invalid_or_error(status):
            invalids.append(line)
        else:
            normal.append(line)

    out: List[str] = []
    out.append("📊 Підсумок (всі):")

    if normal:
        out.extend(normal)

    # конфлікти по кожному адміну
    for admin, lines in conflicts.items():
        out.append("")
        out.append(f"⚠️ Адмін вже є для цих каналів: {admin}")
        out.extend(lines)

    if privates:
        out.append("")
        out.append("🔒 Приватні/недоступні:")
        out.extend(privates)

    if invalids:
        out.append("")
        out.append("❌ Недійсні/помилки:")
        out.extend(invalids)

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


async def process_links(message, text: str, owner_display: Optional[str] = None, owner_username: Optional[str] = None):
    # snapshot owner (із буфера, якщо не передали явно)
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

    # ---- GUARD FIX: ключ для guard має бути не порожнім
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
        # 1) URL із raw-тексту + 2) приховані (entities)
        links_text = extract_links(text)
        hidden = _extract_hidden_links_from_message(message)
        links_all = links_text + hidden
        log.debug("[PL] parsed links: raw=%d hidden=%d", len(links_text), len(hidden))

        # нормалізація + дедуп
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
        slots_probe = list(iter_pool_clients())
        log.debug("[PL] probe slots available=%d", len(slots_probe))
        if slots_probe:
            probe_client = getattr(slots_probe[0], "client", slots_probe[0])

        # початковий бекоф для першої перевірки requested (з .env)
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
            probe_kind: Optional[str] = None
            probe_invite: Optional[str] = None

            log.debug("[PL] #%d start url=%s", idx, url)

            # дублі в межах одного пакету
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

            # легка проба
            if probe_client is not None:
                try:
                    log.debug("[PL] #%d probe_channel_id(url=%s)", idx, url)
                    cid, title_probe, probe_kind, probe_invite = await probe_channel_id(probe_client, url)
                    log.debug("[PL] #%d probe result: cid=%s title=%s kind=%s invite=%s", idx, cid, title_probe, probe_kind, probe_invite)
                    if cid is not None:
                        channel_id = cid
                        if title_probe:
                            title_current = title_probe
                        try:
                            is_conflict, _ = _owner_conflict(channel_id, od, ou)
                            if not is_conflict:
                                channel_db.upsert_channel(channel_id, None, title_current, od, ou, "probe")
                            else:
                                log.debug("[PL] #%d owner conflict on probe, skip upsert", idx)
                        except Exception:
                            pass
                except Exception as e:
                    log.debug("[PL] #%d probe_channel_id error: %s", idx, e)
                    channel_id = None

            # кеш по channel_id
            if channel_id is not None:
                final = any_final_for_channel(channel_id)
                log.debug("[PL] #%d any_final_for_channel(%s) -> %s", idx, channel_id, final)
                if final:
                    line = fmt_result_line(idx, url, "cached", extra=final)
                    is_conflict, ex_owner = _owner_conflict(channel_id, od, ou)
                    if is_conflict:
                        line = f"{line} | owner_conflict(existing={ex_owner})"
                        log.debug("[PL] #%d owner conflict on cached, not updating channel row", idx)
                    results.append(line)
                    progress.add_status("already" if final in ("joined", "already") else "invalid")
                    status_part = line.split(" — ", 1)[1] if " — " in line else line
                    if is_conflict:
                        status_part += f" | owner_conflict(existing={ex_owner})"
                    result_items.append({"idx": idx, "url": url, "title": title_current, "status": status_part})
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
                # кеш по URL
                ust = url_get(url)
                log.debug("[PL] #%d url_get(%s) -> %s", idx, url, ust)
                if ust in ("joined", "already", "requested", "invalid", "private"):
                    if ust == "requested" and probe_kind == "invite" and probe_invite:
                        try:
                            slots_for_inv = list(iter_pool_clients())
                            if slots_for_inv:
                                cli0 = getattr(slots_for_inv[0], "client", slots_for_inv[0])
                                sess0 = _session_name(cli0)
                                reqdb.note_requested_invite(sess0, str(probe_invite), start_after_sec=REQ_START)
                        except Exception:
                            pass

                    line = fmt_result_line(idx, url, "cached", extra=ust)
                    results.append(line)
                    status_part = line.split(" — ", 1)[1] if " — " in line else line
                    result_items.append({"idx": idx, "url": url, "title": title_current, "status": status_part})
                    progress.add_status("already" if ust in ("joined", "already") else "invalid")
                    try:
                        channel_db.add_link(None, url, None, message.id, od, ou)
                    except Exception:
                        pass
                    await _short_pause()
                    continue

            # немає вільних клієнтів — у чергу
            slots = list(iter_pool_clients())
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
                result_items.append({"idx": idx, "url": url, "title": title_current, "status": status_part})
                progress.add_status("flood_wait")
                try:
                    channel_db.add_link(None, url, None, message.id, od, ou)
                except Exception:
                    pass
                break
            log.debug("[PL] slots available for ensure_join=%d for url=%s", len(slots), url)

            # основна спроба
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
                            progress.add_status("already")
                            break
                    except Exception:
                        pass

                    acc_status = get_membership(who_sess, cid_eff)
                    log.debug("[PL] #%d membership(%s, %s) -> %s", idx, who_sess, cid_eff, acc_status)
                    if acc_status in ("joined","already","requested","invalid","private","blocked","too_many"):
                        if acc_status == "requested":
                            line = fmt_result_line(idx, url, "requested", who_display)
                            progress.add_status("already")
                            break
                        continue

                log.debug("[PL] #%d ensure_join start (session=%s, url=%s)", idx, who_sess, url)
                status, title, kind, cid_after, invite_hash = await ensure_join(client, url)
                log.debug("[PL] #%d ensure_join done: status=%s kind=%s cid_after=%s invite_hash=%s", idx, status, kind, cid_after, invite_hash)

                last_kind = kind
                if cid_eff is None:
                    cid_eff = cid_after
                if title and not title_current:
                    title_current = title

                if cid_eff is not None and status in ("joined","already","requested","invalid","private","blocked","too_many"):
                    upsert_membership(who_sess, cid_eff, status)
                if cid_eff is None and status in ("joined","already","requested","invalid","private"):
                    url_put(url, status)

                if cid_eff is not None:
                    try:
                        is_conflict, _ = _owner_conflict(cid_eff, od, ou)
                        if not is_conflict:
                            channel_db.upsert_channel(cid_eff, None, title_current, od, ou, status)
                        else:
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

                if cid_eff is not None and status in ("joined","already","invalid","private","blocked","too_many"):
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
                    progress.add_status("already")
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
            if is_conflict:
                line = f"{line} | owner_conflict(existing={ex_owner})"

            results.append(line)
            status_part = line.split(" — ", 1)[1] if " — " in line else line
            if is_conflict:
                status_part += f" | owner_conflict(existing={ex_owner})"
            result_items.append({"idx": idx, "url": url, "title": title_current, "status": status_part})

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
    finally:
        _guard_end(_owner_key, _src, "process_links", "done")