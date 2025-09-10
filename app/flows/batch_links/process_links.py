import logging
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
    iter_pool_clients, bump_cooldown, mark_flood, mark_limit,
)
from app.services.membership_db import (
    upsert_membership, get_membership, any_final_for_channel, url_get, url_put,
)
from app.services.link_queue import enqueue as lq_enqueue
from .common import display_name

# ➕ (інтеграція пункт 2): імпорт channel_db
from app.services import channel_db

log = logging.getLogger("flow.batch_links.process")


def _build_full_footer(items: List[dict]) -> str:
    """
    Формує дворядковий підсумок для ВСІХ результатів.
    Формат:
      📊 Підсумок (всі):
      N. Назва
         <a href="URL">Посилання</a> — Статус
    Якщо назви немає: N. <a href="URL">Посилання</a> — Статус (однорядково).
    """
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


# Коротка локальна пауза для кейсів без мережевих дій (кеш/дублі/скип).
async def _short_pause():
    try:
        await asyncio.sleep(0.08)  # ~80 ms, щоб не “забивати” цикл
    except Exception:
        pass


def _extract_hidden_links_from_message(msg) -> List[str]:
    """
    Дістає посилання з гіпертексту (MessageEntityTextUrl) у повідомленні Telethon.
    Повертає чисті URL. Дублі не видаляє (це зробимо пізніше разом із текстовими).
    """
    urls: List[str] = []
    try:
        entities = getattr(msg, "entities", None)
        if not entities:
            return urls
        for ent in entities:
            if isinstance(ent, ttypes.MessageEntityTextUrl):
                u = getattr(ent, "url", None)
                if u:
                    urls.append(u.strip())
    except Exception:
        pass
    return urls


