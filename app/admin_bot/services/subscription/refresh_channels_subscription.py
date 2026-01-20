from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple
from types import SimpleNamespace

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.session import session_scope
from app.db import models as m
from app.admin_bot.services import report_cache
from app.admin_bot.services.subscription import batch_cache
from app.admin_bot.services import admins as svc_admins
from app.admin_bot.services.subscription.subscription_report import answer_with_retry
from app.admin_bot.services.subscription.subscription_menu import split_text_for_telegram
from app.admin_bot.services.subscription.subscription_worker import process_batch
from app.admin_bot.services.subscription.keyboards import (
    make_report_keyboard,
    build_confirm_unsubscribe_rows,
    build_confirm_unsubscribe_keyboard,
)
from app.services import link_queue
from app.services import account_pool
from app.DAL import channels_operations as cho
from app.DAL import membership_operations as mem_db
from app.DAL import network_channels_operations as net_db
from app.DAL.refresh_links_operation import (
    BatchResultDTO,
    RefreshPlanDTO,
    build_batch_results,
    build_refresh_plan,
    invite_cache_status_get_bulk,
    bulk_memberships_accounts,
    bulk_any_session,
    bulk_owner_conflict,
    bulk_channel_title_owner,
    bulk_admin_for_channels,
    bulk_channel_link_meta,
)
from app.DAL.admins_operations import AdminSnapshot
from app.utils.link_parser import sanitize_link
from app.admin_bot.services.subscription.subscription_utils import norm_keys as collect_norm_keys

log = logging.getLogger("admin_bot.services.subscription.refresh_channels")

_PENDING_REFRESH_CONFIRMATIONS: Dict[str, Dict] = {}


@dataclass(frozen=True)
class RefreshContext:
    batch_id: str
    chat_id: int
    reply_msg: Any
    admin: AdminSnapshot
    urls: List[str]
    raw_text: str
    raw_html: str
    entities: List


@dataclass(frozen=True)
class RefreshPhaseData:
    plan: RefreshPlanDTO
    enriched_results: List[BatchResultDTO]
    removed_link_map: Dict[int, Tuple[Optional[str], Optional[str]]]
    removed_sessions: Dict[int, Set[str]]
    no_cid_resolution: bool


def _load_current_channel_ids(admin_id: int) -> Set[int]:
    with session_scope() as db:
        current_channel_ids = set(cho.list_admin_channel_ids(db, admin_id))
        network_channel_ids = net_db.list_channel_ids_for_admin_networks(db, admin_id)
        if network_channel_ids:
            current_channel_ids |= set(network_channel_ids)
    return current_channel_ids


