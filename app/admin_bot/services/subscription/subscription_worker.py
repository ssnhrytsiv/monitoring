from __future__ import annotations

import asyncio
import logging
import math
import re
from typing import List, Optional, Dict, Tuple

from sqlalchemy import select
from aiogram.exceptions import TelegramRetryAfter, TelegramServerError

from app.admin_bot.services import report_cache
from app.services import link_queue
from app.services.account_pool import mark_flood, mark_limit, bump_cooldown, session_name
from app.services.joiner import ensure_join, _extract_invite_hash
from app.DAL.membership_operations import MembershipDAO, FINAL_GLOBAL
from app.admin_bot.services.subscription.subscription_for_bot import ensure_bot_started
from app.utils.throttle import LINK_DELAY_INVITE_MAX, LINK_DELAY_PUBLIC_MAX
from app.utils.link_parser import sanitize_link, extract_bot_username
from app.admin_bot.services.channels import upsert_channel_full
from app.admin_bot.db.models import upsert_membership
from app.admin_bot.services.owner_conflicts import log_conflict
from app.admin_bot.services.subscription.subscription_menu import split_text_for_telegram, make_report_kb
from app.admin_bot.services.subscription import batch_cache
from app.admin_bot.services.progress import Progress
from app.admin_bot.services import admins as svc_admins
from app.admin_bot.services import networks as svc_networks
from app.admin_bot.db.session import SessionLocal
from app.admin_bot.db import models as m
from app.DAL import channel_session_assignment_operations as assignment_ops
from app.DAL import channel_subscription_audit_operations as audit_ops
from app.admin_bot.services.subscription.subscription_slots_pool import get_ready_slot
from app.admin_bot.services.subscription.subscription_status import normalize_url, render_html_with_statuses
from app.admin_bot.services.subscription.subscription_report import answer_with_retry
from app.admin_bot.services.subscription.subscription_utils import norm_keys as collect_norm_keys
from app.services.channel_session_cleanup import enforce_single_session_per_channel
from app.logging_json import get_logger, configure_logging
from app.DAL import channels_operations as cho
from app.DAL import requested_operations as requested_checks_db
from app.DAL.membership_operations import _extract_invite_hash

# Гарантований мінімальний логер (на випадок, якщо головний процес не налаштував logging).
if not logging.getLogger().handlers:
    configure_logging()

log = get_logger("admin_bot.queue_worker")

_INVITE_STUB_RE = re.compile(r"^https?://t\\.me/(?:joinchat/?)?(?:\\+)?$")


def _find_channel_by_link(url: str, cleaned: Optional[str] = None):
    db = SessionLocal()
    try:
        row = cho.find_channel_by_link(db, url)
        if not row and cleaned and cleaned != url:
            row = cho.find_channel_by_link(db, cleaned)
        return row
    finally:
        db.close()


def _get_channel_id_by_url(url: str, cleaned: Optional[str] = None):
    db = SessionLocal()
    try:
        cid = cho.get_channel_id_by_url(db, url)
        if not cid and cleaned and cleaned != url:
            cid = cho.get_channel_id_by_url(db, cleaned)
        return cid
    finally:
        db.close()


def _add_link(channel_id, raw_url, kind, batch_msg_id, owner_display, owner_username):
    db = SessionLocal()
    try:
        cho.add_link(db, channel_id, raw_url, kind, batch_msg_id, owner_display, owner_username)
    finally:
        db.close()


def _resolve_assignment_admin_identifier(
    *,
    admin_id: Optional[int],
    other_owner_id: Optional[int],
) -> Optional[int]:
    if other_owner_id is not None:
        return int(other_owner_id)
    if admin_id is not None:
        return int(admin_id)
    return None


def _maybe_upsert_channel_session_assignment(
    *,
    channel_id: Optional[int],
    session_name_value: Optional[str],
    base_status: str,
    admin_id: Optional[int],
    other_owner_id: Optional[int],
    assignment_source: str,
    skip_assignment: bool,
) -> None:
    if skip_assignment:
        return
    if base_status not in ("joined", "already"):
        return
    if channel_id is None or not session_name_value:
        return

    assignment_admin_id = _resolve_assignment_admin_identifier(
        admin_id=admin_id,
        other_owner_id=other_owner_id,
    )
    try:
        assignment_ops.upsert_channel_session_assignment(
            channel_id=int(channel_id),
            session_name=session_name_value,
            admin_id=assignment_admin_id,
            assignment_source=assignment_source,
        )
    except Exception:
        log.exception(
            "queue_worker.assignment_upsert_failed cid=%s sess=%s status=%s source=%s",
            channel_id,
            session_name_value,
            base_status,
            assignment_source,
        )


