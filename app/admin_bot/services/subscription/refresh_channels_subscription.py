from __future__ import annotations

import logging
import re
from typing import List, Optional, Set, Dict
from types import SimpleNamespace

from sqlalchemy import select, delete

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.admin_bot.db.session import SessionLocal
from app.admin_bot.db import models as m
from app.admin_bot.services import report_cache
from app.admin_bot.services.subscription import batch_cache
from app.admin_bot.services import admins as svc_admins
from app.admin_bot.services.subscription.subscription_report import answer_with_retry
from app.admin_bot.services.subscription.subscription_menu import split_text_for_telegram, make_report_kb
from app.services import link_queue
from app.services import account_pool
from app.DAL import channels_operations as cho
from app.DAL.membership_operations import MembershipDAO
from app.utils.link_parser import sanitize_link
from app.admin_bot.services.subscription.subscription_utils import norm_keys as collect_norm_keys

log = logging.getLogger("admin_bot.services.subscription.refresh_channels")

_PENDING_REFRESH_CONFIRMATIONS: Dict[str, Dict] = {}


def _empty_cleanup_stats() -> Dict[str, int]:
    return {
        "left_total": 0,
        "leave_errors": 0,
        "admin_channels_deleted": 0,
        "network_channels_deleted": 0,
        "membership_deleted": 0,
        "membership_status_deleted": 0,
        "invite_map_deleted": 0,
        "invite_status_deleted": 0,
        "owner_conflicts_deleted": 0,
        "links_deleted": 0,
        "url_cache_deleted": 0,
        "channels_deleted": 0,
        "link_queue_deleted": 0,
    }


def _resolve_channel_id(url: str) -> Optional[int]:
    """
    Визначає channel_id за URL/інвайтом, використовуючи кеш links/invite_map.
    """
    if not url:
        return None
    try:
        clean = sanitize_link(url) or url
    except Exception:
        clean = url

    db = SessionLocal()
    dao = MembershipDAO(db)
    try:
        for candidate in (url, clean):
            if not candidate:
                continue
            row = cho.find_channel_by_link(db, candidate)
            if row and row[0]:
                return row[0]
            cid = cho.get_channel_id_by_url(db, candidate)
            if cid:
                return cid
            cid_map, _ = dao.map_invite_get(candidate)
            if cid_map:
                return cid_map
        return None
    finally:
        db.close()


async def _cleanup_removed_channels(admin: m.Admin, chan_ids: Set[int]) -> Dict[str, int]:
    """
    Відписує сесії від каналів та чистить пов’язані таблиці для каналів, які більше не потрібні цьому адміна.
    """
    stats = _empty_cleanup_stats()
    if not chan_ids:
        return stats

    db = SessionLocal()

    # Відписуємо клієнтів
    memberships = db.execute(
        select(m.Membership).where(m.Membership.channel_id.in_(chan_ids), m.Membership.account != "")
    ).scalars().all()
    acct_map: Dict[str, Set[int]] = {}
    for mbr in memberships:
        acct_map.setdefault(mbr.account, set()).add(mbr.channel_id)
    for acct, cids in acct_map.items():
        stat = await account_pool.leave_channels(acct, list(cids))
        stats["left_total"] += stat.get("left", 0) or 0
        stats["leave_errors"] += stat.get("errors", 0) or 0

    # Видаляємо прив’язки адміна та його сіток
    stats["admin_channels_deleted"] = db.execute(
        delete(m.AdminChannel)
        .where(m.AdminChannel.admin_id == admin.id, m.AdminChannel.channel_id.in_(chan_ids))
    ).rowcount or 0
    net_ids = list(db.execute(select(m.Network.id).where(m.Network.admin_id == admin.id)).scalars().all())
    if net_ids:
        stats["network_channels_deleted"] = db.execute(
            delete(m.NetworkChannel).where(
                m.NetworkChannel.network_id.in_(net_ids),
                m.NetworkChannel.channel_id.in_(chan_ids),
            )
        ).rowcount or 0
    db.commit()

    # Перевіряємо, які канали ніде більше не використовуються
    keep_ids = set(db.execute(select(m.AdminChannel.channel_id)).scalars().all()) | set(
        db.execute(select(m.NetworkChannel.channel_id)).scalars().all()
    )
    delete_ids = [cid for cid in chan_ids if cid not in keep_ids]

    urls_for_cleanup: List[str] = []
    if delete_ids:
        for r in db.execute(select(m.Link.raw_url).where(m.Link.channel_id.in_(delete_ids))).all():
            if r and r[0]:
                urls_for_cleanup.extend(svc_admins._expand_url_variants(r[0]))  # type: ignore[attr-defined]
        pre_count = svc_admins._count_url_cache(urls_for_cleanup, db) if urls_for_cleanup else 0  # type: ignore[attr-defined]

        stats["membership_deleted"] = m.delete_memberships_by_channels(db, delete_ids)
        stats["membership_status_deleted"] = m.delete_membership_status_by_channels(db, delete_ids)
        hashes = [h for h in db.execute(select(m.InviteMap.invite_hash).where(m.InviteMap.channel_id.in_(delete_ids))).scalars().all()]
        stats["invite_status_deleted"] = m.delete_invite_status_by_hashes(db, hashes)
        stats["invite_map_deleted"] = m.delete_invite_map_by_channels(db, delete_ids)
        stats["owner_conflicts_deleted"] = m.delete_owner_conflict_by_channels(db, delete_ids)
        stats["links_deleted"] = m.delete_links_by_channels(db, delete_ids)

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

    # Чистимо чергу по власнику та URL
    try:
        stats["link_queue_deleted"] = link_queue.delete_by_owner(
            owner_display=admin.display,
            owner_username=admin.username,
            urls=urls_for_cleanup,
        )
    except Exception:
        stats["link_queue_deleted"] = 0

    db.commit()
    db.close()
    return stats