def _prepare_refresh_phase_data(
    batch_id: str,
    urls: List[str],
    current_channel_ids: Set[int],
    admin: AdminSnapshot,
) -> RefreshPhaseData:
    with session_scope() as db:
        cache_entry = batch_cache.pop(batch_id) or {}
        cached_items = cache_entry.get("items") or []
        batch_results: List[BatchResultDTO] = build_batch_results(urls, cached_items)

        url_keys: Set[str] = set()
        for batch_result in batch_results:
            for norm_key in collect_norm_keys(batch_result.clean_url) + collect_norm_keys(batch_result.original_url):
                if norm_key:
                    url_keys.add(norm_key)

        channel_ids = [batch_result.channel_id for batch_result in batch_results if batch_result.channel_id is not None]
        status_by_url = invite_cache_status_get_bulk(db, list(url_keys))
        titles_map = bulk_channel_title_owner(db, channel_ids)
        admin_map = bulk_admin_for_channels(db, channel_ids)
        conflict_map = bulk_owner_conflict(db, channel_ids)
        membership_accounts = bulk_memberships_accounts(db, channel_ids)
        session_hint_map = bulk_any_session(db, channel_ids)

        conflict_clear_channel_ids: Set[int] = set()
        enriched_results: List[BatchResultDTO] = []
        for batch_result in batch_results:
            status_raw = (
                batch_result.status_raw
                or status_by_url.get(batch_result.clean_url)
                or status_by_url.get(batch_result.original_url)
            )
            title = (
                batch_result.title
                or (titles_map.get(int(batch_result.channel_id)) if batch_result.channel_id is not None else None)
            )
            session_hint = (
                batch_result.session_hint
                or (session_hint_map.get(int(batch_result.channel_id)) if batch_result.channel_id is not None else None)
            )

            if batch_result.channel_id:
                channel_id_int = int(batch_result.channel_id)
                conflict_reason = conflict_map.get(channel_id_int)
                assigned_admin_id = admin_map.get(channel_id_int)
                conflict_clear = False

                if conflict_reason:
                    existing_owner = conflict_reason.strip()
                    if existing_owner and existing_owner.lower() in ("unknown", "невідомий адмін"):
                        existing_owner = None
                    conflict_with = existing_owner
                    if conflict_with and admin.id and assigned_admin_id == admin.id:
                        conflict_clear = True
                        conflict_with = None
                    if conflict_with:
                        status_raw = f"owner_conflict(existing={conflict_with})"
                elif assigned_admin_id and admin.id and assigned_admin_id != admin.id:
                    status_raw = f"owner_conflict(existing={assigned_admin_id})"

                membership_accounts_for_channel = membership_accounts.get(channel_id_int) or set()
                first_membership = next(iter(membership_accounts_for_channel), None)
                if first_membership:
                    if not session_hint:
                        session_hint = str(first_membership)
                    if not status_raw:
                        status_raw = "already"
                    elif "joined" in (status_raw or "").lower() and "already" not in (status_raw or "").lower():
                        status_raw = "already"
                if not session_hint:
                    session_hint = session_hint_map.get(channel_id_int)

                if conflict_clear:
                    conflict_clear_channel_ids.add(channel_id_int)

            enriched_results.append(
                BatchResultDTO(
                    original_url=batch_result.original_url,
                    clean_url=batch_result.clean_url,
                    channel_id=batch_result.channel_id,
                    title=title,
                    status_raw=status_raw,
                    session_hint=session_hint,
                )
            )

        if conflict_clear_channel_ids:
            try:
                mem_db.owner_conflict_delete_by_channels(db, list(conflict_clear_channel_ids))
                db.commit()
            except Exception:
                db.rollback()

        plan = build_refresh_plan(set(current_channel_ids), enriched_results)
        planned_keep_ids = set(plan.keep_cids)
        planned_to_remove = set(plan.to_remove)
        planned_order = list(plan.to_remove_order)
        no_cid_resolution = False
        if not planned_keep_ids:
            no_cid_resolution = True
            planned_keep_ids = set(current_channel_ids)
            planned_to_remove = set()
            planned_order = []
        if planned_to_remove and not planned_order:
            planned_order = [cid for cid in current_channel_ids if cid in planned_to_remove]
            for cid in planned_to_remove:
                if cid not in planned_order:
                    planned_order.append(cid)

        final_plan = RefreshPlanDTO(
            keep_cids=planned_keep_ids,
            to_remove=planned_to_remove,
            to_remove_order=planned_order,
            items=list(enriched_results),
        )

        removed_link_map: Dict[int, Tuple[Optional[str], Optional[str]]] = {}
        removed_sessions: Dict[int, Set[str]] = {}
        if planned_to_remove:
            ordered_remove = planned_order if planned_order else list(planned_to_remove)
            meta_map = bulk_channel_link_meta(db, ordered_remove)
            for channel_id, meta in meta_map.items():
                if not meta:
                    continue
                title, href = meta
                if href and href.startswith("http"):
                    try:
                        href = sanitize_link(href) or href
                    except Exception:
                        href = href
                removed_link_map[int(channel_id)] = (title, href)
            for channel_id in planned_to_remove:
                session_set = membership_accounts.get(int(channel_id)) or set()
                if session_set:
                    removed_sessions[int(channel_id)] = set(session_set)

        return RefreshPhaseData(
            plan=final_plan,
            enriched_results=enriched_results,
            removed_link_map=removed_link_map,
            removed_sessions=removed_sessions,
            no_cid_resolution=no_cid_resolution,
        )


def _empty_cleanup_stats() -> Dict[str, int]:
    return {
        "left_total": 0,
        "leave_errors": 0,
        "admin_channels_deleted": 0,
        "network_channels_deleted": 0,
        "membership_deleted": 0,
        "membership_status_deleted": 0,
        "owner_conflicts_deleted": 0,
        "links_deleted": 0,
        "url_cache_deleted": 0,
        "channels_deleted": 0,
        "link_queue_deleted": 0,
    }


