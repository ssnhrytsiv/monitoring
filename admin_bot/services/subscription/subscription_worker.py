from __future__ import annotations

import asyncio
import logging
import math
from typing import List, Optional, Dict, Tuple

from sqlalchemy import select
from aiogram.exceptions import TelegramRetryAfter, TelegramServerError

from admin_bot.services import report_cache
from app.services import link_queue, channel_db
from app.services.account_pool import mark_flood, mark_limit, bump_cooldown, session_name
from app.services.joiner import ensure_join, _extract_invite_hash
from app.services.membership_db import (
    any_final_for_channel,
    FINAL_GLOBAL,
    get_any_session_for_channel,
    map_invite_get,
    url_get,
    invite_status_get,
    invite_check_last_session,
)
from admin_bot.services.subscription.subscription_for_bot import ensure_bot_started
from app.utils.throttle import LINK_DELAY_INVITE_MAX, LINK_DELAY_PUBLIC_MAX
from app.utils.tg_links import sanitize_link, extract_bot_username
from admin_bot.services.channels import upsert_channel_full
from admin_bot.db.models import upsert_membership
from admin_bot.services.owner_conflicts import log_conflict
from admin_bot.services.subscription.subscription_menu import split_text_for_telegram, make_report_kb
from admin_bot.services.progress import Progress
from admin_bot.services import admins as svc_admins
from admin_bot.services import networks as svc_networks
from admin_bot.db.session import SessionLocal
from admin_bot.db import models as m
from admin_bot.services.subscription.subscription_slots_pool import get_ready_slot
from admin_bot.services.subscription.subscription_status import normalize_url, render_html_with_statuses
from admin_bot.services.subscription.subscription_report import answer_with_retry
from admin_bot.services.subscription.subscription_utils import norm_keys as collect_norm_keys
from app.logging_json import get_logger, configure_logging

# Гарантований мінімальний логер (на випадок, якщо головний процес не налаштував logging).
if not logging.getLogger().handlers:
    configure_logging()

log = get_logger("admin_bot.queue_worker")


