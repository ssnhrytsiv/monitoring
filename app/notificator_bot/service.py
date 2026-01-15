from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Tuple

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.notificator_bot import formatter
from app.notificator_bot.config import NOTIFIER_TARGET_IDS
from app.notificator_bot.models import NotifierMessage
from app.DAL import SessionLocal
from app.DAL import channels_operations as cho
from app.DAL import bot_links_operations as blo
from app.DAL import admins_operations as ao
from app.DAL.watch_events_operations import (
    fetch_unsent_events,
    mark_event_sent,
)
from app.DAL import watch_posts_operations as watch_posts_db
from app.utils.link_parser import extract_bot_username

log = logging.getLogger("notificator.service")

PRIORITY = {
    "pending": 0,
    "candidate": 0,
    "foreign": 0,
    "matched": 1,
    "views": 1,
    "edited_other": 1,
    "deleted": 1,
    "cancelled": 2,
    "expired": 3,
}


def _safe_payload(payload_json: str) -> dict:
    try:
        return json.loads(payload_json or "{}")
    except Exception:
        return {}


def _fetch_channel(channel_id: int) -> dict | None:
    db = SessionLocal()
    try:
        return cho.find_channel(db, channel_id)
    except Exception:
        return None
    finally:
        db.close()


def _admin_label(admin_id: int | None) -> str | None:
    if admin_id is None:
        return None
    row = ao.get_admin_label(None, admin_id)
    if not row:
        return str(admin_id)
    display, username = row
    if display:
        return str(display)
    if username:
        return str(username)
    return str(admin_id)


def _get_watch_info(watch_id: int) -> dict:
    return watch_posts_db.get_watch_info(watch_id)


def _channel_meta(channel_id: int, fallback_url: str | None) -> Tuple[str, str]:
    """
    Повертає (title, link)
    """
    title = f"cid={channel_id}"
    link = fallback_url or ""
    # 1) спробуємо звичайний канал
    db = SessionLocal()
    try:
        info = cho.find_channel(db, channel_id)
    except Exception:
        info = None
    finally:
        db.close()
    if info:
        if info.get("title"):
            title = info["title"]
        username = info.get("username")
        if username:
            link = f"https://t.me/{username}"

    # 2) якщо назва ще дефолтна – спробуємо як бота (по посиланню)
    if (not info or not info.get("title")) and fallback_url:
        bot_username = extract_bot_username(fallback_url)
        if bot_username:
            db = SessionLocal()
            try:
                bot_row = blo.get_bot_link_by_username(db, bot_username)
            except Exception:
                bot_row = None
            finally:
                db.close()
            if bot_row:
                if bot_row.get("title"):
                    title = bot_row["title"]
                elif bot_row.get("username"):
                    title = bot_row["username"]
                if bot_row.get("username"):
                    link = f"https://t.me/{bot_row['username']}"
                log.debug(
                    "notificator: bot_link resolved username=%s -> title=%s link=%s",
                    bot_username,
                    title,
                    link,
                )
            else:
                log.debug("notificator: bot_link not found for username=%s (fallback_url=%s)", bot_username, fallback_url)
    log.debug("notificator: channel_meta resolved cid=%s -> title=%s link=%s", channel_id, title, link)
    return title, link


def _admin_name(channel_info: dict | None, watch_info: dict) -> str:
    admin_id = watch_info.get("admin_id")
    label = _admin_label(admin_id) if admin_id is not None else None
    if label:
        return label

    if channel_info:
        if channel_info.get("owner_display"):
            return channel_info["owner_display"]
        if channel_info.get("owner_username"):
            return channel_info["owner_username"]

    # Якщо це бот – пробуємо взяти owner з bot_links
    bot_username = extract_bot_username(watch_info.get("source_url") or "")
    if bot_username:
        db = SessionLocal()
        try:
            bot_row = blo.get_bot_link_by_username(db, bot_username)
        except Exception:
            bot_row = None
        finally:
            db.close()
        if bot_row:
            if bot_row.get("owner_display"):
                return bot_row["owner_display"]
            if bot_row.get("owner_username"):
                return bot_row["owner_username"]

    created_by = watch_info.get("created_by")
    if created_by:
        return str(created_by)
    return "—"