def _should_bypass_positive_cache(channel_id: Optional[int]) -> bool:
    if channel_id is None:
        return False
    try:
        return audit_ops.should_bypass_positive_channel_cache(int(channel_id))
    except Exception:
        log.debug(
            "queue_worker.audit_positive_cache_check_failed cid=%s",
            channel_id,
            exc_info=True,
        )
        return False


def _get_effective_session_hint(
    channel_id: Optional[int],
    membership_db: MembershipDAO,
) -> Optional[str]:
    if channel_id is None:
        return None
    try:
        assigned_session_name = assignment_ops.get_assigned_session_for_channel(
            int(channel_id)
        )
        if assigned_session_name:
            return assigned_session_name
    except Exception:
        log.debug(
            "queue_worker.assignment_session_hint_failed cid=%s",
            channel_id,
            exc_info=True,
        )
    if _should_bypass_positive_cache(channel_id):
        return None
    try:
        return membership_db.get_session_by_channel(int(channel_id))
    except Exception:
        log.debug(
            "queue_worker.membership_session_hint_failed cid=%s",
            channel_id,
            exc_info=True,
        )
        return None


def _resolve_repair_preferred_session(
    channel_id: Optional[int],
    preferred_session_name: Optional[str],
) -> Optional[str]:
    if channel_id is None or not _should_bypass_positive_cache(channel_id):
        return preferred_session_name
    try:
        assigned_session_name = assignment_ops.get_assigned_session_for_channel(
            int(channel_id)
        )
        if assigned_session_name:
            return assigned_session_name
    except Exception:
        log.debug(
            "queue_worker.repair_preferred_session_lookup_failed cid=%s",
            channel_id,
            exc_info=True,
        )
    return preferred_session_name


def _should_use_url_cache_status(
    *,
    status_norm: Optional[str],
    channel_id: Optional[int],
) -> bool:
    if not status_norm:
        return False
    # duplicate — це локальний дедуп-артефакт, а не стабільний кеш каналу.
    # Його не можна використовувати між батчами, інакше той самий лінк
    # блокує repair для missing-каналу.
    if status_norm == "duplicate":
        return False
    if status_norm not in FINAL_GLOBAL or status_norm == "requested":
        return False
    if status_norm == "already" and _should_bypass_positive_cache(channel_id):
        return False
    return True


def _refresh_audit_after_success(
    *,
    channel_id: Optional[int],
    base_status: str,
    present_session_name: Optional[str],
    audit_reason: str,
) -> None:
    if base_status not in ("joined", "already"):
        return
    if channel_id is None or not present_session_name:
        return
    try:
        audit_ops.refresh_channel_subscription_audit_for_channel(
            int(channel_id),
            present_session_name_list=[present_session_name],
            audit_reason=audit_reason,
        )
    except Exception:
        log.exception(
            "queue_worker.audit_refresh_after_success_failed cid=%s status=%s sess=%s reason=%s",
            channel_id,
            base_status,
            present_session_name,
            audit_reason,
        )


def _repair_missing_channel_session_binding(
    *,
    channel_id: Optional[int],
    current_session_name: Optional[str],
    membership_db: MembershipDAO,
) -> bool:
    if channel_id is None or not current_session_name:
        return False
    try:
        is_missing_channel = audit_ops.should_bypass_positive_channel_cache(int(channel_id))
    except Exception:
        log.debug(
            "queue_worker.audit_missing_check_failed cid=%s",
            channel_id,
            exc_info=True,
        )
        return False
    if not is_missing_channel:
        return False

    return True


