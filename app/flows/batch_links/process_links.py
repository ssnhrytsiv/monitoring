# app/flows/batch_links/process_links.py
import logging
import os
import asyncio
from typing import List, Optional
from html import escape as _escape

from telethon.tl import types as ttypes  # ➕ для читання MessageEntityTextUrl

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

# ➕ інтеграція з channel_db
from app.services import channel_db
# ➕ реєстр для reconcile requested → joined
from app.services import requested_reconciler_db as reqdb

log = logging.getLogger("flow.batch_links.process")


def _build_full_footer(items: List[dict]) -> str:
    out: List[str] = ["📊 Підсумок (всі):"]
    for it in items:
        idx = it["idx"]
        url = it["url"]
        title = it.get("title") or ""
        status = it["status"]
        if title:
            out.append(f"{idx}. {_escape(title)}")
            out.append(f"   <a href=\"{_escape(url)}\">Посилання</a> — {status}")
        else:
            out.append(f"{idx}. <a href=\"{_escape(url)}\">Посилання</a> — {status}")
    return "\n".join(out)


async def _short_pause():
    try:
        await asyncio.sleep(0.08)
    except Exception:
        pass


# --- patch 1: розширений парсинг прихованих лінків
from telethon.tl import types as ttypes

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
                # Витягуємо підстроку з оригінального тексту
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


