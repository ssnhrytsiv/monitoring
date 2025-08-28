import logging
from typing import Optional

from app.utils.throttle import throttle_between_links
from app.utils.link_parser import normalize_url
from app.services.joiner import probe_channel_id, ensure_join
from app.services.account_pool import (
    iter_pool_clients, mark_flood, mark_limit, session_name as _session_name,
)
from app.services.membership_db import (
    upsert_membership, get_membership, any_final_for_channel, url_get, url_put,
)
from app.services.link_queue import (
    fetch_due as lq_fetch_due, mark_processing as lq_mark_processing,
    mark_done as lq_mark_done, mark_failed as lq_mark_failed,
)

log = logging.getLogger("flow.batch_links.worker")

async def run_link_queue_worker(client):
    log.info("link_queue worker started")
    while True:
        try:
            slots_now = list(iter_pool_clients())
            if not slots_now:
                await _sleep(5); continue

            items = lq_fetch_due(limit=10)
            if not items:
                await _sleep(3); continue

            for item_id, url, tries, origin_chat, origin_msg in items:
                lq_mark_processing(item_id)
                
                # Normalize URL for consistent caching
                normalized_url = normalize_url(url)

                channel_id: Optional[int] = None
                try:
                    cid, _, _, _ = await probe_channel_id(getattr(slots_now[0], "client", slots_now[0]), normalized_url)
                    channel_id = cid
                except Exception:
                    channel_id = None

                if channel_id is not None:
                    final = any_final_for_channel(channel_id)
                    if final:
                        lq_mark_done(item_id); continue
                else:
                    ust = url_get(normalized_url)
                    if ust in ("joined","already","requested","invalid","private"):
                        lq_mark_done(item_id); continue

                slots_now = list(iter_pool_clients())
                if not slots_now:
                    lq_mark_failed(item_id, "no_slots", backoff_sec=15, max_retries=20); continue

                processed = False
                last_kind = None

                for slot in slots_now:
                    cli = getattr(slot, "client", slot)
                    who = _session_name(cli)

                    if channel_id is not None:
                        acc_status = get_membership(who, channel_id)
                        if acc_status in ("joined","already","requested","invalid","private","blocked","too_many"):
                            continue

                    status, title, kind, cid_after, _ = await ensure_join(cli, normalized_url)
                    last_kind = kind
                    cid_eff = channel_id or cid_after

                    if cid_eff is not None and status in ("joined","already","requested","invalid","private","blocked","too_many"):
                        upsert_membership(who, cid_eff, status)

                    if cid_eff is None and status in ("joined","already","requested","invalid","private"):
                        url_put(normalized_url, status)

                    if status in ("already","joined","requested","invalid","private"):
                        lq_mark_done(item_id)
                        processed = True
                        await throttle_between_links(last_kind, normalized_url)
                        break
                    elif status == "blocked":
                        continue
                    elif status == "too_many":
                        try: mark_limit(slot, days=2)
                        except Exception: pass
                        continue
                    elif isinstance(status, str) and status.startswith("flood_wait"):
                        try: sec = int(str(status).split("_")[-1])
                        except Exception: sec = 60
                        try: mark_flood(cli, int(sec))
                        except Exception: pass
                        continue
                    else:
                        lq_mark_failed(item_id, f"temp:{status}", backoff_sec=20, max_retries=20)
                        processed = True
                        break

                if not processed:
                    lq_mark_failed(item_id, "no_slot_processed", backoff_sec=30, max_retries=20)

        except Exception as e:
            log.exception("link_queue worker loop error: %s", e)
            await _sleep(5)

async def _sleep(sec: int):
    import asyncio
    await asyncio.sleep(sec)