def _build_line(event_type: str, payload: dict, watch_info: dict, title: str, link: str, created_at: str) -> str:
    desc = event_type
    if event_type == "views":
        views = payload.get("views")
        if views is None:
            views = watch_info.get("final_views")
        if views is not None:
            views_fmt = f"{views:,}".replace(",", " ")
            desc = f"Отстоял (просмотры: {views_fmt})"
        else:
            desc = "Отстоял (просмотры: —)"
    elif event_type == "deleted":
        desc = "Пост удалён"
    elif event_type == "edited_other":
        desc = "Пост отредактирован"
    elif event_type == "matched":
        desc = "Опубликован"
    elif event_type == "expired":
        desc = "Не вышел"
    elif event_type == "cancelled":
        desc = "Вотч отменён"
    elif event_type == "created":
        desc = "Вотч создан"
    elif event_type == "pending":
        desc = "Ожидает публикации"
    elif event_type == "candidate":
        sim = payload.get("similarity")
        if sim is not None:
            try:
                desc = f"Кандидат (похожесть: {float(sim):.3f})"
            except Exception:
                desc = "Кандидат"
        else:
            desc = "Кандидат"
    elif event_type == "foreign":
        sim = payload.get("similarity")
        reason = payload.get("reason") or "links_mismatch"
        details = []
        if sim is not None:
            try:
                details.append(f"похожесть: {float(sim):.3f}")
            except Exception:
                pass
        if reason:
            details.append(f"причина: {reason}")
        details_txt = f" ({'; '.join(details)})" if details else ""
        desc = f"Чужой пост{details_txt}"

    link_html = f'<a href="{link}">{title}</a>' if link else title
    if event_type == "expired":
        return f"{link_html} — {desc}"

    raw_time = created_at or watch_info.get("updated_at") or ""
    time_part = raw_time
    if raw_time:
        try:
            dt = datetime.fromisoformat(raw_time)
            time_part = dt.strftime("%H:%M:%S")
        except Exception:
            time_part = raw_time
    return f"{link_html} — {desc} (время: {time_part})"


def _parse_ts(ts: str | None) -> float:
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts).timestamp()
    except Exception:
        return 0.0


def _priority_of(ev_type: str) -> int:
    return PRIORITY.get(ev_type, 1)


def _add_entry(
    grouped: Dict[Tuple[str, str, int], Dict[int, dict]],
    key: Tuple[str, str, int],
    watch_id: int,
    entry: dict,
) -> None:
    bucket = grouped.setdefault(key, {})
    existing = bucket.get(watch_id)
    if not existing:
        bucket[watch_id] = entry
        return
    old_key = (_priority_of(existing["ev_type"]), existing.get("ts", 0.0), existing.get("watch_id", 0))
    new_key = (_priority_of(entry["ev_type"]), entry.get("ts", 0.0), entry.get("watch_id", 0))
    if new_key >= old_key:
        bucket[watch_id] = entry