async def process_links(message, text: str, owner_display: Optional[str] = None, owner_username: Optional[str] = None):
    """
    Обробка списку посилань.
    ДОДАНО (інтеграція з channel_db):
      - Приймає (опційно) owner_display / owner_username (як snapshot).
        Якщо викликається старим кодом без цих аргументів — вони залишаться None.
      - Пише в channel_db:
         * upsert_channel(...) при probe (status='probe') якщо відомий channel_id
         * upsert_channel(...) з фінальним last_status після результату
         * add_link(...) для кожного URL (включно з duplicate / cached / queued / waiting)
    """
    # Snapshot owner (на випадок якщо зовнішній код ще не передає явно)
    od = owner_display
    ou = owner_username
    # Якщо не передано — пробуємо обережно отримати з потенційного "monitor_buffer" (якщо десь глобально покладений).
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

    # 1) URL із raw-тексту
    links_text = extract_links(text)

    # 2) Додатково URL із прихованих гіперпосилань
    hidden = _extract_hidden_links_from_message(message)
    links_all = links_text + hidden

    # Усуваємо дублікати, зберігаючи порядок
    seen, links = set(), []
    for u in links_all:
        if u and u not in seen:
            seen.add(u)
            links.append(u)

    if not links:
        await message.reply("❌ Посилань не знайдено")
        return

    used: set[str] = set()
    results: List[str] = []
    result_items: List[dict] = []

    progress = DebouncedProgress(
        client=message.client,
        peer=message.chat_id,
        title="Пакет посилань",
        total=len(links),
    )
    await progress.start()
    log.info("batch start: raw=%d uniq=%d", len(links), len(set(links)))

    probe_client = None
    slots_probe = list(iter_pool_clients())
    if slots_probe:
        probe_client = getattr(slots_probe[0], "client", slots_probe[0])

    for idx, url in enumerate(links, start=1):
        progress.set_current(url)
        title_current: Optional[str] = None
        channel_id: Optional[int] = None
        kind_for_link: Optional[str] = None  # що збережемо в add_link

        # ---- 1) Дублі
        if url in used:
            line = fmt_result_line(idx, url, "duplicate")
            results.append(line)
            progress.add_status("already")
            status_part = line.split(" — ", 1)[1] if " — " in line else line
            result_items.append({"idx": idx, "url": url, "title": None, "status": status_part})
            try:
                channel_db.add_link(None, url, kind_for_link, message.id, od, ou)
            except Exception:
                pass
            await _short_pause()
            continue
        used.add(url)

        # ---- 2) Легка проба (probe)
        if probe_client is not None:
            try:
                cid, title_probe, _, _ = await probe_channel_id(probe_client, url)
                if cid is not None:
                    channel_id = cid
                    if title_probe:
                        title_current = title_probe
                    try:
                        channel_db.upsert_channel(channel_id, None, title_current, od, ou, "probe")
                    except Exception:
                        pass
            except Exception:
                channel_id = None

        # ---- 3) Кеш по channel_id
        if channel_id is not None:
            final = any_final_for_channel(channel_id)
            if final:
                line = fmt_result_line(idx, url, "cached", extra=final)
                results.append(line)
                progress.add_status("already" if final in ("joined", "already") else "invalid")
                status_part = line.split(" — ", 1)[1] if " — " in line else line
                result_items.append({"idx": idx, "url": url, "title": title_current, "status": status_part})
                try:
                    channel_db.upsert_channel(channel_id, None, title_current, od, ou, final)
                    channel_db.add_link(channel_id, url, None, message.id, od, ou)
                except Exception:
                    pass
                await _short_pause()
                continue
        else:
            # ---- 4) Кеш по URL
            ust = url_get(url)
            if ust in ("joined", "already", "requested", "invalid", "private"):
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

        # ---- 5) Нема вільних клієнтів — у чергу (ОНОВЛЕНО enqueue з owner snapshot)
        slots = list(iter_pool_clients())
        if not slots:
            rest = [url] + [u for u in links[idx:] if u not in used]
            added = lq_enqueue(
                rest,
                batch_id=f"batch:{message.id}",
                origin_chat=message.chat_id,
                origin_msg=message.id,
                owner_display=od,
                owner_username=ou
            )
            line = f"{idx}. {url} — 💤 Немає вільних акаунтів; додано у чергу: {added} URL"
            results.append(line)
            status_part = line.split(" — ", 1)[1] if " — " in line else line
            result_items.append({"idx": idx, "url": url, "title": title_current, "status": status_part})
            progress.add_status("flood_wait")
            try:
                channel_db.add_link(channel_id, url, None, message.id, od, ou)
            except Exception:
                pass
            break

        # ---- 6) Основна спроба
        line = None
        last_kind = None
        cid_eff: Optional[int] = channel_id

        for slot in slots:
            client = getattr(slot, "client", slot)
            who = display_name(slot)
            progress.set_current(url, actor=who)

            if cid_eff is not None:
                acc_status = get_membership(who, cid_eff)
                if acc_status in ("joined","already","requested","invalid","private","blocked","too_many"):
                    continue

            status, title, kind, cid_after, _ = await ensure_join(client, url)
            last_kind = kind
            if cid_eff is None:
                cid_eff = cid_after
            if title and not title_current:
                title_current = title

            if cid_eff is not None and status in ("joined","already","requested","invalid","private","blocked","too_many"):
                upsert_membership(who, cid_eff, status)
            if cid_eff is None and status in ("joined","already","requested","invalid","private"):
                url_put(url, status)

            if cid_eff is not None:
                try:
                    channel_db.upsert_channel(cid_eff, None, title_current, od, ou, status)
                except Exception:
                    pass

            if status == "already":
                line = fmt_result_line(idx, url, "already", who)
                progress.add_status("already")
                break
            elif status == "joined":
                line = fmt_result_line(idx, url, "joined", who)
                progress.add_status("joined")
                bump_cooldown(client, 8 if kind == "invite" else 3)
                break
            elif status == "requested":
                line = fmt_result_line(idx, url, "requested", who)
                progress.add_status("already")
                bump_cooldown(client, 6)
                break
            elif status == "invalid":
                line = fmt_result_line(idx, url, "invalid", who)
                progress.add_status("invalid")
                break
            elif status == "private":
                line = fmt_result_line(idx, url, "private", who)
                progress.add_status("invalid")
                break
            elif status == "blocked":
                line = fmt_result_line(idx, url, "blocked", who)
                continue
            elif status == "too_many":
                line = fmt_result_line(idx, url, "too_many", who)
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
                line = fmt_result_line(idx, url, "flood_wait", who, extra=f"{sec}s")
                progress.add_status("flood_wait")
                try:
                    mark_flood(client, int(sec))
                except Exception:
                    pass
                continue
            else:
                line = fmt_result_line(idx, url, "temp", who, extra=status)
                continue

        if not line:
            line = fmt_result_line(idx, url, "waiting")

        results.append(line)
        status_part = line.split(" — ", 1)[1] if " — " in line else line
        result_items.append({
            "idx": idx,
            "url": url,
            "title": title_current,
            "status": status_part,
        })

        kind_for_link = last_kind
        try:
            channel_db.add_link(cid_eff, url, kind_for_link, message.id, od, ou)
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