from __future__ import annotations

import asyncio
from typing import List, Optional, Dict

from app.services import link_queue
from app.services.account_pool import (
    iter_ready_pool_clients,
    session_name,
    mark_flood,
    mark_limit,
    bump_cooldown,
)
from app.services.joiner import ensure_join
from admin_bot.services.channels import upsert_channel_full
from admin_bot.services.memberships import upsert_membership
from admin_bot.services.owner_conflicts import log_conflict
from admin_bot.services.report import split_text_for_telegram, build_full_footer
from admin_bot.services.progress import Progress
from admin_bot.db.session import SessionLocal
from admin_bot.services import admins as svc_admins
from admin_bot.services import networks as svc_networks


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


async def process_batch(
    *,
    batch_id: str,
    chat_id: int,
    reply_msg,
    admin_id: int,
    owner_display: Optional[str],
    owner_username: Optional[str],
    raw_text: str,
):
    """
    Обробляє записані в link_queue URL для batch_id. Використовує один lease, якщо доступний.
    """
    db = SessionLocal()
    urls_rec = link_queue.fetch_batch_due(batch_id, limit=200)
    if not urls_rec:
        await reply_msg.answer("Черга порожня або ще не готова.")
        db.close()
        return

    total = len(urls_rec)
    progress = Progress(reply_msg, total=total)
    await progress.start()

    result_items: List[Dict] = []
    for idx, rec in enumerate(urls_rec, start=1):
        item_id, url, tries, origin_chat, origin_msg, od, ou = rec
        slots = iter_ready_pool_clients()
        slot = _RR.pick(slots)
        if slot is None:
            # немає готових акаунтів — залишаємо цей і решту в черзі
            pending = urls_rec[idx - 1 :]
            for j, pend in enumerate(pending, start=idx):
                _, purl, *_ = pend
                result_items.append({"idx": j, "url": purl, "title": None, "status": "no_client", "channel_id": None})
                await progress.update("no_client", purl, None)
            await progress.finish()
            db.close()
            return

        client = slot.client
        sess = session_name(client)
        slot.busy = True
        try:
            link_queue.mark_processing(item_id)
            try:
                status, title, kind, cid, invite_hash = await ensure_join(client, url)
            except Exception as e:
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
                bump_cooldown(client, 2)

            base_status = status or "unknown"
            status_display = f"{base_status}[{sess}]" if sess else base_status

            if cid is None:
                link_queue.mark_failed(item_id, base_status, backoff_sec=10)
                result_items.append({"idx": idx, "url": url, "title": title, "status": status_display, "channel_id": None})
                await progress.update(status_display, title or url, sess)
                continue

            upsert_channel_full(
                db,
                channel_id=cid,
                username=None,
                title=title,
                owner_display=owner_display,
                owner_username=owner_username,
                last_status=base_status,
            )
            ch = svc_admins.ensure_channel(db, channel_id=cid, username=None, title=title)
            link_res = svc_admins.attach_channel(db, admin_id=admin_id, channel_id=ch.channel_id)
            svc_networks.move_orphans_to_primary(db, admin_id)

            status_for_report = base_status
            if link_res.get("status") == "conflict":
                other_id = link_res.get("admin_id")
                other = svc_admins.get_admin_by_id(db, other_id) if other_id else None
                other_name = (other.display or f"@{other.username}") if other else str(other_id)
                status_for_report = f"owner_conflict(existing={other_name})"
                log_conflict(db, channel_id=cid, owner=other_name or "unknown", source_ref=url)

            upsert_membership(db, channel_id=cid, account=sess or "", status=base_status)
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
    db.close()