def collect_grouped_events(
    exclude_ids: set[int] | None = None,
) -> Tuple[Dict[Tuple[str, str, int], Dict[int, dict]], List[int]]:
    """
    Читає unsent events, групує по (project, admin, group_id), повертає (grouped, event_ids).
    Всередині групи по кожному watch_id залишаємо найпріоритетніший запис.
    """
    events = fetch_unsent_events(limit=1000)
    log.debug("notificator: fetched unsent events count=%s", len(events))
    if not events:
        log.debug("notificator: no unsent events")
        return {}, []

    grouped: Dict[Tuple[str, str, int], Dict[int, dict]] = {}
    processed_ids: List[int] = []
    pending_groups: Dict[Tuple[str, str, int], set] = {}

    for ev_id, watch_id, ev_type, payload_json, created_at in events:
        if exclude_ids and ev_id in exclude_ids:
            continue
        watch_info = _get_watch_info(watch_id)
        project = watch_info.get("project") or "UNKNOWN"
        channel_id = watch_info.get("channel_id")
        if not channel_id:
            log.warning("notificator: skip event_id=%s watch_id=%s because channel_id missing", ev_id, watch_id)
            continue

        payload = _safe_payload(payload_json)
        chan_info = _fetch_channel(channel_id)
        title, link = _channel_meta(channel_id, watch_info.get("source_url") or payload.get("source_url"))
        admin = _admin_name(chan_info, watch_info)
        gid = watch_info.get("group_id") or 0
        key = (project, admin, gid)
        ts = _parse_ts(created_at)

        views_val = None
        if ev_type == "views":
            try:
                views_val = int(payload.get("views"))
            except Exception:
                views_val = watch_info.get("final_views")
        line = _build_line(ev_type, payload, watch_info, title, link, created_at)
        _add_entry(
            grouped,
            key,
            watch_id,
            {
                "line": line,
                "ev_type": ev_type,
                "ts": ts,
                "watch_id": watch_id,
                "views": views_val,
            },
        )
        processed_ids.append(ev_id)
        if gid:
            pending_groups.setdefault(key, set()).add(gid)

    # Додаємо всі вотчі з цієї ж групи (повний список), якщо по адміну вже була хоч одна подія
    for key, gids in pending_groups.items():
        project, admin, _ = key
        for gid in gids:
            try:
                rows = watch_posts_db.fetch_watches_by_group(gid)
            except Exception as e:
                log.error("notificator: fetch_watches_by_group failed gid=%s: %s", gid, e)
                continue
            for row in rows:
                watch_id = row.get("id")
                if not watch_id:
                    continue
                chan_id = row.get("channel_id")
                if not chan_id:
                    continue
                status = (row.get("status") or "").lower()
                deleted_at = row.get("deleted_at")
                ev_type = {
                    "matched": "matched",
                    "expired": "expired",
                    "cancelled": "cancelled",
                    "pending": "pending",
                    "deleted": "deleted",
                    "edited": "edited_other",
                    # done після переглядів показуємо як “Отстоял просмотры”
                    "done": "views",
                }.get(status, "pending")
                chan_info = _fetch_channel(chan_id)
                title, link = _channel_meta(chan_id, row.get("source_url"))
                views_val = None
                if ev_type == "views":
                    try:
                        views_val = int(row.get("final_views"))
                    except Exception:
                        views_val = row.get("final_views")
                line = _build_line(
                    ev_type,
                    {"views": row.get("final_views")},
                    {
                        "source_url": row.get("source_url"),
                        "updated_at": row.get("updated_at") or row.get("created_at"),
                        "group_id": gid,
                        "status": status,
                        "final_views": row.get("final_views"),
                    },
                    title,
                    link,
                    row.get("updated_at") or row.get("created_at") or "",
                )
                _add_entry(
                    grouped,
                    key,
                    watch_id,
                    {
                        "line": line,
                        "ev_type": ev_type,
                        "ts": _parse_ts(row.get("updated_at") or row.get("created_at")),
                        "watch_id": watch_id,
                        "views": views_val,
                    },
                )

    return grouped, processed_ids


def _get_prev_message(chat_id: int, project: str, admin: str, group_id: int) -> int | None:
    db = SessionLocal()
    try:
        row = (
            db.query(NotifierMessage.message_id)
            .filter(
                NotifierMessage.chat_id == chat_id,
                NotifierMessage.project == project,
                NotifierMessage.admin == admin,
                NotifierMessage.group_id == group_id,
            )
            .one_or_none()
        )
        return row[0] if row else None
    finally:
        db.close()


