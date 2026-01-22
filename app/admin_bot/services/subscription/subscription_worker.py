from __future__ import annotations

import logging
import math
import re
from typing import List, Optional, Dict, Tuple

from app.admin_bot.services import report_cache
from app.services import link_queue
from app.services.account_pool import mark_flood, mark_limit, bump_cooldown, session_name
from app.services.joiner import ensure_join, _extract_invite_hash
from app.DAL import membership_operations as mem_db
from app.DAL import link_cache_operations as lc_db
from app.DAL.schemas import LinkCachePatch
from app.DAL.membership_operations import FINAL_GLOBAL
from app.admin_bot.services.subscription.subscription_for_bot import ensure_bot_started
from app.utils.throttle import LINK_DELAY_INVITE_MAX, LINK_DELAY_PUBLIC_MAX
from app.utils.link_parser import sanitize_link, extract_bot_username, build_invite_url
from app.DAL.channels_operations import upsert_channel_full
from app.admin_bot.services.owner_conflicts import log_conflict
from app.admin_bot.services.subscription.subscription_menu import split_text_for_telegram
from app.admin_bot.services.subscription.keyboards import make_report_keyboard
from app.admin_bot.services.subscription import batch_cache
from app.admin_bot.services.progress import Progress
from app.admin_bot.services import admins as svc_admins
from app.admin_bot.services import networks as svc_networks
from app.db.session import session_scope
from app.admin_bot.services.subscription.subscription_slots_pool import get_ready_slot
from app.admin_bot.services.subscription.subscription_status import render_html_with_statuses
from app.admin_bot.services.subscription.subscription_report import answer_with_retry
from app.admin_bot.services.subscription.subscription_utils import norm_keys as collect_norm_keys
from app.logging_json import get_logger, configure_logging
from app.DAL import channels_operations as cho
from app.DAL import requested_operations as req_ops

# Гарантований мінімальний логер (на випадок, якщо головний процес не налаштував logging).
if not logging.getLogger().handlers:
    configure_logging()

log = get_logger("admin_bot.queue_worker")

_INVITE_STUB_RE = re.compile(r"^https?://t\\.me/(?:joinchat/?)?(?:\\+)?$")


def _find_channel_by_link(url: str, cleaned: Optional[str] = None):
    with session_scope() as db:
        row = cho.find_channel_by_link(db, url)
        if not row and cleaned and cleaned != url:
            row = cho.find_channel_by_link(db, cleaned)
        return row


def _get_channel_id_by_url(url: str, cleaned: Optional[str] = None):
    with session_scope() as db:
        cid = cho.get_channel_id_by_url(db, url)
        if not cid and cleaned and cleaned != url:
            cid = cho.get_channel_id_by_url(db, cleaned)
        return cid


def _add_link(
    channel_id,
    raw_url,
    kind,
    batch_msg_id,
):
    with session_scope() as db:
        cho.add_link(
            db,
            channel_id,
            raw_url,
            kind,
            batch_msg_id,
        )