# ===== Owner-conflict helpers =====

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
    """
    + snapshot owner
    + channel_db інтеграція
    + конфлікт owner: channels не оновлюємо, сигналізуємо у звіті
    + requested-reconcile:
        - якщо status=='requested' і вже є channel_id → reqdb.note_requested(session, channel_id)
        - якщо status=='requested', але channel_id ще None (інвайт) → reqdb.note_requested_invite(session, invite_hash)
    """
    # Snapshot owner (fallback із runtime.monitor_buffer, якщо є)
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

    # 1) URL із raw-тексту + 2) приховані
    links_text = extract_links(text)
    hidden = _extract_hidden_links_from_message(message)
    links_all = links_text + hidden
    log.debug("[PL] parsed links: raw=%d hidden=%d", len(links_text), len(hidden))

    seen, links = set(), []
    for u in links_all:
        if u and u not in seen:
            seen.add(u); links.append(u)
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
        # для проби збережемо також kind/hash
        probe_kind: Optional[str] = None
        probe_invite: Optional[str] = None

        log.debug("[PL] #%d start url=%s", idx, url)

        # ---- 1) Дублі
        if url in used:
            log.debug("[PL] #%d duplicate, skipping ensure_join", idx)
            line = fmt_result_line(idx, url, "duplicate")
            results.append(line)
            progress.add_status("already")
            status_part = line.split(" — ", 1)[1] if " — " in line else line
            result_items.append({"idx": idx, "url": url, "title": None, "status": status_part})
            try:
                channel_db.add_link(None, url, None, message.id, od, ou)
                log.debug("[PL] #%d add_link(NULL) recorded (duplicate)", idx)
            except Exception as e:
                log.debug("[PL] #%d add_link(NULL) failed: %s", idx, e)
            await _short_pause()
            continue
        used.add(url)

        # ---- 2) Легка проба (probe)
        if probe_client is not None:
            try:
                log.debug("[PL] #%d probe_channel_id(url=%s)", idx, url)
                # ⬇️ беремо також kind та invite_hash
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
                            log.debug("[PL] #%d upsert_channel(probe) cid=%s", idx, channel_id)
                        else:
                            log.debug("[PL] #%d owner conflict on probe, skip upsert", idx)
                    except Exception as e:
                        log.debug("[PL] #%d upsert_channel(probe) failed: %s", idx, e)
            except Exception as e:
                log.debug("[PL] #%d probe_channel_id error: %s", idx, e)
                channel_id = None

        # ---- 3) Кеш по channel_id
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
                        log.debug("[PL] #%d upsert_channel(final=%s) OK", idx, final)
                    except Exception as e:
                        log.debug("[PL] #%d upsert_channel(final) failed: %s", idx, e)
                try:
                    channel_db.add_link(channel_id, url, None, message.id, od, ou)
                    log.debug("[PL] #%d add_link(cid=%s) OK (cached)", idx, channel_id)
                except Exception as e:
                    log.debug("[PL] #%d add_link(cid) failed: %s", idx, e)
                await _short_pause()
                continue
        else:
            # ---- 4) Кеш по URL
            ust = url_get(url)
            log.debug("[PL] #%d url_get(%s) -> %s", idx, url, ust)
            if ust in ("joined", "already", "requested", "invalid", "private"):
                # ⬇️ КЛЮЧОВЕ: якщо це cached-requested і ми бачимо, що це інвайт, підвісимо перевірку за invite_hash
                if ust == "requested" and probe_kind == "invite" and probe_invite:
                    try:
                        # вибираємо будь-яку сесію з пулу, щоб було кому перевіряти
                        slots_for_inv = list(iter_pool_clients())
                        if slots_for_inv:
                            cli0 = getattr(slots_for_inv[0], "client", slots_for_inv[0])
                            sess0 = _session_name(cli0)
                            reqdb.note_requested_invite(sess0, str(probe_invite),
                                                        start_after_sec=REQ_START)
                            log.debug("[PL] #%d cached-requested: note_requested_invite(session=%s, invite=%s)", idx, sess0, probe_invite)
                        else:
                            log.debug("[PL] #%d cached-requested: no slots available to bind invite-check", idx)
                    except Exception as e:
                        log.debug("[PL] #%d cached-requested: note_requested_invite failed: %s", idx, e)

                line = fmt_result_line(idx, url, "cached", extra=ust)
                results.append(line)
                status_part = line.split(" — ", 1)[1] if " — " in line else line
                result_items.append({"idx": idx, "url": url, "title": title_current, "status": status_part})
                progress.add_status("already" if ust in ("joined", "already") else "invalid")
                try:
                    channel_db.add_link(None, url, None, message.id, od, ou)
                    log.debug("[PL] #%d add_link(NULL) OK (url cache)", idx)
                except Exception as e:
                    log.debug("[PL] #%d add_link(NULL) failed: %s", idx, e)
                await _short_pause()
                continue

        # ---- 5) Нема вільних клієнтів — у чергу
        # --- patch 3: явний лог перед відправкою в чергу, коли немає слотів
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
            ...
            results.append(line)
            status_part = line.split(" — ", 1)[1] if " — " in line else line
            result_items.append({"idx": idx, "url": url, "title": title_current, "status": status_part})
            progress.add_status("flood_wait")
            try:
                channel_db.add_link(channel_id, url, None, message.id, od, ou)
                log.debug("[PL] #%d add_link(%s) queued OK; rest=%d", idx, channel_id, len(rest))
            except Exception as e:
                log.debug("[PL] #%d add_link queued failed: %s", idx, e)
            break
        log.debug("[PL] slots available for ensure_join=%d for url=%s", len(slots), url)

        # ---- 6) Основна спроба
        line = None
        last_kind = None
        cid_eff: Optional[int] = channel_id

        for slot in slots:
            client = getattr(slot, "client", slot)
            who_display = display_name(slot)          # для UI
            who_sess = _session_name(client)          # НОРМАЛІЗОВАНЕ ім'я для БД

            progress.set_current(url, actor=who_display)
            log.debug("[PL] #%d try with session=%s (display=%s) cid_eff=%s", idx, who_sess, who_display, cid_eff)

            if cid_eff is not None:
                # якщо цей акаунт вже очікує підтвердження — НЕ дублюємо join
                try:
                    if reqdb.is_requested(who_sess, cid_eff):
                        log.debug("[PL] #%d session=%s already has pending requested for cid=%s -> skip ensure_join", idx, who_sess, cid_eff)
                        line = fmt_result_line(idx, url, "requested", who_display)
                        progress.add_status("already")
                        break
                except Exception as e:
                    log.debug("[PL] #%d is_requested lookup failed: %s", idx, e)

                acc_status = get_membership(who_sess, cid_eff)
                log.debug("[PL] #%d membership(%s, %s) -> %s", idx, who_sess, cid_eff, acc_status)
                if acc_status in ("joined","already","requested","invalid","private","blocked","too_many"):
                    if acc_status == "requested":
                        log.debug("[PL] #%d membership says requested -> skip ensure_join", idx)
                        line = fmt_result_line(idx, url, "requested", who_display)
                        progress.add_status("already")
                        break
                    continue

            # ⚠️ забираємо також invite_hash (5-й елемент)
            log.debug("[PL] #%d ensure_join start (session=%s, url=%s)", idx, who_sess, url)
            status, title, kind, cid_after, invite_hash = await ensure_join(client, url)
            log.debug("[PL] #%d ensure_join done: status=%s kind=%s cid_after=%s invite_hash=%s", idx, status, kind, cid_after, invite_hash)

            last_kind = kind
            if cid_eff is None:
                cid_eff = cid_after
                log.debug("[PL] #%d cid_eff set from ensure_join -> %s", idx, cid_eff)
            if title and not title_current:
                title_current = title
                log.debug("[PL] #%d title_current set -> %s", idx, title_current)

            if cid_eff is not None and status in ("joined","already","requested","invalid","private","blocked","too_many"):
                upsert_membership(who_sess, cid_eff, status)
                log.debug("[PL] #%d upsert_membership(%s, %s, %s)", idx, who_sess, cid_eff, status)
            if cid_eff is None and status in ("joined","already","requested","invalid","private"):
                url_put(url, status)
                log.debug("[PL] #%d url_put(%s, %s)", idx, url, status)

            # оновлення channels (без зміни owner при конфлікті)
            if cid_eff is not None:
                try:
                    is_conflict, _ = _owner_conflict(cid_eff, od, ou)
                    if not is_conflict:
                        channel_db.upsert_channel(cid_eff, None, title_current, od, ou, status)
                        log.debug("[PL] #%d upsert_channel(cid=%s, status=%s) OK", idx, cid_eff, status)
                    else:
                        log.debug("[PL] #%d owner conflict on upsert_channel -> skip", idx)
                except Exception as e:
                    log.debug("[PL] #%d upsert_channel error: %s", idx, e)

            # Реєстрація/очищення requested саме для цього акаунта
            if status == "requested":
                try:
                    if cid_eff is not None:
                        reqdb.note_requested(who_sess, cid_eff, start_after_sec=REQ_START)
                        log.debug("[PL] #%d note_requested(session=%s, cid=%s)", idx, who_sess, cid_eff)
                    elif kind == "invite" and invite_hash:
                        reqdb.note_requested_invite(who_sess, str(invite_hash), start_after_sec=REQ_START)
                        log.debug("[PL] #%d note_requested_invite(session=%s, invite=%s)", idx, who_sess, invite_hash)
                except Exception as e:
                    log.debug("[PL] #%d note_requested* failed: %s", idx, e)

            if cid_eff is not None and status in ("joined","already","invalid","private","blocked","too_many"):
                try:
                    reqdb.clear(who_sess, cid_eff)
                    log.debug("[PL] #%d reqdb.clear(session=%s, cid=%s)", idx, who_sess, cid_eff)
                except Exception as e:
                    log.debug("[PL] #%d reqdb.clear failed: %s", idx, e)

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

        # помітка про конфлікт owner у підсумок рядка
        is_conflict, ex_owner = _owner_conflict(cid_eff, od, ou)
        if is_conflict:
            line = f"{line} | owner_conflict(existing={ex_owner})"
            log.debug("[PL] #%d final line marked with owner_conflict", idx)

        results.append(line)
        status_part = line.split(" — ", 1)[1] if " — " in line else line
        if is_conflict:
            status_part += f" | owner_conflict(existing={ex_owner})"
        result_items.append({"idx": idx, "url": url, "title": title_current, "status": status_part})

        try:
            channel_db.add_link(cid_eff, url, last_kind, message.id, od, ou)
            log.debug("[PL] #%d add_link(cid=%s, kind=%s) OK", idx, cid_eff, last_kind)
        except Exception as e:
            log.debug("[PL] #%d add_link failed: %s", idx, e)

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