def _upsert_message(chat_id: int, project: str, admin: str, group_id: int, message_id: int) -> None:
    now_ts = int(time.time())
    db = SessionLocal()
    try:
        obj = (
            db.query(NotifierMessage)
            .filter(
                NotifierMessage.chat_id == chat_id,
                NotifierMessage.project == project,
                NotifierMessage.admin == admin,
                NotifierMessage.group_id == group_id,
            )
            .one_or_none()
        )
        if obj:
            obj.message_id = message_id
            obj.updated_at = now_ts
        else:
            obj = NotifierMessage(
                chat_id=chat_id,
                project=project,
                admin=admin,
                group_id=group_id,
                message_id=message_id,
                updated_at=now_ts,
            )
            db.add(obj)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def send_notifications(bot: Bot, debounce_sec: int = 60) -> None:
    """
    Якщо є події, збираємо їх протягом debounce_sec, потім шлемо одним батчем.
    Щоб не спамити БД, робимо лише два читання: на старті та після дебаунса.
    """
    grouped, event_ids = collect_grouped_events()
    if not grouped or not event_ids:
        log.debug("notificator: nothing to send")
        return

    if not NOTIFIER_TARGET_IDS:
        log.warning("notificator: NOTIFIER_TARGET_IDS is empty; skip sending, events stay unsent (ids=%s)", event_ids)
        return

    log.info(
        "notificator: collected first batch projects=%s total_events=%s debounce=%ss",
        list(grouped.keys()),
        len(event_ids),
        debounce_sec,
    )

    # Чекаємо дебаунс і читаємо ще раз, щоб добрати хвилю подій
    await asyncio.sleep(max(1, debounce_sec))
    exclude_ids = set(event_ids)
    more_grouped, more_ids = collect_grouped_events(exclude_ids=exclude_ids)
    if more_grouped and more_ids:
        for key, bucket in more_grouped.items():
            for watch_id, entry in bucket.items():
                _add_entry(grouped, key, watch_id, entry)
        event_ids.extend(more_ids)
        log.info(
            "notificator: merged after debounce: +%s events, total=%s",
            len(more_ids),
            len(event_ids),
        )
    else:
        log.debug("notificator: no new events after debounce (exclude=%s)", len(exclude_ids))

    # Надсилаємо по кожній групі (project, admin, group_id)
    for (project, admin, group_id), bucket in grouped.items():
        entries = list(bucket.values())
        # Сортуємо: спочатку pending/matched, потім expired
        entries.sort(
            key=lambda x: (
                _priority_of(x.get("ev_type")),
                x.get("ts", 0.0),
                x.get("watch_id", 0),
            )
        )
        lines = [e["line"] for e in entries]
        views_values: List[int] = []
        for e in entries:
            v = e.get("views")
            if v is None:
                continue
            try:
                views_values.append(int(v))
            except Exception:
                continue
        total_views = sum(views_values) if views_values else None
        text = formatter.format_admin_message(project, admin, lines, total_views)

        for chat_id in NOTIFIER_TARGET_IDS:
            # Якщо є попереднє повідомлення по цьому group_id – видалимо
            if group_id:
                prev_msg_id = _get_prev_message(chat_id, project, admin, group_id)
                if prev_msg_id:
                    try:
                        await bot.delete_message(chat_id=chat_id, message_id=prev_msg_id)
                        log.debug(
                            "notificator: deleted previous message chat=%s project=%s admin=%s group_id=%s msg_id=%s",
                            chat_id,
                            project,
                            admin,
                            group_id,
                            prev_msg_id,
                        )
                    except TelegramAPIError as e:
                        log.warning(
                            "notificator: failed to delete old message chat=%s project=%s admin=%s group_id=%s: %s",
                            chat_id,
                            project,
                            admin,
                            group_id,
                            e,
                        )
                    except Exception as e:
                        log.exception(
                            "notificator: unexpected delete error chat=%s project=%s admin=%s group_id=%s: %s",
                            chat_id,
                            project,
                            admin,
                            group_id,
                            e,
                        )

            try:
                sent_msg = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                log.info(
                    "notificator: sent notification to %s for project=%s admin=%s lines=%s group_id=%s",
                    chat_id,
                    project,
                    admin,
                    len(lines),
                    group_id,
                )
                if group_id:
                    _upsert_message(chat_id, project, admin, group_id, sent_msg.message_id)
            except TelegramAPIError as e:
                log.error("Failed to send notify to %s (project=%s admin=%s): %s", chat_id, project, admin, e)
            except Exception as e:
                log.exception("Unexpected send error to %s (project=%s admin=%s): %s", chat_id, project, admin, e)

    # Позначаємо відправленими (уникаємо дублів) (використовуємо перший chat_id або 0)
    sent_to = NOTIFIER_TARGET_IDS[0] if NOTIFIER_TARGET_IDS else 0
    for ev_id in dict.fromkeys(event_ids):
        try:
            mark_event_sent(ev_id, sent_to)
        except Exception as e:
            log.error("mark_event_sent failed for event_id=%s: %s", ev_id, e)