async def process_batch(
    *,
    batch_id: str,
    chat_id: int,
    reply_msg,
    admin_id: Optional[int],
    admin_display: str,
    admin_username: Optional[str],
    admin_tg_id: Optional[int],
    original_urls: Optional[List[str]] = None,
):
    """
    Обробляє записані в link_queue URL для batch_id. Використовує один lease, якщо доступний.
    """
    try:
        urls_rec = link_queue.fetch_batch_due(batch_id, limit=200)
        log.info("queue_worker.start batch_id=%s chat_id=%s urls=%s", batch_id, chat_id, len(urls_rec))
        if not urls_rec:
            await answer_with_retry(reply_msg, "Черга порожня або ще не готова.")
            return
    except Exception:
        log.exception("queue_worker.start failed batch_id=%s chat_id=%s", batch_id, chat_id)
        raise

    total = len(urls_rec)
    progress = Progress(reply_msg, total=total)
    await progress.start()

    result_items: List[Dict] = []
    admin_id: Optional[int] = admin_id
    current_owner_username = admin_username

    def _cache_invite_status(
        invite_hash: Optional[str],
        *,
        cid: Optional[int],
        title: Optional[str],
        status: str,
        sess: Optional[str],
        last_error: Optional[str] = None,
    ) -> None:
        if not invite_hash:
            return
        invite_url_norm = build_invite_url(invite_hash) or invite_hash
        try:
            lc_db.update_link_cache_status(
                LinkCachePatch(
                    url_norm=invite_url_norm,
                    kind="invite",
                    status=status,
                    account=sess or "",
                    channel_id=cid,
                    title=title,
                    last_error=last_error,
                )
            )
        except Exception:
            log.warning("queue_worker.cache_invite_status failed invite=%s status=%s", invite_hash, status, exc_info=True)

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

    def _resolve_from_cache(url: str, cleaned: Optional[str]) -> Optional[Tuple[str, Optional[str], Optional[int], Optional[str]]]:
        """
        Повертає (status, title, channel_id, account) з link_cache або None.
        """
        for candidate in (url, cleaned):
            if not candidate:
                continue
            rec = lc_db.get_link_cache_record(candidate)
            if rec:
                status_norm = "already" if rec.status == "joined" else rec.status
                return status_norm, rec.title, rec.channel_id, rec.account
        return None

    for rec in urls_rec:
        url = rec.url
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

        preferred_session: Optional[str] = None
        if inv_hash:
            try:
                with session_scope() as db_sess:
                    preferred_session = mem_db.invite_check_last_session(db_sess, inv_hash)
            except Exception:
                preferred_session = None
        # 0) link_cache: фінальні/duplicate стани без мережі
        try:
            cache_hit = _resolve_from_cache(url, cleaned)
        except Exception:
            cache_hit = None
        if cache_hit:
            status_norm, title_cached, cid_cached, acc_cached = cache_hit
            if (status_norm in FINAL_GLOBAL and status_norm != "requested") or status_norm == "duplicate":
                data = (status_norm, title_cached, cid_cached or 0, "link_cache", acc_cached)
                _register_preknown(url, data)
                if cleaned != url:
                    _register_preknown(cleaned, data)
                continue
        # 1) find_channel_by_link (raw/clean)
        try:
            link_row = _find_channel_by_link(url, cleaned)
            if link_row:
                cid_link, title_link = link_row.channel_id, link_row.title
                with session_scope() as db_link:
                    final = mem_db.any_final_for_channel(db_link, cid_link)
                if final:
                    final_norm = "already" if final == "joined" else final
                    if final_norm in FINAL_GLOBAL and final_norm != "requested":
                        sess_known = mem_db.get_any_session_for_channel(db_link, cid_link)
                        data = (final_norm, title_link, cid_link, "link_cache", sess_known)
                        _register_preknown(url, data)
                        if cleaned != url:
                            _register_preknown(cleaned, data)
                        continue

            # 1b) get_channel_id_by_url
            cid_raw = _get_channel_id_by_url(url, cleaned)
            if cid_raw:
                with session_scope() as db_raw:
                    final = mem_db.any_final_for_channel(db_raw, cid_raw)
                if final:
                    final_norm = "already" if final == "joined" else final
                    if final_norm in FINAL_GLOBAL and final_norm != "requested":
                        sess_known = mem_db.get_any_session_for_channel(db_raw, cid_raw)
                        data = (final_norm, None, cid_raw, "link_raw", sess_known)
                        _register_preknown(url, data)
                        if cleaned != url:
                            _register_preknown(cleaned, data)
                        continue

            # 2) Інвайт: якщо знаємо invite_hash -> channel_id і фінальний статус (через link_cache)
            if inv_hash:
                try:
                    cache_hit = _resolve_from_cache(url, cleaned)
                    if cache_hit:
                        status_norm, title_cached, cid_cached, acc_cached = cache_hit
                        if (status_norm in FINAL_GLOBAL and status_norm != "requested") or status_norm == "duplicate":
                            data = (status_norm, title_cached, cid_cached or 0, "link_cache", acc_cached)
                            _register_preknown(url, data)
                            if cleaned != url:
                                _register_preknown(cleaned, data)
                            continue
                except Exception:
                    pass
        except Exception:
            pass

        # Якщо сюди дійшли — мережа потрібна
        if inv_hash:
            # Якщо в link_cache уже є фінальний статус (наприклад, invalid), не рахуємо у ETA
            st_inv = None
            try:
                cache_hit = _resolve_from_cache(url, cleaned)
                st_inv = cache_hit[0] if cache_hit else None
            except Exception:
                st_inv = None
            if st_inv and st_inv != "requested":
                final_norm = "already" if st_inv == "joined" else st_inv
                data = (final_norm, None, None, "link_cache_status", None)
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
    with session_scope() as db_lookup:
        existing_admin = svc_admins.get_admin_by_display(db_lookup, admin_display) if admin_display else None
        if existing_admin:
            admin_id = existing_admin.id
            current_owner_username = existing_admin.username

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
        log.debug("queue_worker.reply_eta failed batch_id=%s", batch_id, exc_info=True)
    for idx, rec in enumerate(urls_rec, start=1):
        item_id = rec.id
        url = rec.url
        tries = rec.tries
        origin_msg = rec.origin_msg
        owner_admin_id_rec = rec.owner_admin_id
        if owner_admin_id_rec and admin_id is None:
            admin_id = owner_admin_id_rec
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
                    owner_admin_id=admin_id,
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
                _cache_invite_status(inv_hash, cid=cid, title=title, status=base_status, sess=sess)
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
                _cache_invite_status(inv_hash, cid=None, title=title, status=base_status, sess=sess, last_error=base_status if base_status.startswith("error") else None)
                result_items.append({
                    "idx": idx,
                    "url": url,
                    "title": title,
                    "status": status_display,
                    "channel_id": None,
                })
                await progress.update(status_display, title or url, sess)
                _remember_seen(collect_norm_keys(url), title=title, channel_id=None, session=sess)
                continue
            with session_scope() as db:
                try:
                    upsert_channel_full(
                        db,
                        channel_id=cid,
                        username=None,
                        title=title,
                        order_index=item_id,
                        owner_admin_id=admin_id,
                        last_status=base_status,
                    )
                except Exception:
                    pass

                # owner_conflict check і прив'язка (як звичайно)
                other_owner = None
                other_owner_id = None
                adm_info = cho.get_admin_for_channel(db, cid)
                if adm_info and adm_info.admin_id:
                    other_owner_id = adm_info.admin_id
                    other_owner = (adm_info.display or f"@{adm_info.username}") if adm_info else None

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
                    if admin_id is None and base_status in ("joined", "already", "requested"):
                        adm_obj = svc_admins.get_or_create_admin(
                            db,
                            tg_id=admin_tg_id,
                            username=admin_username,
                            display=admin_display,
                        )
                        admin_id = adm_obj.id
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

                mem_db.upsert_membership(db, account=(sess or ""), channel_id=cid, status=base_status)
            link_queue.mark_done(item_id)
            try:
                _add_link(
                    cid,
                    url,
                    kind,
                    origin_msg,
                )
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
                # не перевіряємо цей URL заново найближчим часом — сесія засинає
                backoff_seconds = max(backoff_seconds, 86400)
            else:
                bump_cooldown(client, 1)

            base_status = status or "unknown"
            status_display = f"{base_status}[{sess}]" if sess else base_status

            if base_status == "requested":
                try:
                    if invite_hash:
                        with session_scope() as db:
                            req_ops.note_requested_invite(db, sess or "", invite_hash, start_after_sec=60)
                    elif cid:
                        req_ops.note_requested(sess or "", cid, start_after_sec=60)
                except Exception:
                    log.exception(
                        "queue_worker.note_requested failed batch_id=%s idx=%s url=%s sess=%s invite=%s cid=%s",
                        batch_id,
                        idx,
                        url,
                        sess,
                        invite_hash,
                        cid,
                    )

            if cid is None:
                _cache_invite_status(
                    invite_hash,
                    cid=None,
                    title=title,
                    status=base_status,
                    sess=sess,
                    last_error=base_status if base_status.startswith("error") else None,
                )
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

            with session_scope() as db:
                upsert_channel_full(
                    db,
                    channel_id=cid,
                    username=None,
                    title=title,
                    order_index=item_id,
                    owner_admin_id=admin_id,
                    last_status=base_status,
                )

                other_owner = None
                other_owner_id = None
                adm_info = cho.get_admin_for_channel(db, cid)
                if adm_info and adm_info.admin_id:
                    other_owner_id = adm_info.admin_id
                    other_owner = (adm_info.display or f"@{adm_info.username}") if adm_info else None

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
                    create_allowed = base_status in ("joined", "already", "requested")
                    if create_allowed and admin_id is None:
                        adm_obj = svc_admins.get_or_create_admin(
                            db,
                            tg_id=admin_tg_id,
                            username=admin_username,
                            display=admin_display,
                        )
                        admin_id = adm_obj.id
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

                mem_db.upsert_membership(db, account=sess or "", channel_id=cid, status=base_status)

            _cache_invite_status(
                invite_hash,
                cid=cid,
                title=title,
                status=base_status,
                sess=sess,
                last_error=base_status if base_status.startswith("error") else None,
            )

            link_queue.mark_done(item_id)
            try:
                _add_link(
                    cid,
                    url,
                    kind,
                    origin_msg,
                )
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
            n = (sanitize_link(it.get("url", "")) or it.get("url", "")).rstrip(").,;")
            norm_counts[n] = norm_counts.get(n, 0) + 1
            cid_counts[it.get("channel_id")] = cid_counts.get(it.get("channel_id"), 0) + 1

        norm_seen: Dict[str, int] = {}
        cid_seen: Dict[Optional[int], int] = {}
        dup_count = 0

        render_order = original_urls if original_urls else [it.get("url", "") for it in result_items]
        buckets: Dict[str, List[Dict]] = {}
        for it in result_items:
            n = (sanitize_link(it.get("url", "")) or it.get("url", "")).rstrip(").,;")
            buckets.setdefault(n, []).append(it)

        def _pop(norm: str) -> Optional[Dict]:
            lst = buckets.get(norm) or []
            if lst:
                return lst.pop(0)
            return None

        for url in render_order:
            norm = (sanitize_link(url) or url).rstrip(").,;")
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
        for it in result_items:
            cid = it.get("channel_id")
            url_val = it.get("url")
            cache = lc_db.get_link_cache_record(url_val or "")
            if cache:
                if cache.channel_id and not cid:
                    it["channel_id"] = cache.channel_id
                    cid = cache.channel_id
                if cache.title and not it.get("title"):
                    it["title"] = cache.title
            status_raw = (it.get("status") or "").strip()
            if "[" not in status_raw and cid:
                sess_known = cache.account if cache and cache.account else None
                if sess_known:
                    it["status"] = f"{status_raw or 'already'}[{sess_known}]"
    except Exception:
        log.exception("queue_worker: failed to hydrate titles/sessions from DB")

    # Рендер звіту зі збереженням форматування та статусами біля кожного лінка
    try:
        html_report = render_html_with_statuses(result_items, original_urls)
    except Exception as e:
        # Замість старого fallback відправляємо текст помилки в бот
        log.exception("queue_worker: failed render html report, fallback disabled")
        pages = [f"Render error: {e}"]
        report_idx = None
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

        kb = make_report_keyboard(0, len(pages), has_report=report_idx is not None)
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