def _format_removed_lines(
    *,
    to_remove: Set[int],
    removed_link_map: Dict[int, tuple[Optional[str], Optional[str]]],
    removed_sessions: Dict[int, Set[str]],
    action_text: str,
    db=None,
) -> List[str]:
    lines = []
    for cid in to_remove:
        title, href = removed_link_map.get(cid, (None, None))
        if not title and db is not None:
            ch = db.execute(select(m.Channel).where(m.Channel.id == cid)).scalar_one_or_none()
            title = getattr(ch, "title", None)
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
    admin: m.Admin,
    reply_msg,
    status_lines: List[str],
    to_remove: Set[int],
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
                    to_remove=to_remove,
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
                    to_remove=to_remove,
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
        f"invite_map {stats['invite_map_deleted']}, invite_status {stats['invite_status_deleted']}, owner_conflicts {stats['owner_conflicts_deleted']}; "
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
        kb = make_report_kb(0, len(pages), has_report=False)
        sent = await answer_with_retry(
            reply_msg,
            pages[0],
            disable_web_page_preview=True,
            parse_mode="HTML",
            reply_markup=kb,
        )
        if sent:
            report_cache.register(sent.chat.id, sent.message_id, pages, None)  # type: ignore[name-defined]


async def refresh_channels_for_admin(
    *,
    batch_id: str,
    chat_id: int,
    reply_msg,
    admin: m.Admin,
    urls: List[str],
    raw_text: str,
    raw_html: str,
    entities: List,
):
    """
    Оновлює список каналів адміна:
    1) підписує/оновлює за новими URL (process_batch)
    2) визначає канал_id із нових URL
    3) відписує та чистить канали, що не потрапили до нового списку.
    """
    db = SessionLocal()
    current_cids = set(
        db.execute(select(m.AdminChannel.channel_id).where(m.AdminChannel.admin_id == admin.id)).scalars().all()
    )
    net_chan_ids = db.execute(
        select(m.NetworkChannel.channel_id)
        .join(m.Network, m.NetworkChannel.network_id == m.Network.id)
        .where(m.Network.admin_id == admin.id)
    ).scalars().all()
    if net_chan_ids:
        current_cids |= set(net_chan_ids)
    conflict_clear_cids: Set[int] = set()

    added = link_queue.enqueue(
        urls,
        batch_id=batch_id,
        origin_chat=chat_id,
        origin_msg=getattr(reply_msg, "message_id", None),
        owner_display=admin.display,
        owner_username=admin.username,
        adopt_existing=True,
        reset_next_try=True,
    )
    # Імпорт всередині, щоб уникнути циклічного імпорту
    from app.admin_bot.services.queue_worker import process_batch

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
        def __init__(self, orig):
            self._orig = orig
            self.bot = _FilteredBot(orig.bot)
            self.chat = orig.chat
            self.message_id = getattr(orig, "message_id", None)

        async def answer(self, text, *args, **kwargs):
            if any(marker in str(text) for marker in allowed_markers):
                return await self._orig.answer(text, *args, **kwargs)
            return SimpleNamespace(message_id=None, chat=self.chat)

    filtered_msg = _FilteredMessage(reply_msg)

    await process_batch(
        batch_id=batch_id,
        chat_id=chat_id,
        reply_msg=filtered_msg,
        admin_display=admin.display,
        admin_username=admin.username,
        admin_tg_id=admin.tg_id,
        raw_text=raw_text,
        raw_html=raw_html,
        entities=entities,
        original_urls=urls,
    )

    cache_entry = batch_cache.pop(batch_id) or {}
    cached_items = cache_entry.get("items") or []
    cache_map: Dict[str, Dict] = {}
    keep_from_cache: Set[int] = set()
    for it in cached_items:
        nkeys = collect_norm_keys(it.get("url", ""))
        for nk in nkeys:
            cache_map[nk] = it
        cid = it.get("channel_id")
        if cid:
            keep_from_cache.add(int(cid))

    keep_cids: Set[int] = set()
    for u in urls:
        cid = _resolve_channel_id(u)
        if cid:
            keep_cids.add(cid)
        if not cid:
            cached = cache_map.get(u) or cache_map.get(sanitize_link(u) or "")
            if cached and cached.get("channel_id"):
                keep_cids.add(int(cached["channel_id"]))
    if keep_from_cache:
        keep_cids |= keep_from_cache
    no_cid_resolution = False
    if not keep_cids:
        # не вдалося визначити channel_id для нових URL — не відписуємо поточні,
        # але показуємо статуси з кешу
        no_cid_resolution = True
        keep_cids = set(current_cids)

    if not keep_cids:
        await answer_with_retry(
            reply_msg,
            "Не вдалося визначити канали за надісланими посиланнями — видалення пропущено.",
        )
        db.close()
        return

    def _human_status(raw: Optional[str], session_hint: Optional[str] = None) -> str:
        if not raw:
            return "…"
        s = raw.lower()
        base = raw
        sess = None
        if "[" in raw and raw.endswith("]"):
            sess = raw[raw.rfind("[") + 1 : -1]
            base = raw[: raw.rfind("[")].strip()
        if "owner_conflict" in s:
            conflict_with = None
            try:
                conflict_with = re.search(r"owner_conflict\(existing=([^)]+)\)", base, re.IGNORECASE).group(1)  # type: ignore[arg-type]
            except Exception:
                conflict_with = None
            human = "⚠️ Конфликт"
            if conflict_with:
                human = f"⚠️ Конфликт (закреплен за {conflict_with})"
        elif "requested" in s or "заявк" in s:
            human = "✉️ Заявка"
        elif "duplicate" in s:
            human = "🔁 Дубликат"
        elif "joined" in s:
            human = "✅ Подписался"
        elif "already" in s:
            human = "☑️ Был подписан"
        elif "flood" in s:
            human = "⏳ Флуд"
        elif any(tok in s for tok in ("invalid", "private", "error", "blocked", "too_many")):
            human = "❌ Невалидное"
        else:
            human = base or "…"
        if sess:
            human = f"{human} [{account_pool.session_display(sess)}]"
        elif session_hint:
            human = f"{human} [{account_pool.session_display(session_hint)}]"
        return human

    def _is_same_owner(candidate: Optional[str], admin_obj: m.Admin) -> bool:
        if not candidate:
            return False
        cand = candidate.strip().lstrip("@").lower()
        if admin_obj.display and cand == admin_obj.display.strip().lstrip("@").lower():
            return True
        if admin_obj.username and cand == admin_obj.username.strip().lstrip("@").lower():
            return True
        if admin_obj.tg_id and cand == str(admin_obj.tg_id):
            return True
        return False

    # --- Формуємо список усіх отриманих каналів зі статусами ---
    status_lines: List[str] = ["📋 Обновление списка каналов"]
    dao = MembershipDAO(db)
    if no_cid_resolution:
        status_lines.append("⚠️ Не вдалося визначити channel_id за новими посиланнями; відписка пропущена, показуємо статуси за кешем.")

    for idx, url in enumerate(urls, start=1):
        status_raw = None
        try:
            clean = sanitize_link(url) or url
        except Exception:
            clean = url
        cached_item = cache_map.get(clean) or cache_map.get(url)
        cid, title = None, None
        cid_title = dao.map_invite_get(clean)
        cid, title = cid_title
        if not cid:
            cid = _resolve_channel_id(clean)
        if not title and cid:
            ch = db.execute(select(m.Channel).where(m.Channel.id == cid)).scalar_one_or_none()
            title = getattr(ch, "title", None)
        if cached_item:
            if cached_item.get("channel_id") and not cid:
                cid = cached_item.get("channel_id")
            if cached_item.get("title") and not title:
                title = cached_item.get("title")
            status_raw = cached_item.get("status")
        # Підтягуємо статус підписки; інколи кеш зберігається по неочищеному URL,
        # тому пробуємо і clean, і вихідний url.
        if not status_raw:
            for candidate in (clean, url):
                if not candidate:
                    continue
                status_raw = dao.invite_status_get(candidate)
                if status_raw:
                    break

        session_hint = None
        # Конфлікт власника: читаємо з таблиці, щоб явно відобразити
        if cid:
            oc = (
                db.execute(select(m.OwnerConflict).where(m.OwnerConflict.channel_id == cid).limit(1))
                .scalars()
                .first()
            )
            # Шукаємо адміна, який уже прив'язаний до цього каналу
            ac_row = (
                db.execute(
                    select(m.Admin.display, m.Admin.username, m.Admin.tg_id, m.Admin.id)
                    .join(m.AdminChannel, m.AdminChannel.admin_id == m.Admin.id)
                    .where(m.AdminChannel.channel_id == cid)
                    .limit(1)
                ).first()
            )
            ac_display = None
            ac_admin_id = None
            if ac_row:
                disp, uname, tg_id, ac_admin_id = ac_row
                if disp:
                    ac_display = disp
                elif uname:
                    ac_display = f"@{uname}"
                elif tg_id:
                    ac_display = str(tg_id)
            if oc:
                existing = (
                    getattr(oc, "owner", None)
                    or getattr(oc, "reason", None)
                    or ac_display
                )
                conflict_with = "" if existing is None else str(existing).strip()
                # Якщо у таблиці збережено «unknown», але ми знаємо адміна — показуємо його
                if (not conflict_with or conflict_with.lower() in ("unknown", "невідомий адмін")) and ac_display:
                    conflict_with = ac_display
                # Якщо конфлікт записаний на цього ж адміна — очищаємо і не показуємо
                if conflict_with and _is_same_owner(conflict_with, admin):
                    conflict_clear_cids.add(int(cid))
                    conflict_with = ""
                if not conflict_with:
                    conflict_with = None
                if conflict_with:
                    if status_raw and "owner_conflict" in status_raw:
                        status_raw = f"owner_conflict(existing={conflict_with})"
                    elif not status_raw:
                        status_raw = f"owner_conflict(existing={conflict_with})"
            elif ac_admin_id and admin.id and ac_admin_id != admin.id:
                # Канал уже прив'язаний до іншого адміна, але конфлікт не записаний у таблиці
                conflict_with = ac_display or str(ac_admin_id) or "невідомий адмін"
                status_raw = f"owner_conflict(existing={conflict_with})"
            # Якщо є активна підписка в membership — вважаємо, що був підписаний
            first_membership = db.execute(
                select(m.Membership.account).where(m.Membership.channel_id == cid).limit(1)
            ).scalar_one_or_none()
            if first_membership:
                if not session_hint:
                    session_hint = str(first_membership)
                if not status_raw:
                    status_raw = "already"
                elif "joined" in (status_raw or "").lower() and "already" not in (status_raw or "").lower():
                    status_raw = "already"
            if not session_hint:
                try:
                    session_hint = dao.get_any_session_for_channel(int(cid))
                except Exception:
                    session_hint = None
        human = _human_status(status_raw, session_hint)

        title_txt = title or clean or url or "невідомо"
        href = clean or url
        status_lines.append(f"{idx}. <a href=\"{href}\">{title_txt}</a> — {human}")

    if conflict_clear_cids:
        try:
            db.execute(delete(m.OwnerConflict).where(m.OwnerConflict.channel_id.in_(conflict_clear_cids)))
            db.commit()
        except Exception:
            pass

    to_remove = {cid for cid in current_cids if cid not in keep_cids}

    # Готуємо лінки/назви для видалених каналів, щоб відобразити як у списку
    removed_link_map: Dict[int, tuple[Optional[str], Optional[str]]] = {}
    if to_remove:
        rows = db.execute(
            select(m.Channel.id, m.Channel.title, m.Link.raw_url)
            .join(m.Link, m.Link.channel_id == m.Channel.id, isouter=True)
            .where(m.Channel.id.in_(to_remove))
        ).all()
        for cid, title, raw_url in rows:
            if cid not in removed_link_map:
                href = None
                if raw_url:
                    try:
                        href = sanitize_link(raw_url) or raw_url
                    except Exception:
                        href = raw_url
                removed_link_map[cid] = (title, href)
        # Якщо немає посилання в links – пробуємо витягти з invite_map
        invite_rows = db.execute(
            select(m.InviteMap.channel_id, m.InviteMap.title, m.InviteMap.invite_hash)
            .where(m.InviteMap.channel_id.in_(to_remove))
        ).all()
        for cid, title, inv_hash in invite_rows:
            if cid in removed_link_map and removed_link_map[cid][1]:
                continue
            href = None
            if inv_hash:
                href = f"https://t.me/+{inv_hash}"
            prev_title, prev_href = removed_link_map.get(cid, (None, None))
            if not prev_title and title:
                prev_title = title
            removed_link_map[cid] = (prev_title or title, prev_href or href)

    # Фіксуємо сесії, що були підписані на ці канали (до чистки), щоб показати у звіті
    removed_sessions: Dict[int, Set[str]] = {}
    if to_remove:
        try:
            rows = (
                db.query(m.Membership.channel_id, m.Membership.account)
                .filter(m.Membership.channel_id.in_([int(cid) for cid in to_remove]))
                .all()
            )
            for cid_val, acc in rows:
                removed_sessions.setdefault(int(cid_val), set()).add(str(acc))
        except Exception:
            removed_sessions = {}

    if to_remove:
        _PENDING_REFRESH_CONFIRMATIONS.pop(batch_id, None)
        _PENDING_REFRESH_CONFIRMATIONS[batch_id] = {
            "admin_id": admin.id,
            "status_lines": list(status_lines),
            "to_remove": set(to_remove),
            "removed_link_map": removed_link_map,
            "removed_sessions": removed_sessions,
        }
        preview_lines = [
            "Знайшли канали, яких немає у новому списку. Відписати від них?",
            "",
        ]
        preview_lines.extend(
            _format_removed_lines(
                to_remove=to_remove,
                removed_link_map=removed_link_map,
                removed_sessions=removed_sessions,
                action_text="Потенційна відписка",
                db=db,
            )
        )
        preview_lines.append("")
        preview_lines.append("Підтвердити відписку?")
        kb_confirm = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Так", callback_data=f"refresh_unsub_yes:{batch_id}"),
                    InlineKeyboardButton(text="Ні", callback_data=f"refresh_unsub_no:{batch_id}"),
                ]
            ]
        )
        text_preview = "\n".join(preview_lines)
        pages = split_text_for_telegram(text_preview, max_len=5000)
        if len(pages) == 1:
            await answer_with_retry(
                reply_msg,
                pages[0],
                disable_web_page_preview=True,
                reply_markup=kb_confirm,
                parse_mode="HTML",
            )
        else:
            kb = make_report_kb(0, len(pages), has_report=False)
            sent = await answer_with_retry(
                reply_msg,
                pages[0],
                disable_web_page_preview=True,
                parse_mode="HTML",
                reply_markup=kb,
            )
            if sent:
                report_cache.register(sent.chat.id, sent.message_id, pages, None)
        db.close()
        return

    await _send_refresh_report(
        admin=admin,
        reply_msg=reply_msg,
        status_lines=status_lines,
        to_remove=to_remove,
        removed_link_map=removed_link_map,
        removed_sessions=removed_sessions,
        perform_cleanup=True,
        db=db,
    )
    db.close()


async def finalize_refresh_confirmation(batch_id: str, approve_unsubscribe: bool, reply_msg) -> None:
    """
    Завершує оновлення каналів після відповіді на підтвердження відписки.
    """
    ctx = _PENDING_REFRESH_CONFIRMATIONS.pop(batch_id, None)
    if not ctx:
        await answer_with_retry(reply_msg, "Не знайшов дані для цього запиту. Спробуй запустити оновлення ще раз.")
        return

    admin_id = ctx.get("admin_id")
    db = SessionLocal()
    admin = svc_admins.get_admin_by_id(db, admin_id) if admin_id else None
    db.close()

    if not admin:
        await answer_with_retry(reply_msg, "Адміна не знайдено. Спробуй запустити оновлення ще раз.")
        return

    report_db = SessionLocal()
    try:
        await _send_refresh_report(
            admin=admin,
            reply_msg=reply_msg,
            status_lines=ctx.get("status_lines") or [],
            to_remove=set(ctx.get("to_remove") or []),
            removed_link_map=ctx.get("removed_link_map") or {},
            removed_sessions=ctx.get("removed_sessions") or {},
            perform_cleanup=approve_unsubscribe,
            db=report_db,
        )
    finally:
        report_db.close()
