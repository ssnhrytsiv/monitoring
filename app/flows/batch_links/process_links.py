from __future__ import annotations

import logging
import time
import asyncio
from typing import Iterable, List, Optional

from app.plugins.progress_live import DebouncedProgress
from app.utils.throttle import throttle_between_links, throttle_probe
from app.utils.formatting import fmt_result_line, fmt_summary
from app.services.joiner import probe_channel_id, ensure_join
from app.services.account_pool import (
    iter_pool_clients,
    bump_cooldown,
    mark_flood,
    mark_limit,
)
from app.services.db import (
    upsert_membership, get_membership, any_final_for_channel,
    url_get, url_put,
    channel_title_get, channel_title_put,
    url_title_get, url_title_put,
    url_channel_get, url_channel_put,
    backoff_get, backoff_set,
    map_invite_get, map_invite_set,
)
from app.services.link_queue import enqueue as lq_enqueue
from .common import display_name

log = logging.getLogger("flow.batch_links.process")


async def _micro_pause() -> None:
    """Крихітна пауза, щоб не «спамити» редагуваннями і лояльно поводитись, але без зайвих затримок."""
    await asyncio.sleep(0.05)


async def process_links(
    *,
    links: Iterable[str],
    progress: DebouncedProgress,
    monitor_buffer,
    **kwargs,
) -> None:
    links = list(links)
    if not links:
        await progress.finish(footer="❌ Посилань не знайдено")
        return

    used: set[str] = set()
    results: List[dict] = []

    log.info("batch start: raw=%d uniq=%d", len(links), len(set(links)))

    # клієнт для probe (тільки коли кеші не допомогли)
    probe_client = None
    slots_probe = list(iter_pool_clients())
    if slots_probe:
        probe_client = getattr(slots_probe[0], "client", slots_probe[0])

    for idx, url in enumerate(links, start=1):
        progress.set_current(url)

        # локальний дублікат у межах пакета (без великих пауз)
        if url in used:
            results.append(fmt_result_line(idx, url, "duplicate"))
            progress.add_status("already")  # дублікат рахуємо як «вже є»
            used.add(url)
            await _micro_pause()
            continue
        used.add(url)

        # 1) Пошук channel_id без мережі
        channel_id: Optional[int] = url_channel_get(url)
        title_cached: str = channel_title_get(channel_id) or "" if channel_id else ""

        # 1.1) Якщо це інвайт (t.me/+ або joinchat) — пробуємо invite_map (ключ — повний URL)
        if channel_id is None and ("t.me/+" in url or "joinchat" in url):
            cid_inv, title_inv = map_invite_get(url)
            if cid_inv is not None:
                channel_id = cid_inv
            if title_inv and not title_cached:
                title_cached = title_inv

        # 1.2) Якщо досі нічого — обережний probe (це мережевий виклик, тротлимо через throttle_probe)
        if channel_id is None and probe_client is not None:
            try:
                log.debug("process probe: %s", url)
                await throttle_probe(url)  # 👈 обережна коротка затримка перед probe
                cid_probe, title_probe, kind_probe, invite_hash = await probe_channel_id(probe_client, url)
                channel_id = cid_probe
                if title_probe:
                    title_cached = title_cached or title_probe
                if invite_hash:
                    map_invite_set(url, cid_probe, title_probe or None)
                if cid_probe is not None:
                    url_channel_put(url, cid_probe)
                    if title_probe:
                        channel_title_put(cid_probe, title_probe)
            except Exception:
                # залишаємо channel_id=None, далі підстрахуємось кешем URL
                pass

        # 2) Дедуплікація/кеш
        # 2.1) backoff по каналу (жодних великих затримок)
        if channel_id is not None:
            until = backoff_get(channel_id)
            if until:
                left = max(0, until - int(time.time()))
                results.append(fmt_result_line(idx, url, "flood_wait", extra=f"{left}s", title=title_cached))
                progress.add_status("flood_wait")
                await _micro_pause()
                continue

            # 2.2) фінальний статус по каналу
            final = any_final_for_channel(channel_id)
            if final:
                results.append(fmt_result_line(idx, url, "cached", extra=final, title=title_cached))
                progress.add_status("already" if final in ("joined", "already", "requested") else "invalid")
                await _micro_pause()
                continue

        # 2.3) фінальний статус по URL (коли channel_id все ще None)
        ust = url_get(url)
        if ust in ("joined", "already", "requested", "invalid", "private"):
            title_from_url = url_title_get(url) or title_cached
            results.append(fmt_result_line(idx, url, "cached", extra=ust, title=title_from_url))
            progress.add_status("already" if ust in ("joined", "already", "requested") else "invalid")
            await _micro_pause()
            continue

        # 3) Пул акаунтів
        slots = list(iter_pool_clients())
        if not slots:
            rest = [url] + [u for u in links[idx:] if u not in used]
            origin_chat = getattr(progress, "peer", None)
            origin_msg = getattr(progress, "msg_id", None) or 0
            added = lq_enqueue(
                rest,
                batch_id=f"batch:{origin_msg}",
                origin_chat=origin_chat,
                origin_msg=origin_msg,
            )
            results.append({
                "idx": idx, "url": url, "title": title_cached or "",
                "status_code": "flood_wait",
                "status_text": f"⏳ немає вільних; у черзі +{added}",
                "actor": "",
            })
            progress.add_status("flood_wait")
            await _micro_pause()
            break

        # 4) Спроба join по слотах
        final_status_code: Optional[str] = None
        line: Optional[dict] = None
        last_kind: Optional[str] = None
        did_api_call: bool = False  # <— throttle між лінками лише якщо був ensure_join

        for slot in slots:
            # 🔸 Пропускаємо зайняті або «приспані» слоти (FLOOD / cooldown)
            now_ts = time.time()
            if getattr(slot, "busy", False):
                log.debug("process: skip slot %s (busy)", getattr(slot, "name", "?"))
                continue
            if getattr(slot, "next_ready", 0) > now_ts:
                log.debug(
                    "process: skip slot %s (sleep until %.0f, now %.0f)",
                    getattr(slot, "name", "?"), getattr(slot, "next_ready", 0), now_ts
                )
                continue

            client = getattr(slot, "client", slot)
            who = display_name(slot)
            progress.set_current(url, actor=who)

            # не дублюємо роботу, якщо по каналу вже є фінал для цього акаунта
            if channel_id is not None:
                acc_status = get_membership(who, channel_id)
                if acc_status in ("joined","already","requested","invalid","private","blocked","too_many"):
                    continue

            # реальний мережевий виклик
            status, title, kind, cid_after, invite_hash = await ensure_join(client, url)
            did_api_call = True
            last_kind = kind
            cid_eff = channel_id if channel_id is not None else cid_after

            # оновлюємо мапи/назви
            if cid_eff is not None:
                url_channel_put(url, cid_eff)
            if title:
                if cid_eff is not None:
                    channel_title_put(cid_eff, title)
                url_title_put(url, title)
            if invite_hash:
                map_invite_set(url, cid_eff, title or None)

            # запис у БД
            if cid_eff is not None and status in ("joined","already","requested","invalid","private","blocked","too_many"):
                upsert_membership(who, cid_eff, status)
            if cid_eff is None and status in ("joined","already","requested","invalid","private"):
                url_put(url, status)

            # гілки статусів — формуємо лінію + фінальний код
            if status == "already":
                line = fmt_result_line(idx, url, "already", who, title=title or title_cached)
                final_status_code = "already"
                break

            elif status == "joined":
                line = fmt_result_line(idx, url, "joined", who, title=title or title_cached)
                final_status_code = "joined"
                bump_cooldown(client, 8 if kind == "invite" else 3)
                break

            elif status == "requested":
                line = fmt_result_line(idx, url, "requested", who, title=title or title_cached)
                final_status_code = "already"   # у зведенні рахуємо як «успішно/без прямого join»
                bump_cooldown(client, 6)
                break

            elif status == "invalid":
                line = fmt_result_line(idx, url, "invalid", who, title=title or title_cached)
                final_status_code = "invalid"
                break

            elif status == "private":
                line = fmt_result_line(idx, url, "private", who, title=title or title_cached)
                final_status_code = "invalid"
                break

            elif status == "blocked":
                line = fmt_result_line(idx, url, "blocked", who, title=title or title_cached)
                final_status_code = final_status_code or "invalid"
                continue

            elif status == "too_many":
                line = fmt_result_line(idx, url, "too_many", who, title=title or title_cached)
                try:
                    mark_limit(slot, days=2)
                except Exception:
                    pass
                final_status_code = final_status_code or "invalid"
                continue

            elif isinstance(status, str) and status.startswith("flood_wait"):
                # FLOOD: переносимо поточний і решту URL у чергу з backoff, слот — м'яко присипляємо
                try:
                    sec = int(str(status).split("_")[-1])
                except Exception:
                    sec = 60

                line = fmt_result_line(idx, url, "flood_wait", who, extra=f"{sec}s", title=title or title_cached)
                final_status_code = final_status_code or "flood_wait"

                # короткий локальний «сон» слота; довгий робитиме черга
                try:
                    mark_flood(client, int(sec), strategy="soft")
                except Exception:
                    pass

                # канал під FLOOD -> не чіпати його n секунд
                if cid_eff is not None:
                    backoff_set(cid_eff, int(sec))

                # віддати поточний + решту пакета у чергу з backoff’ом
                origin_chat = getattr(progress, "peer", None)
                origin_msg = getattr(progress, "msg_id", None) or 0
                remaining = [u for u in links[idx:] if u not in used]
                to_queue = [url] + remaining
                added = lq_enqueue(
                    to_queue,
                    batch_id=f"batch:{origin_msg}",
                    origin_chat=origin_chat,
                    origin_msg=origin_msg,
                    delay_sec=int(sec),
                    reason="flood_wait",
                )
                log.debug("process: FLOOD_WAIT %ss -> queued current+rest (n=%d)", sec, added)

                # ми не хочемо ще й міжлінковий throttle тут у «прямому» проході
                did_api_call = False
                break

            else:
                line = fmt_result_line(idx, url, "temp", who, extra=status, title=title or title_cached)
                final_status_code = final_status_code or "waiting"
                continue

        if line is None:
            line = fmt_result_line(idx, url, "waiting", title=title_cached or "")
            final_status_code = final_status_code or "waiting"

        results.append(line)

        # ✅ Інкрементуємо підсумок ОДИН раз на URL (без дублювань на FLOOD всередині слотів)
        if final_status_code in ("joined","already","invalid","flood_wait","waiting"):
            progress.add_status(final_status_code if final_status_code != "waiting" else "already")
        else:
            progress.add_status("already")

        # ✅ Throttle тільки якщо був реальний API-виклик ensure_join
        if did_api_call:
            await throttle_between_links(last_kind, url)
        else:
            await _micro_pause()

        # Якщо ми щойно попадали у FLOOD і віддали все у чергу — доцільно перервати пакет
        if final_status_code == "flood_wait":
            break

    await progress.finish(footer=fmt_summary(results))
    log.info("batch done: total=%d uniq=%d", len(links), len(set(links)))