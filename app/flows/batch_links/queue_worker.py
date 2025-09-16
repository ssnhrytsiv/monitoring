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
# ➕ реєстр для reconcile requested → joined
from app.services import requested_reconciler_db as reqdb

log = logging.getLogger("flow.batch_links.worker")


def _norm_user(u: Optional[str]) -> Optional[str]:
    if not u:
        return None
    return u.lstrip("@").lower()


def _owner_conflict(channel_id: Optional[int],
                    new_owner_display: Optional[str],
                    new_owner_username: Optional[str]) -> tuple[bool, Optional[str]]:
    """
    Конфлікт: у БД для channel_id вже є owner і він відрізняється від поточного snapshot.
    Повертає (is_conflict, existing_owner_repr).
    """
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

    # якщо в БД owner порожній — конфлікту немає
    if not ex_disp and not ex_user:
        return (False, None)
    # якщо збігається username — той самий owner
    if ex_user and new_user and ex_user == new_user:
        return (False, None)
    # якщо username невідомий, але збігається display — той самий owner
    if (not ex_user or not new_user) and ex_disp and new_owner_display and ex_disp == new_owner_display:
        return (False, None)

    return (True, f"@{ex_user}" if ex_user else (ex_disp or "owner?"))


async def run_link_queue_worker(client):
    log.info("link_queue worker started")
    while True:
        try:
            slots_now = list(iter_pool_clients())
            if not slots_now:
                await _sleep(5)
                continue

            # fetch_due: (id, url, tries, origin_chat, origin_msg, owner_display, owner_username)
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
                invite_hash_probe: Optional[str] = None  # <— додаємо

                # ---- Probe (беремо і invite_hash)
                try:
                    cid, title_probe, _kind, inv_hash = await probe_channel_id(
                        getattr(slots_now[0], "client", slots_now[0]), url
                    )
                    channel_id = cid
                    invite_hash_probe = inv_hash
                    if title_probe:
                        title_current = title_probe
                    if channel_id is not None:
                        try:
                            # при конфлікті — НЕ пишемо навіть 'probe'
                            is_conflict, _ = _owner_conflict(channel_id, owner_display, owner_username)
                            if not is_conflict:
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
                            # при конфлікті — НЕ пишемо в channels
                            is_conflict, _ = _owner_conflict(channel_id, owner_display, owner_username)
                            if not is_conflict:
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
                    if ust in ("joined", "already", "invalid", "private"):
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
                    # Якщо 'requested' — НЕ закриваємо пункт, а пробуємо ще раз (можливо вже accepted)

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

                    # Якщо це інвайт і ця ж сесія вже має pending по invite_hash — НЕ дублюємо join
                    if invite_hash_probe:
                        try:
                            is_pending = getattr(reqdb, "is_requested_invite", None)
                            if callable(is_pending) and is_pending(who, invite_hash_probe):
                                # просто фіксуємо лінк та закриваємо item
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
                                lq_mark_done(item_id)
                                processed = True
                                break
                        except Exception:
                            pass

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
                            # якщо для цього акаунта вже requested — вважаємо, що заявка подана раніше
                            if acc_status == "requested":
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
                                lq_mark_done(item_id)
                                processed = True
                            continue

                    # ensure_join повертає (status, title, kind, channel_id|None, invite_hash|None)
                    status, title, kind, cid_after, invite_hash = await ensure_join(cli, url)
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

                    # Оновлення каналу проміжним/фінальним статусом (з урахуванням конфлікту owner)
                    if cid_eff is not None:
                        try:
                            is_conflict, _ = _owner_conflict(cid_eff, owner_display, owner_username)
                            if not is_conflict:
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

                    # ➕ Реєстрація 'requested' саме для цього акаунта (включно з кейсом без channel_id)
                    if status == "requested":
                        try:
                            if invite_hash:
                                # головний трекінг — по invite_hash
                                reqdb.note_requested_invite(who, str(invite_hash))
                            if cid_eff is not None:
                                # можна паралельно тримати і по channel_id (необов’язково)
                                reqdb.note_requested(who, cid_eff)
                        except Exception:
                            pass

                    # очищення для фінальних
                    if status in ("joined", "already", "invalid", "private", "blocked", "too_many"):
                        try:
                            if invite_hash:
                                reqdb.clear(who, str(invite_hash))
                        except Exception:
                            pass
                        if cid_eff is not None:
                            try:
                                reqdb.clear(who, cid_eff)
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