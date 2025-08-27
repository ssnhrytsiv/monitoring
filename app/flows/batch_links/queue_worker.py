# app/flows/batch_links/queue_worker.py
from __future__ import annotations

import logging
from typing import Optional
from app.services.boot_gate import is_hold as boot_hold
from app.utils.throttle import throttle_between_links, throttle_probe
from app.services.joiner import probe_channel_id, ensure_join
from app.services.account_pool import (
    iter_pool_clients,
    mark_flood,
    mark_limit,
    session_name as _session_name,
    bump_cooldown,
)
from app.services.db import (
    upsert_membership,
    get_membership,
    any_final_for_channel,
    url_get,
    url_put,
    # опціонально можете підключити ці кеші теж:
    # url_channel_get, url_channel_put,
    # channel_title_put, url_title_put,
)
from app.services.link_queue import (
    fetch_due as lq_fetch_due,
    mark_processing as lq_mark_processing,
    mark_done as lq_mark_done,
    reschedule as lq_reschedule,  # новий, краще ніж mark_failed для повторів
    mark_failed_final as lq_failed_final,
)

log = logging.getLogger("flow.batch_links.worker")


async def run_link_queue_worker(client, submitter=None) -> None:
    """
    Воркер, що підхоплює чергу link_queue і обробляє її обережно:
      - максимум локальних кешів перед будь-яким мережевим викликом;
      - probe з легким throttle;
      - throttle між URL лише після реальної спроби join (ensure_join);
      - FLOOD_WAIT -> reschedule із відповідним backoff.
      - TEMP RATE LIMIT -> reschedule на вказану кількість секунд (або дефолт 45с).
    """
    log.info("link_queue worker started")
    while True:
        try:
            slots_now = list(iter_pool_clients())
            if not slots_now:
                await _sleep(5)
                continue

            # fetch_due -> список dict’ів
            items = lq_fetch_due(limit=12)
            if not items:
                await _sleep(3)
                continue

            for it in items:
                item_id = it["id"]
                url = it["url"]
                tries = it["tries"]
                origin_chat = it.get("origin_chat")
                origin_msg = it.get("origin_msg")

                lq_mark_processing(item_id)

                # -----------------------------
                # 1) локальна дедуплікація/кеш
                # -----------------------------
                channel_id: Optional[int] = None

                # Якщо хочете — увімкніть свій url_channel_get тут
                # channel_id = url_channel_get(url)

                # Якщо ще не знаємо channel_id — спробуємо дешевий probe
                if channel_id is None:
                    # легкий throttle для розрідження burst’ів
                    await throttle_probe(url)
                    log.debug("worker probe: %s", url)
                    try:
                        cid, _, _, _ = await probe_channel_id(
                            getattr(slots_now[0], "client", slots_now[0]), url
                        )
                        channel_id = cid
                    except Exception:
                        channel_id = None

                # Якщо маємо channel_id і по ньому вже є фінал — done
                if channel_id is not None:
                    final = any_final_for_channel(channel_id)
                    if final:
                        lq_mark_done(item_id)
                        continue
                else:
                    # fallback — кеш по самому URL
                    ust = url_get(url)
                    if ust in ("joined", "already", "requested", "invalid", "private"):
                        lq_mark_done(item_id)
                        continue

                # -----------------------------
                # 2) підбираємо доступні слоти
                # -----------------------------
                slots_now = list(iter_pool_clients())
                if not slots_now:
                    # м’яко перенесемо спробу
                    lq_reschedule(item_id, backoff_sec=15, reason="no_slots", max_retries=30)
                    continue

                processed = False
                last_kind = None
                did_api_call = False  # throttle між URL лише якщо був ensure_join

                for slot in slots_now:
                    cli = getattr(slot, "client", slot)
                    who = _session_name(cli)

                    # якщо відомий канал і цей акаунт вже має фінал — скіпаємо слот
                    if channel_id is not None:
                        acc_status = get_membership(who, channel_id)
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

                    # -----------------------------
                    # 3) реальна спроба join
                    # -----------------------------
                    status, title, kind, cid_after, _ = await ensure_join(cli, url)
                    did_api_call = True
                    last_kind = kind
                    cid_eff = channel_id or cid_after

                    # оновлення БД/кешів станів
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

                    # (опційно) зберігати назви/мапи, якщо підключите:
                    # if cid_eff: url_channel_put(url, cid_eff)
                    # if title:
                    #     if cid_eff: channel_title_put(cid_eff, title)
                    #     url_title_put(url, title)

                    # -----------------------------
                    # 4) розбір результату
                    # -----------------------------
                    if status in ("already", "joined", "requested"):
                        # успіх/умовний успіх — завершити
                        if status == "joined":
                            bump_cooldown(cli, 8 if kind == "invite" else 3)
                        elif status == "requested":
                            bump_cooldown(cli, 6)

                        lq_mark_done(item_id)
                        processed = True
                        break

                    if status in ("invalid", "private"):
                        lq_mark_done(item_id)  # повторювати нема сенсу
                        processed = True
                        break

                    if status == "blocked":
                        # спробуємо інший слот
                        continue

                    if status == "too_many":
                        try:
                            mark_limit(slot, days=2)
                        except Exception:
                            pass
                        # інший слот може вдатись
                        continue

                    # --- FLOOD_WAIT ---
                    if isinstance(status, str) and status.startswith("flood_wait"):
                        # приклад: 'flood_wait_251'
                        try:
                            sec = int(status.split("_")[-1])
                        except Exception:
                            sec = 60

                        try:
                            # М'ЯКИЙ локальний сон (короткий), а довгий бекоф робить черга:
                            mark_flood(cli, int(sec), strategy="soft")
                        except Exception:
                            pass

                        # перенесемо завдання з backoff’ом, причому reason=flood_wait
                        lq_reschedule(
                            item_id,
                            backoff_sec=sec,
                            reason="flood_wait",
                            max_retries=50,
                        )
                        processed = True
                        break

                    # --- TEMP RATE LIMIT (нове) ---
                    if isinstance(status, str) and status.startswith("temp_rate_limit"):
                        # може прийти як 'temp_rate_limit' або 'temp_rate_limit_XX'
                        parts = status.split("_")
                        if len(parts) >= 3:
                            # temp_rate_limit_<sec>
                            try:
                                sec = int(parts[-1])
                            except Exception:
                                sec = 45
                        else:
                            sec = 45  # дефолт

                        lq_reschedule(
                            item_id,
                            backoff_sec=sec,
                            reason="temp_rate_limit",
                            max_retries=40,
                        )
                        processed = True
                        break

                    # тимчасові помилки/незрозумілі коди — відкласти трохи
                    lq_reschedule(
                        item_id,
                        backoff_sec=20,
                        reason=f"temp:{status}",
                        max_retries=30,
                    )
                    processed = True
                    break

                # якщо жоден слот не підійшов (усі «зайняті»/blocked/too_many)
                if not processed:
                    lq_reschedule(item_id, backoff_sec=30, reason="no_slot_processed", max_retries=30)

                # throttle між URL лише після реального API-виклику
                if did_api_call:
                    await throttle_between_links(last_kind, url)

        except Exception as e:
            log.exception("link_queue worker loop error: %s", e)
            await _sleep(5)


async def _sleep(sec: int) -> None:
    import asyncio
    await asyncio.sleep(sec)