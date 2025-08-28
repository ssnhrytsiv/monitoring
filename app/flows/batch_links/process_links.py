import logging
from typing import List, Optional

from app.plugins.progress_live import DebouncedProgress
from app.utils.link_parser import extract_links, normalize_url
from app.utils.throttle import throttle_between_links
from app.utils.formatting import fmt_result_line, fmt_summary
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

async def process_links(message, text: str):
    # Extract and normalize ALL URLs upfront for consistent caching
    raw_links = extract_links(text)  # This now returns normalized URLs
    links = [normalize_url(url) for url in raw_links]  # Ensure normalization
    
    if not links:
        await message.reply("❌ Посилань не знайдено")
        return

    used: set[str] = set()
    results: List[str] = []

    progress = DebouncedProgress(
        client=message.client,
        peer=message.chat_id,
        title="Пакет посилань",
        total=len(links),
    )
    await progress.start()
    log.info("batch start: raw=%d normalized=%d uniq=%d", len(raw_links), len(links), len(set(links)))

    probe_client = None
    slots_probe = list(iter_pool_clients())
    if slots_probe:
        probe_client = getattr(slots_probe[0], "client", slots_probe[0])

    for idx, url in enumerate(links, start=1):
        progress.set_current(url)

        if url in used:
            results.append(fmt_result_line(idx, url, "duplicate"))
            progress.add_status("already")
            await throttle_between_links(None, url)
            continue
        used.add(url)

        channel_id: Optional[int] = None
        if probe_client is not None:
            try:
                cid, _, _, _ = await probe_channel_id(probe_client, url)
                channel_id = cid
            except Exception:
                channel_id = None

        if channel_id is not None:
            final = any_final_for_channel(channel_id)
            if final:
                results.append(fmt_result_line(idx, url, "cached", extra=final))
                progress.add_status("already" if final in ("joined", "already") else "invalid")
                await throttle_between_links(None, url)
                continue
        else:
            ust = url_get(url)
            if ust in ("joined", "already", "requested", "invalid", "private"):
                results.append(fmt_result_line(idx, url, "cached", extra=ust))
                progress.add_status("already" if ust in ("joined", "already") else "invalid")
                await throttle_between_links(None, url)
                continue

        slots = list(iter_pool_clients())
        if not slots:
            rest = [url] + [u for u in links[idx:] if u not in used]
            added = lq_enqueue(
                rest, batch_id=f"batch:{message.id}",
                origin_chat=message.chat_id, origin_msg=message.id
            )
            results.append(f"{idx}. {url} — 💤 Немає вільних акаунтів; додано у чергу: {added} URL")
            progress.add_status("flood_wait")
            break

        line = None
        last_kind = None

        for slot in slots:
            client = getattr(slot, "client", slot)
            who = display_name(slot)
            progress.set_current(url, actor=who)

            if channel_id is not None:
                acc_status = get_membership(who, channel_id)
                if acc_status in ("joined","already","requested","invalid","private","blocked","too_many"):
                    continue

            status, title, kind, cid_after, _ = await ensure_join(client, url)
            last_kind = kind
            cid_eff = channel_id or cid_after

            if cid_eff is not None and status in ("joined","already","requested","invalid","private","blocked","too_many"):
                upsert_membership(who, cid_eff, status)

            if cid_eff is None and status in ("joined","already","requested","invalid","private"):
                url_put(url, status)

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
                progress.add_status("already")  # успішне завершення без join
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
        await throttle_between_links(last_kind, url)

    await progress.finish(footer=fmt_summary(results[-10:]))
    log.info("batch done: total=%d uniq=%d", len(links), len(set(links)))