def _resolve_channel_id(url: str) -> Optional[int]:
    """
    Визначає channel_id за URL/інвайтом, використовуючи кеш links/invite_cache.
    """
    if not url:
        return None
    try:
        clean = sanitize_link(url) or url
    except Exception:
        clean = url

    for candidate in (url, clean):
        if not candidate:
            continue
        with session_scope() as db:
            row = cho.find_channel_by_link(db, candidate)
            if row and row.channel_id:
                return row.channel_id
            cid = cho.get_channel_id_by_url(db, candidate)
            if cid:
                return cid
            cid_map_title = mem_db.map_invite_get(db, candidate)
            if cid_map_title:
                cid_map, _title = cid_map_title
                if cid_map:
                    return cid_map
    return None


async def _cleanup_removed_channels(admin: AdminSnapshot, chan_ids: Set[int]) -> Dict[str, int]:
    """
    Відписує сесії від каналів та чистить пов’язані таблиці для каналів, які більше не потрібні цьому адміна.
    """
    stats = _empty_cleanup_stats()
    if not chan_ids:
        return stats

    # Phase 1: gather data (DB-only)
    acct_map: Dict[str, Set[int]] = {}
    net_ids: List[int] = []
    delete_ids: List[int] = []
    urls_for_cleanup: List[str] = []
    pre_count = 0
    with session_scope() as db:
        memberships = mem_db.list_memberships_for_channels(db, list(chan_ids))
        for mbr in memberships:
            acct_map.setdefault(mbr.account, set()).add(mbr.channel_id)

        stats["admin_channels_deleted"] = cho.delete_admin_channels(db, admin.id, list(chan_ids))
        net_ids = net_db.list_network_ids_for_admin(db, admin.id)
        if net_ids:
            stats["network_channels_deleted"] = net_db.delete_network_channels_by_networks(
                db, net_ids, list(chan_ids)
            )
        db.commit()

        keep_ids = set(cho.list_all_admin_channel_ids(db)) | set(net_db.list_channel_ids_for_admin_networks(db, admin.id))
        delete_ids = [cid for cid in chan_ids if cid not in keep_ids]

        if delete_ids:
            raw_urls = cho.raw_urls_for_channels(db, delete_ids)
            for u in raw_urls:
                urls_for_cleanup.extend(svc_admins._expand_url_variants(u))  # type: ignore[attr-defined]
            pre_count = svc_admins._count_url_cache(urls_for_cleanup, db) if urls_for_cleanup else 0  # type: ignore[attr-defined]

    # Phase 2: async-only (leave channels)
    for acct, cids in acct_map.items():
        stat = await account_pool.leave_channels(acct, list(cids))
        stats["left_total"] += stat.get("left", 0) or 0
        stats["leave_errors"] += stat.get("errors", 0) or 0

    # Phase 3: apply deletes/cleanup (DB-only)
    with session_scope() as db:
        if delete_ids:
            stats["membership_deleted"] = m.delete_memberships_by_channels(db, delete_ids)
            stats["membership_status_deleted"] = m.delete_membership_status_by_channels(db, delete_ids)
            stats["owner_conflicts_deleted"] = m.delete_owner_conflict_by_channels(db, delete_ids)
            stats["links_deleted"] = m.delete_links_by_channels(db, delete_ids)
            try:
                stats["invite_cache_deleted"] = mem_db.invite_cache_delete_by_channels(db, delete_ids)
            except Exception:
                stats["invite_cache_deleted"] = 0

            try:
                stats["url_cache_deleted"] = svc_admins._delete_url_cache_db(db, urls_for_cleanup, ["already", "joined"])  # type: ignore[attr-defined]
            except Exception:
                stats["url_cache_deleted"] = 0
            if pre_count > 0 and stats["url_cache_deleted"] == 0:
                try:
                    stats["url_cache_deleted"] = svc_admins._delete_url_cache_db(db, urls_for_cleanup, None)  # type: ignore[attr-defined]
                except Exception:
                    pass
            stats["channels_deleted"] = m.delete_channels_by_ids(db, delete_ids)
        db.commit()

    # Phase 4: cleanup link_queue (separate sqlite access)
    try:
        stats["link_queue_deleted"] = link_queue.delete_by_owner(
            owner_admin_id=admin.id,
            owner_username=admin.username,
            urls=list(set(urls_for_cleanup)) if urls_for_cleanup else None,
        )
    except Exception:
        stats["link_queue_deleted"] = 0
    return stats


