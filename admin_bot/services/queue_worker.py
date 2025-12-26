from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Dict, Tuple
import math

from sqlalchemy import select
from app.services import link_queue
from app.services.account_pool import (
    iter_ready_pool_clients,
    session_name,
    mark_flood,
    mark_limit,
    bump_cooldown,
)
from app.services.joiner import ensure_join, _extract_invite_hash
from app.services.membership_db import any_final_for_channel, FINAL_GLOBAL, get_any_session_for_channel, map_invite_get
from app.services import channel_db
from app.utils.throttle import LINK_DELAY_INVITE_MAX, LINK_DELAY_PUBLIC_MAX
from app.utils.tg_links import sanitize_link
from admin_bot.services.channels import upsert_channel_full
from admin_bot.services.memberships import upsert_membership
from admin_bot.services.owner_conflicts import log_conflict
from admin_bot.services.report import split_text_for_telegram, build_full_footer
from admin_bot.services.progress import Progress
from admin_bot.db.session import SessionLocal
from admin_bot.services import admins as svc_admins
from admin_bot.services import networks as svc_networks
from admin_bot.db import models as m
from app.logging_json import get_logger, configure_logging

# Гарантований мінімальний логер (на випадок, якщо головний процес не налаштував logging).
if not logging.getLogger().handlers:
    configure_logging()

log = get_logger("admin_bot.queue_worker")


class _RoundRobin:
    """
    Мінімальний RR для розподілу URL між готовими слотами пулу.
    Зберігає кільце і зсуває голову на кожен виклик pick().
    """

    def __init__(self) -> None:
        self._ring: List[str] = []
        self._pos: int = 0

    def _sid(self, slot) -> str:
        try:
            return getattr(slot, "name", None) or session_name(slot.client)
        except Exception:
            return "unknown"

    def pick(self, slots: List) -> Optional:
        if not slots:
            return None

        id_to_slot: Dict[str, any] = {}
        avail_ids: List[str] = []
        for s in slots:
            sid = self._sid(s)
            if sid not in id_to_slot:
                id_to_slot[sid] = s
                avail_ids.append(sid)

        # перебудовуємо кільце, зберігаючи попередній порядок
        new_ring = [sid for sid in self._ring if sid in avail_ids]
        for sid in avail_ids:
            if sid not in new_ring:
                new_ring.append(sid)
        self._ring = new_ring

        if not self._ring:
            return None

        if self._pos >= len(self._ring):
            self._pos %= len(self._ring)

        head_idx = self._pos
        ordered_ids = self._ring[head_idx:] + self._ring[:head_idx]
        self._pos = (head_idx + 1) % len(self._ring)

        for sid in ordered_ids:
            slot = id_to_slot.get(sid)
            if slot:
                return slot
        return None


_RR = _RoundRobin()


async def _get_ready_slot(max_wait_sec: int = 30, step: float = 2.0):
    """
    Чекає появи готового клієнта з пулу (не busy, без кулдауна).
    Повертає slot або None після таймауту.
    """
    waited = 0.0
    while waited <= max_wait_sec:
        slots = iter_ready_pool_clients()
        slot = _RR.pick(slots)
        if slot:
            return slot
        await asyncio.sleep(step)
        waited += step
    return None


async def process_batch(
    *,
    batch_id: str,
    chat_id: int,
    reply_msg,
    admin_display: str,
    admin_username: Optional[str],
    admin_tg_id: Optional[int],
    raw_text: str,
):
    """
    Обробляє записані в link_queue URL для batch_id. Використовує один lease, якщо доступний.
    """
    db = SessionLocal()
    urls_rec = link_queue.fetch_batch_due(batch_id, limit=200)
    log.info("queue_worker.start batch_id=%s chat_id=%s urls=%s", batch_id, chat_id, len(urls_rec))
    if not urls_rec:
        await reply_msg.answer("Черга порожня або ще не готова.")
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

    def _register_preknown(key: str, data: Tuple[str, Optional[str], int, str, Optional[str]]):
        if not key:
            return
        preknown[key] = data
        preknown_urls.add(key)

    cnt_invite_need = 0
    cnt_public_need = 0

    for rec in urls_rec:
        _, url, *_ = rec
        try:
            cleaned = sanitize_link(url) or url
        except Exception:
            cleaned = url

        # Визначаємо тип
        inv_hash = _extract_invite_hash(url)
        # 1) find_channel_by_link (raw/clean)
        try:
            link_row = channel_db.find_channel_by_link(url) or channel_db.find_channel_by_link(cleaned)
            if link_row:
                cid_link, title_link = link_row
                final = any_final_for_channel(cid_link)
                if final:
                    final_norm = "already" if final == "joined" else final
                    if final_norm in FINAL_GLOBAL:
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
                    if final_norm in FINAL_GLOBAL:
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
                        if final_norm in FINAL_GLOBAL:
                            sess_known = get_any_session_for_channel(int(cid_cached))
                            data = (final_norm, title_cached, int(cid_cached), "invite_cache", sess_known)
                            _register_preknown(url, data)
                            if cleaned != url:
                                _register_preknown(cleaned, data)
                            continue
        except Exception:
            pass

        # Якщо сюди дійшли — мережа потрібна
        if inv_hash:
            cnt_invite_need += 1
        else:
            cnt_public_need += 1

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

        # Швидкий шлях: уже знаємо фінальний статус без мережі
        fast = preknown.get(url)
        if fast:
            base_status, title, cid, kind, sess = fast
            status_for_report = base_status
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
            continue
        slot = await _get_ready_slot()
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
            if status.startswith("flood_wait_"):
                try:
                    secs = int(status.split("_")[-1])
                except Exception:
                    secs = 0
                if secs:
                    mark_flood(client, secs)
            elif status == "too_many":
                mark_limit(client)
            else:
                bump_cooldown(client, 1)

            base_status = status or "unknown"
            status_display = f"{base_status}[{sess}]" if sess else base_status

            if cid is None:
                link_queue.mark_failed(item_id, base_status, backoff_sec=10)
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
        finally:
            slot.busy = False

    await progress.finish()

    # визначаємо індекс сторінки "Отчет" для кнопки
    footer, sections = build_full_footer(result_items, raw_lines=[raw_text])
    pages = []
    pages.extend(split_text_for_telegram(footer, max_len=3500))
    report_idx = None
    for label, text in sections:
        idx_before = len(pages)
        pages.extend(split_text_for_telegram(f"{label}:\n{text}", max_len=3500))
        if report_idx is None and label.startswith("Отчет"):
            report_idx = idx_before

    if pages:
        from admin_bot.bot.report_nav import make_report_kb
        from admin_bot.services import report_cache

        kb = make_report_kb(0, len(pages), has_report=report_idx is not None)
        sent = await reply_msg.answer(pages[0], disable_web_page_preview=True, reply_markup=kb)
        report_cache.register(sent.chat.id, sent.message_id, pages, report_idx)
        log.info(
            "queue_worker.report_sent batch_id=%s pages=%s report_idx=%s",
            batch_id,
            len(pages),
            report_idx,
        )
    db.close()
