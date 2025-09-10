import logging
from typing import Optional

from app.utils.throttle import throttle_between_links
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
from app.services import channel_db  # інтеграція з channel_db

log = logging.getLogger("flow.batch_links.worker")


async def run_link_queue_worker(client):
    log.info("link_queue worker started")
    while True:
        try:
            slots_now = list(iter_pool_clients())
            if not slots_now:
                await _sleep(5)
                continue

            # fetch_due тепер повертає:
            # (id, url, tries, origin_chat, origin_msg, owner_display, owner_username)
            items = lq_fetch_due(limit=10)
            if not items:
                await _sleep(3)
                continue

            for item in items:
                (
                    item_id,
                    url,
                    tries,
                    origin_chat,
                    origin_msg,
                    owner_display,
                    owner_username,
                ) = item

                lq_mark_processing(item_id)

                channel_id: Optional[int] = None
                title_current: Optional[str] = None

                # ---- Probe
                try:
                    cid, title_probe, _, _ = await probe_channel_id(
                        getattr(slots_now[0], "client", slots_now[0]), url
                    )
                    channel_id = cid
                    if title_probe:
                        title_current = title_probe
                    if channel_id is not None:
                        try:
                            channel_db.upsert_channel(
                                channel_id,
                                None,
                                title_current,
                                owner_display,
                                owner_username,
                                "probe",
                            )
                        except Exception:
                            pass
                except Exception:
                    channel_id = None

                # ---- Cached by channel_id
                if channel_id is not None:
                    final = any_final_for_channel(channel_id)
                    if final:
                        try:
                            channel_db.upsert_channel(
                                channel_id,
                                None,
                                title_current,
                                owner_display,
                                owner_username,
                                final,
                            )
                            channel_db.add_link(
                                channel_id,
                                url,
                                None,
                                origin_msg,
                                owner_display,
                                owner_username,
                            )
                        except Exception:
                            pass
                        lq_mark_done(item_id)
                        continue
                else:
                    # ---- Cached by URL
                    ust = url_get(url)
                    if ust in (
                        "joined",
                        "already",
                        "requested",
                        "invalid",
                        "private",
                    ):
                        try:
                            channel_db.add_link(
                                None,
                                url,
                                None,
                                origin_msg,
                                owner_display,
                                owner_username,
                            )
                        except Exception:
                            pass
                        lq_mark_done(item_id)
                        continue

                # ---- Refresh slots
                slots_now = list(iter_pool_clients())
                if not slots_now:
                    lq_mark_failed(
                        item_id,
                        "no_slots",
                        backoff_sec=15,
                        max_retries=20,
                    )
                    continue

                processed = False
                last_kind = None
                cid_eff: Optional[int] = channel_id

                for slot in slots_now:
                    cli = getattr(slot, "client", slot)
                    who = _session_name(cli)

                    # Перевірка фінального для акаунта
                    if cid_eff is not None:
                        acc_status = get_membership(who, cid_eff)
                        if acc_status in (
                            "joined",
                            "already",
                            "requested",
                            "invalid",
                            "private",
                            "blocked",
                            "too_many",
                        ):
                            continue

                    status, title, kind, cid_after, _ = await ensure_join(cli, url)
                    last_kind = kind
                    if cid_eff is None:
                        cid_eff = cid_after
                    if title and not title_current:
                        title_current = title

                    # Membership / URL cache
                    if cid_eff is not None and status in (
                        "joined",
                        "already",
                        "requested",
                        "invalid",
                        "private",
                        "blocked",
                        "too_many",
                    ):
                        upsert_membership(who, cid_eff, status)
                    if cid_eff is None and status in (
                        "joined",
                        "already",
                        "requested",
                        "invalid",
                        "private",
                    ):
                        url_put(url, status)

                    # Оновлення каналу проміжним/фінальним статусом
                    if cid_eff is not None:
                        try:
                            channel_db.upsert_channel(
                                cid_eff,
                                None,
                                title_current,
                                owner_display,
                                owner_username,
                                status,
                            )
                        except Exception:
                            pass

                    # Фінальні стани
                    if status in (
                        "already",
                        "joined",
                        "requested",
                        "invalid",
                        "private",
                    ):
                        lq_mark_done(item_id)
                        processed = True
                        try:
                            channel_db.add_link(
                                cid_eff,
                                url,
                                last_kind,
                                origin_msg,
                                owner_display,
                                owner_username,
                            )
                        except Exception:
                            pass
                        await throttle_between_links(last_kind, url)
                        break
                    elif status == "blocked":
                        # пробуємо іншим слотом
                        continue
                    elif status == "too_many":
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
                        try:
                            mark_flood(cli, int(sec))
                        except Exception:
                            pass
                        continue
                    else:
                        # Тимчасова / невідома → backoff
                        lq_mark_failed(
                            item_id,
                            f"temp:{status}",
                            backoff_sec=20,
                            max_retries=20,
                        )
                        processed = True
                        break

                if not processed:
                    lq_mark_failed(
                        item_id,
                        "no_slot_processed",
                        backoff_sec=30,
                        max_retries=20,
                    )

        except Exception as e:
            log.exception("link_queue worker loop error: %s", e)
            await _sleep(5)


async def _sleep(sec: int):
    import asyncio
    await asyncio.sleep(sec)