def _format_removed_lines(
    *,
    to_remove: List[int],
    removed_link_map: Dict[int, tuple[Optional[str], Optional[str]]],
    removed_sessions: Dict[int, Set[str]],
    action_text: str,
    db=None,
) -> List[str]:
    lines = []
    for cid in to_remove:
        title, href = removed_link_map.get(cid, (None, None))
        if not title and db is not None:
            info = cho.get_channel_title_and_owner(db, cid)
            title = info.title if info else None
        title_txt = title or f"channel_id={cid}"
        sess_txt = ""
        sess_set = removed_sessions.get(cid) or set()
        if sess_set:
            sess_txt = " [" + ", ".join(account_pool.session_display(s) for s in sorted(sess_set)) + "]"
        if href:
            lines.append(f'• <a href="{href}">{title_txt}</a> — {action_text}{sess_txt}')
        else:
            lines.append(f"• {title_txt} (ID: {cid}) — {action_text}{sess_txt}")
    return lines


async def _send_refresh_report(
    *,
    admin: AdminSnapshot,
    reply_msg,
    status_lines: List[str],
    to_remove: Set[int],
    to_remove_order: Optional[List[int]],
    removed_link_map: Dict[int, tuple[Optional[str], Optional[str]]],
    removed_sessions: Dict[int, Set[str]],
    perform_cleanup: bool,
    db=None,
) -> None:
    stats = _empty_cleanup_stats()
    if perform_cleanup and to_remove:
        stats = await _cleanup_removed_channels(admin, to_remove)

    lines = list(status_lines)

    if to_remove:
        if perform_cleanup:
            lines.append("")
            lines.append("Отписались от каналов:")
            lines.extend(
                _format_removed_lines(
                    to_remove=to_remove_order if to_remove_order else list(to_remove),
                    removed_link_map=removed_link_map,
                    removed_sessions=removed_sessions,
                    action_text="Отписались",
                    db=db,
                )
            )
        else:
            lines.append("")
            lines.append("Відписка скасована — канали залишились закріпленими:")
            lines.extend(
                _format_removed_lines(
                    to_remove=to_remove_order if to_remove_order else list(to_remove),
                    removed_link_map=removed_link_map,
                    removed_sessions=removed_sessions,
                    action_text="Залишились",
                    db=db,
                )
            )
    else:
        lines.append("")
        lines.append("Отписались от каналов: —")

    lines.append("")
    lines.append(
        f"Отписка left={stats['left_total']} errors={stats['leave_errors']}"
    )
    lines.append(
        "БД: "
        f"channels {stats['channels_deleted']}, memberships {stats['membership_deleted']}, membership_status {stats['membership_status_deleted']}; "
        f"owner_conflicts {stats['owner_conflicts_deleted']}; "
        f"links {stats['links_deleted']}, url_cache {stats['url_cache_deleted']}, link_queue {stats['link_queue_deleted']}"
    )

    text_full = "\n".join(lines)
    pages = split_text_for_telegram(text_full, max_len=5000)
    if len(pages) == 1:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ До адміна", callback_data=f"admin_back:{admin.id}")]]
        )
        await answer_with_retry(
            reply_msg,
            pages[0],
            disable_web_page_preview=True,
            reply_markup=kb,
            parse_mode="HTML",
        )
    else:
        kb = make_report_keyboard(0, len(pages), has_report=False)
        sent = await answer_with_retry(
            reply_msg,
            pages[0],
            disable_web_page_preview=True,
            parse_mode="HTML",
            reply_markup=kb,
        )
        if sent:
            report_cache.register(sent.chat.id, sent.message_id, pages, None)  # type: ignore[name-defined]


