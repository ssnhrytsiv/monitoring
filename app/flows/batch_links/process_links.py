# app/flows/batch_links/process_links.py
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


async def process_links(message, text: str):
    # 1) URL із raw-тексту
    links_text = extract_links(text)

    # 2) Додатково URL із прихованих гіперпосилань у самому повідомленні
    #    (message тут — це подія/повідомлення Telethon)
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
    result_items: List[dict] = []  # зібрані структури для фінального футера

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

        # ---- 1) Дублі: без мережі, коротка пауза
        if url in used:
            line = fmt_result_line(idx, url, "duplicate")
            results.append(line)
            progress.add_status("already")
            await _short_pause()
            continue
        used.add(url)

        # ---- 2) Легка проба (без API для інвайтів)
        channel_id: Optional[int] = None
        if probe_client is not None:
            try:
                cid, title_probe, _, _ = await probe_channel_id(probe_client, url)
                title_current = title_probe or title_current
                channel_id = cid
            except Exception:
                channel_id = None

        # ---- 3) Якщо є фінальний статус по channel_id — скипаємо (без мережі)
        if channel_id is not None:
            final = any_final_for_channel(channel_id)
            if final:
                line = fmt_result_line(idx, url, "cached", extra=final)
                results.append(line)
                progress.add_status("already" if final in ("joined", "already") else "invalid")
                await _short_pause()
                status_part = line.split(" — ", 1)[1] if " — " in line else line
                result_items.append({"idx": idx, "url": url, "title": title_current, "status": status_part})
                continue
        else:
            # ---- 4) Якщо є фінальний статус по URL — скипаємо (без мережі)
            ust = url_get(url)
            if ust in ("joined", "already", "requested", "invalid", "private"):
                line = fmt_result_line(idx, url, "cached", extra=ust)
                results.append(line)
                status_part = line.split(" — ", 1)[1] if " — " in line else line
                result_items.append({"idx": idx, "url": url, "title": title_current, "status": status_part})
                progress.add_status("already" if ust in ("joined", "already") else "invalid")
                await _short_pause()
                continue

        # ---- 5) Нема вільних клієнтів — додаємо решту у чергу та завершуємо
        slots = list(iter_pool_clients())
        if not slots:
            rest = [url] + [u for u in links[idx:] if u not in used]
            added = lq_enqueue(
                rest, batch_id=f"batch:{message.id}",
                origin_chat=message.chat_id, origin_msg=message.id
            )
            line = f"{idx}. {url} — 💤 Немає вільних акаунтів; додано у чергу: {added} URL"
            results.append(line)
            status_part = line.split(" — ", 1)[1] if " — " in line else line
            result_items.append({"idx": idx, "url": url, "title": title_current, "status": status_part})
            progress.add_status("flood_wait")
            break

        # ---- 6) Спроба підписки/перевірки
        line = None
        last_kind = None

        for slot in slots:
            client = getattr(slot, "client", slot)
            who = display_name(slot)
            progress.set_current(url, actor=who)

            # Якщо вже маємо фінальний статус для цього акаунта по channel_id — пропускаємо
            if channel_id is not None:
                acc_status = get_membership(who, channel_id)
                if acc_status in ("joined","already","requested","invalid","private","blocked","too_many"):
                    continue

            status, title, kind, cid_after, _ = await ensure_join(client, url)
            last_kind = kind
            cid_eff = channel_id or cid_after
            if title:
                title_current = title_current or title

            # Зберігаємо статуси
            if cid_eff is not None and status in ("joined","already","requested","invalid","private","blocked","too_many"):
                upsert_membership(who, cid_eff, status)
            if cid_eff is None and status in ("joined","already","requested","invalid","private"):
                url_put(url, status)

            # Обробка результату
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

        # ---- 7) Тротлінг між елементами
        if last_kind:
            await throttle_between_links(last_kind, url)
        else:
            await _short_pause()

    # Фінальний футер
    try:
        footer_full = _build_full_footer(result_items)
    except Exception:
        footer_full = "📊 Підсумок (всі):\n(помилка формування футера)"
    await progress.finish(footer=footer_full)
    log.info("batch done: total=%d uniq=%d", len(links), len(set(links)))