async def process_batch(
    *,
    batch_id: str,
    chat_id: int,
    reply_msg,
    admin_display: str,
    admin_username: Optional[str],
    admin_tg_id: Optional[int],
    raw_text: str,
    raw_html: Optional[str] = None,
    entities=None,
    original_urls: Optional[List[str]] = None,
):
    """
    Обробляє записані в link_queue URL для batch_id. Використовує один lease, якщо доступний.
    """
    db = SessionLocal()
    urls_rec = link_queue.fetch_batch_due(batch_id, limit=200)
    log.info("queue_worker.start batch_id=%s chat_id=%s urls=%s", batch_id, chat_id, len(urls_rec))
    if not urls_rec:
        await answer_with_retry(reply_msg, "Черга порожня або ще не готова.")
        db.close()
        return

    total = len(urls_rec)
    progress = Progress(reply_msg, total=total)
    await progress.start()

    result_items: List[Dict] = []
    admin_id: Optional[int] = None
    current_owner_display = admin_display
    current_owner_username = admin_username

    # Попередня перевірка: якщо URL уже відомий у channel_db і є фінальний статус у membership_db,
    # одразу ставимо "already" без мережевих викликів.
    # --- Підготовка: визначаємо, які URL потребують мережі, а які вже мають фінальний статус ---
    preknown: Dict[str, Tuple[str, Optional[str], int, str, Optional[str]]] = {}
    preknown_urls: set[str] = set()
    cleaned_urls_log: list[str] = []

    def _register_preknown(key: str, data: Tuple[str, Optional[str], int, str, Optional[str]]):
        if not key:
            return
        preknown[key] = data
        preknown_urls.add(key)

    cnt_invite_need = 0
    cnt_public_need = 0
    seen_urls: Dict[str, Dict[str, Optional[str]]] = {}

    def _remember_seen(keys: List[str], title: Optional[str] = None, channel_id: Optional[int] = None, session: Optional[str] = None) -> None:
        for k in keys:
            if not k:
                continue
            entry = seen_urls.get(k, {})
            if title is not None and entry.get("title") is None:
                entry["title"] = title
            if channel_id is not None and entry.get("channel_id") is None:
                entry["channel_id"] = channel_id
            if session is not None and entry.get("session") is None:
                entry["session"] = session
            seen_urls[k] = entry

    for rec in urls_rec:
        _, url, *_ = rec
        bot_username = extract_bot_username(url)
        if bot_username:
            # Боти не рахуються у ETA підписки на канали
            continue
        try:
            cleaned = sanitize_link(url) or url
        except Exception:
            cleaned = url
        cleaned_urls_log.append(cleaned)

        # Визначаємо тип
        inv_hash = _extract_invite_hash(url)
        preferred_session: Optional[str] = None
        if inv_hash:
            try:
                preferred_session = invite_check_last_session(inv_hash)
            except Exception:
                preferred_session = None
        # 1) find_channel_by_link (raw/clean)
        try:
            link_row = channel_db.find_channel_by_link(url) or channel_db.find_channel_by_link(cleaned)
            if link_row:
                cid_link, title_link = link_row
                final = any_final_for_channel(cid_link)
                if final:
                    final_norm = "already" if final == "joined" else final
                    if final_norm in FINAL_GLOBAL and final_norm != "requested":
                        sess_known = get_any_session_for_channel(cid_link)
                        data = (final_norm, title_link, cid_link, "link_cache", sess_known)
                        _register_preknown(url, data)
                        if cleaned != url:
                            _register_preknown(cleaned, data)
                        continue

            # 1b) get_channel_id_by_url
            cid_raw = channel_db.get_channel_id_by_url(url) or channel_db.get_channel_id_by_url(cleaned)
            if cid_raw:
                final = any_final_for_channel(cid_raw)
                if final:
                    final_norm = "already" if final == "joined" else final
                    if final_norm in FINAL_GLOBAL and final_norm != "requested":
                        sess_known = get_any_session_for_channel(cid_raw)
                        data = (final_norm, None, cid_raw, "link_raw", sess_known)
                        _register_preknown(url, data)
                        if cleaned != url:
                            _register_preknown(cleaned, data)
                        continue

            # 2) Інвайт: якщо знаємо invite_hash -> channel_id і фінальний статус
            if inv_hash:
                cid_cached, title_cached = map_invite_get(inv_hash)
                if cid_cached:
                    final = any_final_for_channel(int(cid_cached))
                    if final:
                        final_norm = "already" if final == "joined" else final
                        if final_norm in FINAL_GLOBAL and final_norm != "requested":
                            sess_known = get_any_session_for_channel(int(cid_cached))
                            data = (final_norm, title_cached, int(cid_cached), "invite_cache", sess_known)
                            _register_preknown(url, data)
                            if cleaned != url:
                                _register_preknown(cleaned, data)
                            continue
        except Exception:
            pass

        # 3) url_cache — фінальні стани або duplicate
        try:
            ust = url_get(url) or url_get(cleaned)
        except Exception:
            ust = None
        if ust:
            status_norm = "already" if ust == "joined" else ust
            if (status_norm in FINAL_GLOBAL and status_norm != "requested") or status_norm == "duplicate":
                data = (status_norm, None, None, "url_cache", None)
                _register_preknown(url, data)
                if cleaned != url:
                    _register_preknown(cleaned, data)
                continue

        # Якщо сюди дійшли — мережа потрібна
        if inv_hash:
            # Якщо в invite_status уже є фінальний статус (наприклад, invalid), не рахуємо у ETA
            try:
                st_inv = invite_status_get(inv_hash)
            except Exception:
                st_inv = None
            if st_inv and st_inv != "requested":
                final_norm = "already" if st_inv == "joined" else st_inv
                data = (final_norm, None, None, "invite_status", None)
                _register_preknown(url, data)
                if cleaned != url:
                    _register_preknown(cleaned, data)
                continue
            cnt_invite_need += 1
        else:
            cnt_public_need += 1

    if cleaned_urls_log:
        log.info(
            "queue_worker.cleaned_urls batch_id=%s urls=%s",
            batch_id,
            cleaned_urls_log,
        )

    # Якщо є існуючий адмін з такими даними — використовуємо його одразу, щоб уникнути фальшивих owner_conflict
    db_lookup = SessionLocal()
    try:
        existing_admin = svc_admins.find_admin(
            db_lookup,
            tg_id=admin_tg_id,
            username=admin_username,
            display=admin_display,
        )
        if existing_admin:
            admin_id = existing_admin.id
            current_owner_display = existing_admin.display
            current_owner_username = existing_admin.username
    finally:
        db_lookup.close()

    # Оцінка часу: лише для тих, що потребують мережі
    eta_sec = cnt_invite_need * LINK_DELAY_INVITE_MAX + cnt_public_need * LINK_DELAY_PUBLIC_MAX
    eta_min = math.ceil(eta_sec / 60) if (cnt_invite_need + cnt_public_need) > 0 else 0
    try:
        await reply_msg.answer(
            f"Орієнтовний час підписки: ~{eta_min} хв "
            f"(інвайтів: {cnt_invite_need} x {LINK_DELAY_INVITE_MAX:.0f}s, "
            f"публічних: {cnt_public_need} x {LINK_DELAY_PUBLIC_MAX:.0f}s)."
        )
    except Exception:
        pass
    for idx, rec in enumerate(urls_rec, start=1):
        item_id, url, tries, origin_chat, origin_msg, od, ou = rec
        keys_norm = collect_norm_keys(url)
        existing_seen = None
        for k in keys_norm:
            if k in seen_urls:
                existing_seen = seen_urls[k]
                break
        if existing_seen:
            link_queue.mark_done(item_id)
            title_dup = existing_seen.get("title")
            cid_dup = existing_seen.get("channel_id")
            sess_dup = existing_seen.get("session")
            status_dup = "duplicate"
            status_display = f"{status_dup}[{sess_dup}]" if sess_dup else status_dup
            log.debug(
                "queue_worker.duplicate batch_id=%s idx=%s url=%s title=%s cid=%s sess=%s",
                batch_id,
                idx,
                url,
                title_dup,
                cid_dup,
                sess_dup,
            )
            result_items.append({
                "idx": idx,
                "url": url,
                "title": title_dup,
                "status": status_display,
                "channel_id": cid_dup,
            })
            await progress.update(status_display, title_dup or url, sess_dup)
            try:
                from app.services.membership_db import url_put
                for k in keys_norm:
                    url_put(k, status_dup)
            except Exception:
                pass
            continue
        _remember_seen(keys_norm)

        bot_username = extract_bot_username(url)
        if bot_username:
            slot = await get_ready_slot()
            if slot is None:
                log.warning("queue_worker.no_client batch_id=%s idx=%s url=%s (bot)", batch_id, idx, url)
                result_items.append({"idx": idx, "url": url, "title": None, "status": "no_client", "channel_id": None})
                await progress.update("no_client", url, None)
                continue

            client = slot.client
            sess = session_name(client)
            slot.busy = True
            try:
                link_queue.mark_processing(item_id)
                log.debug(
                    "queue_worker.bot_start start batch_id=%s idx=%s url=%s sess=%s tries=%s",
                    batch_id,
                    idx,
                    url,
                    sess,
                    tries,
                )
                status, _ = await ensure_bot_started(
                    client,
                    url,
                    owner_display=current_owner_display,
                    owner_username=current_owner_username,
                    batch_id=batch_id,
                )
                status_display = f"{status}[{sess}]" if sess else status
                link_queue.mark_done(item_id)
                log.info(
                    "queue_worker.bot_start_done batch_id=%s idx=%s url=%s status=%s sess=%s",
                    batch_id,
                    idx,
                    url,
                    status,
                    sess,
                )
                result_items.append({"idx": idx, "url": url, "title": bot_username, "status": status_display, "channel_id": None})
                await progress.update(status_display, bot_username or url, sess)
                _remember_seen(keys_norm, title=bot_username, channel_id=None, session=sess)
            except Exception as e:
                link_queue.mark_failed(item_id, f"bot_error:{e}", backoff_sec=30)
                log.exception(
                    "queue_worker.bot_start error batch_id=%s idx=%s url=%s sess=%s tries=%s",
                    batch_id,
                    idx,
                    url,
                    sess,
                    tries,
                )
                result_items.append({"idx": idx, "url": url, "title": bot_username, "status": f"bot_error[{sess}]", "channel_id": None})
                await progress.update(f"bot_error[{sess}]", bot_username or url, sess)
            finally:
                slot.busy = False
            continue

        # Швидкий шлях: уже знаємо фінальний статус без мережі
        fast = preknown.get(url)
        if fast:
            base_status, title, cid, kind, sess = fast
            status_for_report = base_status

            if base_status == "duplicate":
                link_queue.mark_done(item_id)
                status_display = f"{status_for_report}[{sess}]" if sess else status_for_report
                result_items.append({
                    "idx": idx,
                    "url": url,
                    "title": title,
                    "status": status_display,
                    "channel_id": cid,
                })
                await progress.update(status_display, title or url, sess)
                try:
                    from app.services.membership_db import url_put
                    url_put(url, status_for_report)
                    for k in collect_norm_keys(url):
                        url_put(k, status_for_report)
                except Exception:
                    pass
                _remember_seen(collect_norm_keys(url), title=title, channel_id=cid, session=sess)
                continue

            if cid is None:
                link_queue.mark_done(item_id)
                status_display = f"{status_for_report}[{sess}]" if sess else status_for_report
                result_items.append({
                    "idx": idx,
                    "url": url,
                    "title": title,
                    "status": status_display,
                    "channel_id": None,
                })
                await progress.update(status_display, title or url, sess)
                try:
                    from app.services.membership_db import url_put
                    url_put(url, status_for_report)
                    for k in collect_norm_keys(url):
                        url_put(k, status_for_report)
                except Exception:
                    pass
                _remember_seen(collect_norm_keys(url), title=title, channel_id=None, session=sess)
                continue
            try:
                upsert_channel_full(
                    db,
                    channel_id=cid,
                    username=None,
                    title=title,
                    owner_display=current_owner_display,
                    owner_username=current_owner_username,
                    last_status=base_status,
                )
            except Exception:
                pass

            # owner_conflict check і прив'язка (як звичайно)
            other_owner = None
            other_owner_id = None
            try:
                row = db.execute(
                    select(m.AdminChannel, m.Admin)
                    .join(m.Admin, m.Admin.id == m.AdminChannel.admin_id)
                    .where(m.AdminChannel.channel_id == cid)
                ).first()
                if row:
                    _, adm_obj = row
                    if adm_obj:
                        other_owner_id = adm_obj.id
                        other_owner = (adm_obj.display or f"@{adm_obj.username}") if adm_obj else None
            except Exception:
                other_owner = None

            if other_owner_id and (admin_id is None or admin_id != other_owner_id):
                status_for_report = f"owner_conflict(existing={other_owner})"
                log_conflict(db, channel_id=cid, owner=other_owner or "unknown", source_ref=url)
                log.warning(
                    "queue_worker.owner_conflict batch_id=%s idx=%s url=%s sess=%s other=%s",
                    batch_id,
                    idx,
                    url,
                    sess,
                    other_owner,
                )
            else:
                if admin_id is None:
                    adm_obj = svc_admins.get_or_create_admin(
                        db,
                        tg_id=admin_tg_id,
                        username=admin_username,
                        display=admin_display,
                    )
                    admin_id = adm_obj.id
                    current_owner_display = adm_obj.display
                    current_owner_username = adm_obj.username

                ch = svc_admins.ensure_channel(db, channel_id=cid, username=None, title=title)
                link_res = svc_admins.attach_channel(db, admin_id=admin_id, channel_id=ch.channel_id)
                svc_networks.move_orphans_to_primary(db, admin_id)

                if link_res.get("status") == "conflict":
                    other_id = link_res.get("admin_id")
                    other = svc_admins.get_admin_by_id(db, other_id) if other_id else None
                    other_name = (other.display or f"@{other.username}") if other else str(other_id)
                    status_for_report = f"owner_conflict(existing={other_name})"
                    log_conflict(db, channel_id=cid, owner=other_name or "unknown", source_ref=url)
                    log.warning(
                        "queue_worker.owner_conflict batch_id=%s idx=%s url=%s sess=%s other=%s",
                        batch_id,
                        idx,
                        url,
                        sess,
                        other_name,
                    )

            upsert_membership(db, channel_id=cid, account=(sess or ""), status=base_status)
            link_queue.mark_done(item_id)
            try:
                from app.services.membership_db import url_put
                url_put(url, status_for_report)
            except Exception:
                pass
            try:
                channel_db.add_link(cid, url, kind, origin_msg, current_owner_display, current_owner_username)
            except Exception:
                pass

            status_display = f"{status_for_report}[{sess}]" if sess else status_for_report
            log.info(
                "queue_worker.item_done batch_id=%s idx=%s url=%s status=%s title=%r cid=%s sess=%s (fast-path)",
                batch_id,
                idx,
                url,
                status_for_report,
                title,
                cid,
                sess,
            )
            result_items.append({
                "idx": idx,
                "url": url,
                "title": title,
                "status": status_display,
                "channel_id": cid,
            })
            await progress.update(status_display, title or url, sess)
            _remember_seen(keys_norm, title=title, channel_id=cid, session=sess)
            continue
        slot = await get_ready_slot(preferred_session=preferred_session)
        if slot is None:
            # немає готових акаунтів навіть після очікування — позначаємо тільки цей елемент
            log.warning("queue_worker.no_client batch_id=%s idx=%s url=%s", batch_id, idx, url)
            result_items.append({"idx": idx, "url": url, "title": None, "status": "no_client", "channel_id": None})
            await progress.update("no_client", url, None)
            continue

        client = slot.client
        sess = session_name(client)
        slot.busy = True
        try:
            link_queue.mark_processing(item_id)
            try:
                log.debug(
                    "queue_worker.ensure_join start batch_id=%s idx=%s url=%s sess=%s tries=%s",
                    batch_id,
                    idx,
                    url,
                    sess,
                    tries,
                )
                status, title, kind, cid, invite_hash = await ensure_join(client, url)
            except Exception as e:
                log.exception(
                    "queue_worker.ensure_join error batch_id=%s idx=%s url=%s sess=%s tries=%s",
                    batch_id,
                    idx,
                    url,
                    sess,
                    tries,
                )
                status, title, cid = f"error:{e}", None, None

            # маркування кулдаунів/флуду
            backoff_seconds = 10
            if status.startswith("flood_wait_"):
                try:
                    secs = int(status.split("_")[-1])
                except Exception:
                    secs = 0
                if secs:
                    mark_flood(client, secs)
                    backoff_seconds = max(backoff_seconds, secs)
            elif status == "too_many":
                mark_limit(client)
            else:
                bump_cooldown(client, 1)

            base_status = status or "unknown"
            status_display = f"{base_status}[{sess}]" if sess else base_status

            if cid is None:
                link_queue.mark_failed(item_id, base_status, backoff_sec=backoff_seconds)
                log.info(
                    "queue_worker.item_failed batch_id=%s idx=%s url=%s status=%s sess=%s",
                    batch_id,
                    idx,
                    url,
                    base_status,
                    sess,
                )
                result_items.append({"idx": idx, "url": url, "title": title, "status": status_display, "channel_id": None})
                await progress.update(status_display, title or url, sess)
                continue

            upsert_channel_full(
                db,
                channel_id=cid,
                username=None,
                title=title,
                owner_display=current_owner_display,
                owner_username=current_owner_username,
                last_status=base_status,
            )

            # Перевіряємо, чи канал уже закріплений за іншим адміном до створення нового
            other_owner = None
            other_owner_id = None
            try:
                row = db.execute(
                    select(m.AdminChannel, m.Admin)
                    .join(m.Admin, m.Admin.id == m.AdminChannel.admin_id)
                    .where(m.AdminChannel.channel_id == cid)
                ).first()
                if row:
                    _, adm_obj = row
                    if adm_obj:
                        other_owner_id = adm_obj.id
                        other_owner = (adm_obj.display or f"@{adm_obj.username}") if adm_obj else None
            except Exception:
                other_owner = None

            status_for_report = base_status
            # owner_conflict: канал уже у іншого адміна і ми ще не створили свого
            if other_owner_id and (admin_id is None or admin_id != other_owner_id):
                status_for_report = f"owner_conflict(existing={other_owner})"
                log_conflict(db, channel_id=cid, owner=other_owner or "unknown", source_ref=url)
                log.warning(
                    "queue_worker.owner_conflict batch_id=%s idx=%s url=%s sess=%s other=%s",
                    batch_id,
                    idx,
                    url,
                    sess,
                    other_owner,
                )
            else:
                # Створюємо адміна лише перед першою успішною прив'язкою
                if admin_id is None:
                    adm_obj = svc_admins.get_or_create_admin(
                        db,
                        tg_id=admin_tg_id,
                        username=admin_username,
                        display=admin_display,
                    )
                    admin_id = adm_obj.id
                    current_owner_display = adm_obj.display
                    current_owner_username = adm_obj.username

                ch = svc_admins.ensure_channel(db, channel_id=cid, username=None, title=title)
                link_res = svc_admins.attach_channel(db, admin_id=admin_id, channel_id=ch.channel_id)
                svc_networks.move_orphans_to_primary(db, admin_id)

                if link_res.get("status") == "conflict":
                    other_id = link_res.get("admin_id")
                    other = svc_admins.get_admin_by_id(db, other_id) if other_id else None
                    other_name = (other.display or f"@{other.username}") if other else str(other_id)
                    status_for_report = f"owner_conflict(existing={other_name})"
                    log_conflict(db, channel_id=cid, owner=other_name or "unknown", source_ref=url)
                    log.warning(
                        "queue_worker.owner_conflict batch_id=%s idx=%s url=%s sess=%s other=%s",
                        batch_id,
                        idx,
                        url,
                        sess,
                        other_name,
                    )

            upsert_membership(db, channel_id=cid, account=sess or "", status=base_status)
            link_queue.mark_done(item_id)
            try:
                from app.services.membership_db import url_put
                url_put(url, status_for_report)
            except Exception:
                pass
            try:
                channel_db.add_link(cid, url, kind, origin_msg, current_owner_display, current_owner_username)
            except Exception:
                pass

            status_display = f"{status_for_report}[{sess}]" if sess else status_for_report
            log.info(
                "queue_worker.item_done batch_id=%s idx=%s url=%s status=%s title=%r cid=%s sess=%s",
                batch_id,
                idx,
                url,
                status_for_report,
                title,
                cid,
                sess,
            )

            result_items.append({
                "idx": idx,
                "url": url,
                "title": title,
                "status": status_display,
                "channel_id": cid,
            })
            await progress.update(status_display, title or url, sess)
            _remember_seen(collect_norm_keys(url), title=title, channel_id=cid, session=sess)
        finally:
            slot.busy = False

    # Перерахунок кількості дублікатів для прогрес-бара:
    # дублікатом вважаємо другий і наступні елементи з тим самим norm_url або channel_id.
    if result_items:
        norm_counts: Dict[str, int] = {}
        cid_counts: Dict[Optional[int], int] = {}
        for it in result_items:
            n = normalize_url(it.get("url", ""))
            norm_counts[n] = norm_counts.get(n, 0) + 1
            cid_counts[it.get("channel_id")] = cid_counts.get(it.get("channel_id"), 0) + 1

        norm_seen: Dict[str, int] = {}
        cid_seen: Dict[Optional[int], int] = {}
        dup_count = 0

        render_order = original_urls if original_urls else [it.get("url", "") for it in result_items]
        buckets: Dict[str, List[Dict]] = {}
        for it in result_items:
            n = normalize_url(it.get("url", ""))
            buckets.setdefault(n, []).append(it)

        def _pop(norm: str) -> Optional[Dict]:
            lst = buckets.get(norm) or []
            if lst:
                return lst.pop(0)
            return None

        for url in render_order:
            norm = normalize_url(url)
            it = _pop(norm)
            if not it:
                continue
            cid = it.get("channel_id")
            norm_seen[norm] = norm_seen.get(norm, 0) + 1
            cid_seen[cid] = cid_seen.get(cid, 0) + 1
            is_dup = False
            if norm_counts.get(norm, 0) > 1 and norm_seen[norm] >= 2:
                is_dup = True
            if cid is not None and cid_counts.get(cid, 0) > 1 and cid_seen[cid] >= 2:
                is_dup = True
            if is_dup:
                dup_count += 1

        progress.duplicates = dup_count
        if dup_count:
            # не рахуємо дублікати у "Был подписан"
            progress.already = max(0, progress.already - dup_count)

    await progress.finish()

    # Рендер звіту зі збереженням форматування та статусами біля кожного лінка
    try:
        html_report = render_html_with_statuses(result_items, original_urls)
    except Exception as e:
        # Замість старого fallback відправляємо текст помилки в бот
        log.exception("queue_worker: failed render html report, fallback disabled")
        pages = [f"Render error: {e}"]
        report_idx = None
        # Старий fallback із build_full_footer залишив закоментованим на випадок повернення
        # footer, sections = build_full_footer(result_items, raw_lines=[raw_text])
        # pages = []
        # pages.extend(split_text_for_telegram(footer, max_len=3500))
        # for label, text in sections:
        #     pages.extend(split_text_for_telegram(f\"{label}:\\n{text}\", max_len=3500))
    else:
        pages = split_text_for_telegram(html_report, max_len=6000)
        report_idx = None
        log.info(
            "queue_worker.report_rendered batch_id=%s pages=%s links=%s",
            batch_id,
            len(pages),
            len(result_items),
        )

    if pages:

        kb = make_report_kb(0, len(pages), has_report=report_idx is not None)
        sent = await answer_with_retry(
            reply_msg,
            pages[0],
            disable_web_page_preview=True,
            parse_mode="HTML",
            reply_markup=kb,
        )
        if sent:
            report_cache.register(sent.chat.id, sent.message_id, pages, report_idx)
            log.info(
                "queue_worker.report_sent batch_id=%s pages=%s report_idx=%s",
                batch_id,
                len(pages),
                report_idx,
            )
        else:
            log.warning(
                "queue_worker.report_send_skipped batch_id=%s pages=%s chat_id=%s (flood/server error)",
                batch_id,
                len(pages),
                chat_id,
            )
    db.close()