async def refresh_channels_for_admin(refresh_context: RefreshContext) -> None:
    """
    Оновлює список каналів адміна:
    1) підписує/оновлює за новими URL (process_batch)
    2) визначає канал_id із нових URL
    3) відписує та чистить канали, що не потрапили до нового списку.
    """
    admin_obj = refresh_context.admin
    if isinstance(admin_obj, m.Admin):
        admin = AdminSnapshot(
            id=admin_obj.id,
            username=admin_obj.username,
            display=admin_obj.display,
            tg_id=admin_obj.tg_id,
        )
    else:
        admin = admin_obj

    current_channel_ids = _load_current_channel_ids(admin.id)

    link_queue.enqueue(
        refresh_context.urls,
        batch_id=refresh_context.batch_id,
        origin_chat=refresh_context.chat_id,
        origin_msg=getattr(refresh_context.reply_msg, "message_id", None),
        owner_admin_id=admin.id,
        owner_username=admin.username,
        adopt_existing=True,
        reset_next_try=True,
    )
    allowed_markers = (
        "Додано у чергу",
        "Орієнтовний час підписки",
        "Пакет каналов",
        "Пакет посилан",
        "Прогресс подписки",
        "Список каналів",
        "Обновление списка каналов",
    )

    class _FilteredBot:
        def __init__(self, real_bot):
            self._bot = real_bot

        async def send_message(self, chat_id, text, *args, **kwargs):
            if any(marker in str(text) for marker in allowed_markers):
                return await self._bot.send_message(chat_id, text, *args, **kwargs)
            return SimpleNamespace(message_id=None, chat=SimpleNamespace(id=chat_id))

        async def edit_message_text(self, *args, **kwargs):
            text = kwargs.get("text") or (args[2] if len(args) > 2 else "")
            if any(marker in str(text) for marker in allowed_markers):
                return await self._bot.edit_message_text(*args, **kwargs)
            return None

        def __getattr__(self, item):
            return getattr(self._bot, item)

    class _FilteredMessage:
        def __init__(self, original_message):
            self._original_message = original_message
            self.bot = _FilteredBot(original_message.bot)
            self.chat = original_message.chat
            self.message_id = getattr(original_message, "message_id", None)

        async def answer(self, text, *args, **kwargs):
            if any(marker in str(text) for marker in allowed_markers):
                return await self._original_message.answer(text, *args, **kwargs)
            return SimpleNamespace(message_id=None, chat=self.chat)

    filtered_msg = _FilteredMessage(refresh_context.reply_msg)

    def _human_status(raw: Optional[str], session_hint: Optional[str] = None) -> str:
        if not raw:
            return "…"
        normalized = raw.lower()
        base = raw
        session_value = None
        if "[" in raw and raw.endswith("]"):
            session_value = raw[raw.rfind("[") + 1 : -1]
            base = raw[: raw.rfind("[")].strip()
        if "owner_conflict" in normalized:
            conflict_with = None
            try:
                conflict_with = re.search(r"owner_conflict\(existing=([^)]+)\)", base, re.IGNORECASE).group(1)  # type: ignore[arg-type]
            except Exception:
                conflict_with = None
            human = "⚠️ Конфликт"
            if conflict_with:
                human = f"⚠️ Конфликт (закреплен за {conflict_with})"
        elif "requested" in normalized or "заявк" in normalized:
            human = "✉️ Заявка"
        elif "duplicate" in normalized:
            human = "🔁 Дубликат"
        elif "joined" in normalized:
            human = "✅ Подписался"
        elif "already" in normalized:
            human = "☑️ Был подписан"
        elif "flood" in normalized:
            human = "⏳ Флуд"
        elif any(token in normalized for token in ("invalid", "private", "error", "blocked", "too_many")):
            human = "❌ Невалидное"
        else:
            human = base or "…"
        if session_value:
            human = f"{human} [{account_pool.session_display(session_value)}]"
        elif session_hint:
            human = f"{human} [{account_pool.session_display(session_hint)}]"
        return human

    await process_batch(
        batch_id=refresh_context.batch_id,
        chat_id=refresh_context.chat_id,
        reply_msg=filtered_msg,
        admin_id=admin.id,
        admin_display=admin.display,
        admin_username=admin.username,
        admin_tg_id=admin.tg_id,
        raw_text=refresh_context.raw_text,
        raw_html=refresh_context.raw_html,
        entities=refresh_context.entities,
        original_urls=refresh_context.urls,
    )

    phase_data = _prepare_refresh_phase_data(
        refresh_context.batch_id,
        refresh_context.urls,
        current_channel_ids,
        admin,
    )

    if not phase_data.plan.keep_cids:
        await answer_with_retry(
            refresh_context.reply_msg,
            "Не вдалося визначити канали за надісланими посиланнями — видалення пропущено.",
        )
        return

    status_lines: List[str] = ["📋 Обновление списка каналов"]
    if phase_data.no_cid_resolution:
        status_lines.append(
            "⚠️ Не вдалося визначити channel_id за новими посиланнями; відписка пропущена, показуємо статуси за кешем."
        )

    for idx, batch_result in enumerate(phase_data.enriched_results, start=1):
        human_status = _human_status(batch_result.status_raw, batch_result.session_hint)
        title_text = batch_result.title or batch_result.clean_url or batch_result.original_url or "невідомо"
        href = batch_result.clean_url or batch_result.original_url
        status_lines.append(f'{idx}. <a href="{href}">{title_text}</a> — {human_status}')

    to_remove = set(phase_data.plan.to_remove)
    to_remove_order = list(phase_data.plan.to_remove_order)
    if not to_remove_order and to_remove:
        to_remove_order = list(to_remove)

    removed_link_map = phase_data.removed_link_map
    removed_sessions = phase_data.removed_sessions

    if to_remove:
        _PENDING_REFRESH_CONFIRMATIONS.pop(refresh_context.batch_id, None)
        _PENDING_REFRESH_CONFIRMATIONS[refresh_context.batch_id] = {
            "admin_id": admin.id,
            "status_lines": list(status_lines),
            "to_remove": set(to_remove),
            "to_remove_order": list(to_remove_order),
            "removed_link_map": removed_link_map,
            "removed_sessions": removed_sessions,
        }

        preview_lines = [
            "Знайшли канали, яких немає у новому списку. Відписати від них?",
            "",
        ]
        preview_lines.extend(
            _format_removed_lines(
                to_remove=to_remove_order if to_remove_order else list(to_remove),
                removed_link_map=removed_link_map,
                removed_sessions=removed_sessions,
                action_text="Потенційна відписка",
                db=None,
            )
        )
        preview_lines.append("")
        preview_lines.append("Підтвердити відписку?")
        confirm_rows = build_confirm_unsubscribe_rows(refresh_context.batch_id)
        preview_keyboard = build_confirm_unsubscribe_keyboard(refresh_context.batch_id)
        text_preview = "\n".join(preview_lines)
        preview_pages = split_text_for_telegram(text_preview, max_len=5000)

        if len(preview_pages) == 1:
            await answer_with_retry(
                refresh_context.reply_msg,
                preview_pages[0],
                disable_web_page_preview=True,
                reply_markup=preview_keyboard,
                parse_mode="HTML",
            )
        else:
            keyboard = make_report_keyboard(0, len(preview_pages), has_report=False, extra_rows=confirm_rows)
            sent = await answer_with_retry(
                refresh_context.reply_msg,
                preview_pages[0],
                disable_web_page_preview=True,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            if sent:
                report_cache.register(sent.chat.id, sent.message_id, preview_pages, None, confirm_rows)
        return

    await _send_refresh_report(
        admin=admin,
        reply_msg=refresh_context.reply_msg,
        status_lines=status_lines,
        to_remove=to_remove,
        to_remove_order=to_remove_order,
        removed_link_map=removed_link_map,
        removed_sessions=removed_sessions,
        perform_cleanup=True,
        db=None,
    )
    return

async def finalize_refresh_confirmation(batch_id: str, approve_unsubscribe: bool, reply_msg) -> None:
    """
    Завершує оновлення каналів після відповіді на підтвердження відписки.
    """
    ctx = _PENDING_REFRESH_CONFIRMATIONS.pop(batch_id, None)
    if not ctx:
        await answer_with_retry(reply_msg, "Не знайшов дані для цього запиту. Спробуй запустити оновлення ще раз.")
        return

    admin_id = ctx.get("admin_id")
    admin = None
    if admin_id:
        with session_scope() as db:
            admin = svc_admins.get_admin_snapshot_by_id(db, admin_id)

    if not admin:
        await answer_with_retry(reply_msg, "Адміна не знайдено. Спробуй запустити оновлення ще раз.")
        return

    await _send_refresh_report(
        admin=admin,
        reply_msg=reply_msg,
        status_lines=ctx.get("status_lines") or [],
        to_remove=set(ctx.get("to_remove") or []),
        to_remove_order=ctx.get("to_remove_order"),
        removed_link_map=ctx.get("removed_link_map") or {},
        removed_sessions=ctx.get("removed_sessions") or {},
        perform_cleanup=approve_unsubscribe,
        db=None,
    )