def _resolve_success_session_binding(
    *,
    channel_id: Optional[int],
    base_status: str,
    current_session_name: Optional[str],
    membership_db: MembershipDAO,
) -> Tuple[bool, Optional[str]]:
    if base_status not in ("joined", "already"):
        return False, current_session_name
    if channel_id is None or not current_session_name:
        return False, current_session_name

    repaired_missing_channel = _repair_missing_channel_session_binding(
        channel_id=channel_id,
        current_session_name=current_session_name,
        membership_db=membership_db,
    )
    if repaired_missing_channel:
        return False, current_session_name

    skip_membership = False
    audit_present_session_name = current_session_name
    if base_status == "already":
        try:
            sess_known = _get_effective_session_hint(channel_id, membership_db)
            if sess_known and sess_known != current_session_name:
                skip_membership = True
                audit_present_session_name = sess_known
                log.debug(
                    "queue_worker.skip_membership_other_session cid=%s sess=%s other=%s",
                    channel_id,
                    current_session_name,
                    sess_known,
                )
        except Exception:
            pass
    return skip_membership, audit_present_session_name


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
    forced_session_name: Optional[str] = None,
):
    """
    Обробляє записані в link_queue URL для batch_id. Використовує один lease, якщо доступний.
    """
    db = SessionLocal()
    membership_db = MembershipDAO(db)
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

    # Попередня перевірка: якщо URL уже відомий у links (DAO) і є фінальний статус у membership_db,
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
        resolved_channel_identifier_for_cache: Optional[int] = None

        # Визначаємо тип
        inv_hash = _extract_invite_hash(url)
        # Відсікаємо "порожні" інвайт-лінки без хеша (t.me/joinchat або t.me/+)
        if not inv_hash:
            try:
                from urllib.parse import urlsplit
                p = urlsplit(cleaned)
                path = p.path.strip("/").lower()
                if _INVITE_STUB_RE.match(cleaned) or path.startswith("joinchat") or path.startswith("+"):
                    data = ("invalid", None, None, "invalid_invite_stub", None)
                    _register_preknown(url, data)
                    if cleaned != url:
                        _register_preknown(cleaned, data)
                    continue
            except Exception:
                # Якщо парсинг упав, продовжуємо поточну логіку
                pass

        preferred_session: Optional[str] = forced_session_name
        if inv_hash and not preferred_session:
            try:
                preferred_session = membership_db.invite_check_last_session(inv_hash)
            except Exception:
                preferred_session = None
        # 1) find_channel_by_link (raw/clean)
        try:
            link_row = _find_channel_by_link(url, cleaned)
            if link_row:
                cid_link, title_link = link_row
                if cid_link is not None:
                    resolved_channel_identifier_for_cache = int(cid_link)
                final = membership_db.any_final_for_channel(cid_link)
                if final:
                    final_norm = "already" if final == "joined" else final
                    if final_norm in FINAL_GLOBAL and final_norm != "requested":
                        if final_norm == "already" and _should_bypass_positive_cache(
                            resolved_channel_identifier_for_cache
                        ):
                            log.info(
                                "queue_worker.skip_stale_positive_cache batch_id=%s url=%s cid=%s source=link_cache status=%s",
                                batch_id,
                                url,
                                resolved_channel_identifier_for_cache,
                                final_norm,
                            )
                        else:
                            sess_known = membership_db.get_any_session_for_channel(cid_link)
                            data = (final_norm, title_link, cid_link, "link_cache", sess_known)
                            _register_preknown(url, data)
                            if cleaned != url:
                                _register_preknown(cleaned, data)
                            continue

            # 1b) get_channel_id_by_url
            cid_raw = _get_channel_id_by_url(url, cleaned)
            if cid_raw:
                resolved_channel_identifier_for_cache = int(cid_raw)
                final = membership_db.any_final_for_channel(cid_raw)
                if final:
                    final_norm = "already" if final == "joined" else final
                    if final_norm in FINAL_GLOBAL and final_norm != "requested":
                        if final_norm == "already" and _should_bypass_positive_cache(
                            resolved_channel_identifier_for_cache
                        ):
                            log.info(
                                "queue_worker.skip_stale_positive_cache batch_id=%s url=%s cid=%s source=link_raw status=%s",
                                batch_id,
                                url,
                                resolved_channel_identifier_for_cache,
                                final_norm,
                            )
                        else:
                            sess_known = membership_db.get_any_session_for_channel(cid_raw)
                            data = (final_norm, None, cid_raw, "link_raw", sess_known)
                            _register_preknown(url, data)
                            if cleaned != url:
                                _register_preknown(cleaned, data)
                            continue

            # 2) Інвайт: якщо знаємо invite_hash -> channel_id і фінальний статус
            if inv_hash:
                cid_cached, title_cached = membership_db.map_invite_get(inv_hash)
                if cid_cached:
                    resolved_channel_identifier_for_cache = int(cid_cached)
                    final = membership_db.any_final_for_channel(int(cid_cached))
                    if final:
                        final_norm = "already" if final == "joined" else final
                        if final_norm in FINAL_GLOBAL and final_norm != "requested":
                            if final_norm == "already" and _should_bypass_positive_cache(
                                resolved_channel_identifier_for_cache
                            ):
                                log.info(
                                    "queue_worker.skip_stale_positive_cache batch_id=%s url=%s cid=%s source=invite_cache status=%s",
                                    batch_id,
                                    url,
                                    resolved_channel_identifier_for_cache,
                                    final_norm,
                                )
                            else:
                                sess_known = membership_db.get_any_session_for_channel(int(cid_cached))
                                data = (final_norm, title_cached, int(cid_cached), "invite_cache", sess_known)
                                _register_preknown(url, data)
                                if cleaned != url:
                                    _register_preknown(cleaned, data)
                                continue
        except Exception:
            pass

        # 3) url_cache — фінальні стани або duplicate
        try:
            ust = membership_db.url_get(url) or membership_db.url_get(cleaned)
        except Exception:
            ust = None
        if ust:
            status_norm = "already" if ust == "joined" else ust
            if _should_use_url_cache_status(
                status_norm=status_norm,
                channel_id=resolved_channel_identifier_for_cache,
            ):
                data = (status_norm, None, None, "url_cache", None)
                _register_preknown(url, data)
                if cleaned != url:
                    _register_preknown(cleaned, data)
                continue
            if (
                status_norm == "already"
                and _should_bypass_positive_cache(resolved_channel_identifier_for_cache)
            ):
                log.info(
                    "queue_worker.skip_stale_positive_cache batch_id=%s url=%s cid=%s source=url_cache status=%s",
                    batch_id,
                    url,
                    resolved_channel_identifier_for_cache,
                    status_norm,
                )
            elif status_norm == "duplicate":
                log.debug(
                    "queue_worker.ignore_duplicate_url_cache batch_id=%s url=%s cid=%s",
                    batch_id,
                    url,
                    resolved_channel_identifier_for_cache,
                )

        # Якщо сюди дійшли — мережа потрібна
        if inv_hash:
            # Якщо в invite_status уже є фінальний статус (наприклад, invalid), не рахуємо у ETA
            try:
                st_inv = membership_db.invite_status_get(inv_hash)
            except Exception:
                st_inv = None
            if st_inv and st_inv not in ("requested", "requested_fast", "private"):
                final_norm = "already" if st_inv == "joined" else st_inv
                if (
                    final_norm == "already"
                    and _should_bypass_positive_cache(resolved_channel_identifier_for_cache)
                ):
                    log.info(
                        "queue_worker.skip_stale_positive_cache batch_id=%s url=%s cid=%s source=invite_status status=%s",
                        batch_id,
                        url,
                        resolved_channel_identifier_for_cache,
                        final_norm,
                    )
                else:
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
    cooldown_extra_sec = 30  # додатковий кулдаун між пакетами
    eta_sec = (
        cnt_invite_need * LINK_DELAY_INVITE_MAX
        + cnt_public_need * LINK_DELAY_PUBLIC_MAX
        + cooldown_extra_sec
    )
    eta_min = math.ceil(eta_sec / 60) if (cnt_invite_need + cnt_public_need) > 0 else 0
    try:
        await reply_msg.answer(
            f"Орієнтовний час підписки: ~{eta_min} хв "
            f"(інвайтів: {cnt_invite_need} x {LINK_DELAY_INVITE_MAX:.0f}s, "
            f"публічних: {cnt_public_need} x {LINK_DELAY_PUBLIC_MAX:.0f}s, "
            f"кулдаун: +{cooldown_extra_sec}s)."
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
                    membership_db.url_put(url, status_for_report)
                    for k in collect_norm_keys(url):
                        membership_db.url_put(k, status_for_report)
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

            skip_membership, audit_present_session_name = _resolve_success_session_binding(
                channel_id=cid,
                base_status=base_status,
                current_session_name=sess,
                membership_db=membership_db,
            )
            if not skip_membership:
                upsert_membership(db, channel_id=cid, account=(sess or ""), status=base_status)
            _maybe_upsert_channel_session_assignment(
                channel_id=cid,
                session_name_value=sess,
                base_status=base_status,
                admin_id=admin_id,
                other_owner_id=other_owner_id,
                assignment_source=f"subscription_worker:fast_path:{kind}",
                skip_assignment=skip_membership,
            )
            _refresh_audit_after_success(
                channel_id=cid,
                base_status=base_status,
                present_session_name=audit_present_session_name,
                audit_reason=f"subscription_worker:fast_path:{kind}",
            )
            link_queue.mark_done(item_id)
            try:
                membership_db.url_put(url, status_for_report)
            except Exception:
                pass
            try:
                _add_link(cid, url, kind, origin_msg, current_owner_display, current_owner_username)
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
        slot = await get_ready_slot(
            preferred_session=_resolve_repair_preferred_session(
                resolved_channel_identifier_for_cache,
                preferred_session,
            ),
            fallback_to_round_robin=not bool(forced_session_name),
        )
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
                # не перевіряємо цей URL заново найближчим часом — сесія засинає
                backoff_seconds = max(backoff_seconds, 86400)
            else:
                bump_cooldown(client, 1)

            base_status = status or "unknown"
            status_display = f"{base_status}[{sess}]" if sess else base_status

            if base_status in ("requested", "requested_fast"):
                if invite_hash and sess:
                    try:
                        requested_checks_db.note_requested_invite(
                            session=sess,
                            invite_hash=invite_hash,
                            start_after_sec=90,
                        )
                    except Exception:
                        log.debug(
                            "queue_worker.requested_note_invite_failed batch_id=%s idx=%s invite=%s sess=%s",
                            batch_id,
                            idx,
                            invite_hash,
                            sess,
                            exc_info=True,
                        )
                if cid and sess:
                    try:
                        requested_checks_db.note_requested(
                            session=sess,
                            channel_id=int(cid),
                            start_after_sec=90,
                        )
                    except Exception:
                        log.debug(
                            "queue_worker.requested_note_channel_failed batch_id=%s idx=%s cid=%s sess=%s",
                            batch_id,
                            idx,
                            cid,
                            sess,
                            exc_info=True,
                        )

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

            skip_membership, audit_present_session_name = _resolve_success_session_binding(
                channel_id=cid,
                base_status=base_status,
                current_session_name=sess,
                membership_db=membership_db,
            )
            if not skip_membership:
                upsert_membership(db, channel_id=cid, account=sess or "", status=base_status)
            _maybe_upsert_channel_session_assignment(
                channel_id=cid,
                session_name_value=sess,
                base_status=base_status,
                admin_id=admin_id,
                other_owner_id=other_owner_id,
                assignment_source=f"subscription_worker:ensure_join:{kind}",
                skip_assignment=skip_membership,
            )
            cleanup_keep_session_name = audit_present_session_name or sess
            if cleanup_keep_session_name and base_status in ("joined", "already"):
                await enforce_single_session_per_channel(
                    channel_id=cid,
                    keep_session_name=cleanup_keep_session_name,
                    reason=f"subscription_worker:ensure_join:{kind}",
                )
            _refresh_audit_after_success(
                channel_id=cid,
                base_status=base_status,
                present_session_name=audit_present_session_name,
                audit_reason=f"subscription_worker:ensure_join:{kind}",
            )
            link_queue.mark_done(item_id)
            try:
                membership_db.url_put(url, status_for_report)
            except Exception:
                pass
            try:
                _add_link(cid, url, kind, origin_msg, current_owner_display, current_owner_username)
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

    # Фолбек: підтягуємо title з БД, якщо його немає у результатах
    try:
        db_titles = SessionLocal()
        mem_dao = MembershipDAO(db_titles)
        for it in result_items:
            cid = it.get("channel_id")
            url_val = it.get("url")
            # 1) Title by channel_id
            if cid and not it.get("title"):
                ch = cho.find_channel(db_titles, cid)
                if ch and ch.get("title"):
                    it["title"] = ch.get("title")
            # 2) Якщо досі немає title – пробуємо через raw_url
            if not it.get("title") and url_val:
                row = cho.find_channel_by_link(db_titles, url_val)
                if row:
                    # row може бути (channel_id, title)
                    if len(row) >= 1 and row[0] and not cid:
                        cid = int(row[0])
                        it["channel_id"] = cid
                    if len(row) >= 2 and row[1] and not it.get("title"):
                        it["title"] = row[1]
            # 2b) Якщо це інвайт і маємо map_invite -> title
            if not it.get("title") and url_val:
                inv_hash = _extract_invite_hash(url_val)
                if inv_hash:
                    inv_cid, inv_title = mem_dao.map_invite_get(inv_hash)
                    if inv_cid and not cid:
                        it["channel_id"] = inv_cid
                        cid = inv_cid
                    if inv_title:
                        it["title"] = inv_title
            # 3) Підтягуємо сесію для already/joined, не перетираючи існуючий статус із сесією
            status_raw = (it.get("status") or "").strip()
            if "[" not in status_raw and cid:
                sess_known = _get_effective_session_hint(cid, mem_dao)
                log.debug(
                    "queue_worker.report: hydrate session cid=%s status=%s session=%s url=%s",
                    cid,
                    status_raw,
                    sess_known,
                    url_val,
                )
                if sess_known:
                    it["status"] = f"{status_raw or 'already'}[{sess_known}]"
    except Exception:
        log.exception("queue_worker: failed to hydrate titles/sessions from DB")
    finally:
        try:
            db_titles.close()
        except Exception:
            pass

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
    try:
        batch_cache.register(batch_id, result_items, original_urls)
    except Exception:
        log.exception("queue_worker: failed to cache result_items for batch_id=%s", batch_id)
    db.close()
