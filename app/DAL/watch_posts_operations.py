from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import logging
import os

from sqlalchemy import or_, select, update, text

import json
from app.notificator_bot.db.posts_watch_result_models import (
    SessionLocal as WatchSessionLocal,
    WatchPost,
    WatchGroup,
)
from app.DAL.watch_processing_operations import get_session_for_source_url as process_get_session_for_source_url
from app.DAL.watch_events_operations import insert_watch_event
from app.services import watch_event_reason_codes
from app.admin_bot.db import models as m
from app.utils.time_utils import MOSCOW_TIME_FORMAT, moscow_now

# Дозволені статуси вотчів
ALLOWED_STATUSES: Dict[str, str] = {
    "pending": "pending",
    "matched": "matched",
    "expired": "expired",
    "views_access_lost": "views_access_lost",
}

log = logging.getLogger(__name__)
_ACTIVE_WATCH_INDEX_CHECKED: bool = False


def _now_msk_str() -> str:
    return moscow_now().strftime(MOSCOW_TIME_FORMAT)


def _ensure_active_watch_unique_index() -> None:
    """
    Ensure uq_active_watch matches business rule:
    unique per (channel_id, template_id, expected_text_hash, time_window_end)
    for active statuses pending|matched.
    """
    global _ACTIVE_WATCH_INDEX_CHECKED
    if _ACTIVE_WATCH_INDEX_CHECKED:
        return

    db = WatchSessionLocal()
    try:
        bind = db.get_bind()
        if bind is None or bind.dialect.name != "sqlite":
            _ACTIVE_WATCH_INDEX_CHECKED = True
            return

        row = db.execute(
            text("SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_active_watch'")
        ).first()
        current_sql = str(row[0] or "") if row else ""
        normalized_sql = " ".join(current_sql.lower().split())
        expected_fragment = "on watch_posts(channel_id, template_id, expected_text_hash, time_window_end)"
        if expected_fragment in normalized_sql:
            _ACTIVE_WATCH_INDEX_CHECKED = True
            return

        db.execute(text("DROP INDEX IF EXISTS uq_active_watch"))
        db.execute(
            text(
                """
                CREATE UNIQUE INDEX uq_active_watch
                ON watch_posts(channel_id, template_id, expected_text_hash, time_window_end)
                WHERE status IN ('pending','matched')
                """
            )
        )
        db.commit()
        log.info("watch_posts: migrated uq_active_watch to include time_window_end")
        _ACTIVE_WATCH_INDEX_CHECKED = True
    except Exception:
        db.rollback()
        log.warning("watch_posts: failed to ensure uq_active_watch index", exc_info=True)
    finally:
        db.close()


def _parse_int_ids_csv(raw_value: str | None) -> List[int]:
    result: List[int] = []
    seen: set[int] = set()
    if not raw_value:
        return result
    for raw_part in str(raw_value).split(","):
        token = raw_part.strip()
        if not token:
            continue
        try:
            value = int(token)
        except Exception:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _shared_watch_viewer_ids() -> List[int]:
    env_ids = _parse_int_ids_csv(os.getenv("WATCH_SHARED_VIEWER_IDS"))
    if env_ids:
        return env_ids
    # Default shared visibility for two operator accounts.
    return [300851736, 7384359075]


def _resolve_visible_creator_ids(viewer_user_id: int) -> List[int]:
    try:
        normalized_viewer_id = int(viewer_user_id)
    except Exception:
        return []
    shared_ids = _shared_watch_viewer_ids()
    if normalized_viewer_id in shared_ids:
        return shared_ids
    return [normalized_viewer_id]


def _time_window_key(value: Any) -> Optional[str]:
    if value is None:
        return None
    raw = str(value)
    return raw[:16] if len(raw) >= 16 else raw


def list_active_watches(
    user_id: int,
    statuses: Optional[List[str]] = None,
) -> List[Tuple[int, Optional[int], str, Optional[str], Optional[int], Optional[int], Optional[int]]]:
    """
    Повертає активні вотчі для видимої зони користувача:
    - власні created_by
    - або shared created_by (для WATCH_SHARED_VIEWER_IDS)
    - плюс created_by IS NULL
    з фільтром статусів.
    Результат відсортований за id DESC.
    """
    if not statuses:
        statuses = ["pending", "matched"]

    filtered_statuses = [ALLOWED_STATUSES[s] for s in statuses if s in ALLOWED_STATUSES]
    if not filtered_statuses:
        filtered_statuses = ["pending", "matched"]
    visible_creator_ids = _resolve_visible_creator_ids(user_id)
    if visible_creator_ids:
        created_by_filter = WatchPost.created_by.in_(visible_creator_ids)
    else:
        created_by_filter = WatchPost.created_by == user_id

    db = WatchSessionLocal()
    try:
        rows = db.execute(
            select(
                WatchPost.id,
                WatchPost.template_id,
                WatchPost.status,
                WatchPost.time_window_end,
                WatchPost.created_by,
                WatchPost.channel_id,
                WatchPost.group_id,
            )
            .where(
                or_(created_by_filter, WatchPost.created_by.is_(None)),
                WatchPost.status.in_(filtered_statuses),
            )
            .order_by(WatchPost.id.desc())
        ).all()
    finally:
        db.close()

    result: List[Tuple[int, Optional[int], str, Optional[str], Optional[int], Optional[int], Optional[int]]] = []
    for row in rows:
        result.append(
            (
                int(row.id),
                int(row.template_id) if row.template_id is not None else None,
                str(row.status or ""),
                str(row.time_window_end) if row.time_window_end else None,
                int(row.created_by) if row.created_by is not None else None,
                int(row.channel_id) if row.channel_id is not None else None,
                int(row.group_id) if row.group_id is not None else None,
            )
        )
    return result


def get_watch_by_id(watch_id: int) -> Optional[Tuple[int, Optional[int], str, Optional[str], Any, Optional[int], Optional[str]]]:
    """
    Повертає один watch за id або None, якщо не знайдено.
    """
    db = WatchSessionLocal()
    try:
        row = db.execute(
            select(
                WatchPost.id,
                WatchPost.template_id,
                WatchPost.status,
                WatchPost.time_window_end,
                WatchPost.created_by,
                WatchPost.channel_id,
                WatchPost.source_url,
            ).where(WatchPost.id == int(watch_id)).limit(1)
        ).first()
    finally:
        db.close()
    if not row:
        return None
    return (
        int(row.id),
        int(row.template_id) if row.template_id is not None else None,
        str(row.status or ""),
        row.time_window_end,
        row.created_by,
        int(row.channel_id) if row.channel_id is not None else None,
        row.source_url,
    )


def get_group_leader_key(watch_id: int) -> Optional[Tuple[Optional[int], Optional[str], Any, Optional[int]]]:
    """
    Повертає (template_id, tw_key, created_by, channel_id) для watch_id.
    """
    db = WatchSessionLocal()
    try:
        row = db.execute(
            select(
                WatchPost.template_id,
                WatchPost.time_window_end,
                WatchPost.created_by,
                WatchPost.channel_id,
            ).where(WatchPost.id == int(watch_id)).limit(1)
        ).first()
    finally:
        db.close()
    if not row:
        return None
    template_id = int(row.template_id) if row.template_id is not None else None
    tw_key = _time_window_key(row.time_window_end)
    channel_id = int(row.channel_id) if row.channel_id is not None else None
    return template_id, tw_key, row.created_by, channel_id


def get_group_leader_for_watch(watch_id: int) -> Optional[int]:
    """
    Повертає мінімальний watch_id за ключем групи (template_id + tw_key + created_by).
    """
    leader_key = get_group_leader_key(watch_id)
    if not leader_key:
        return None
    template_id, tw_key, created_by, _ = leader_key
    db = WatchSessionLocal()
    try:
        row = db.execute(
            select(WatchPost.id)
            .where(
                WatchPost.template_id == template_id,
                WatchPost.time_window_end == tw_key,
                WatchPost.created_by == created_by,
            )
            .order_by(WatchPost.id.asc())
            .limit(1)
        ).first()
    finally:
        db.close()
    if not row:
        return None
    return int(row.id)


def load_group_items(
    template_id: Optional[int],
    tw_key: Optional[str],
    created_by: Any,
    statuses: Optional[List[str]] = None,
) -> List[Tuple[int, int, str, str, int]]:
    """
    Повертає вотчі групи у форматі (wid, channel_id, status, source_url, template_id).
    """
    status_list = statuses or ["pending", "matched"]
    status_list = [s for s in status_list if s in ALLOWED_STATUSES]
    if not status_list:
        status_list = ["pending", "matched"]

    db = WatchSessionLocal()
    try:
        rows = db.execute(
            select(
                WatchPost.id,
                WatchPost.template_id,
                WatchPost.status,
                WatchPost.time_window_end,
                WatchPost.created_by,
                WatchPost.channel_id,
                WatchPost.source_url,
            )
            .where(
                WatchPost.status.in_(status_list),
                WatchPost.template_id == template_id,
                or_(WatchPost.created_by == created_by, WatchPost.created_by.is_(None)),
            )
            .order_by(WatchPost.id.desc())
        ).all()
    finally:
        db.close()

    items: List[Tuple[int, int, str, str, int]] = []
    for wid, tid_row, status_value, tw_row, created_row, cid, source_url in rows:
        tid_row_int = int(tid_row) if tid_row is not None else None
        if tid_row_int != template_id:
            continue
        tw_row_key = _time_window_key(tw_row)
        if tw_row_key != tw_key:
            continue
        wid_int = int(wid)
        cid_int = int(cid) if cid is not None else 0
        status_str = str(status_value or "").strip()
        src = str(source_url).strip() if source_url else ""
        items.append((wid_int, cid_int, status_str, src, tid_row_int if tid_row_int is not None else 0))
    return items


def load_group_channels(leader_watch_id: int, statuses: Optional[List[str]] = None) -> List[int]:
    """
    Повертає channel_id для всіх watch'ів групи leader_watch_id.
    """
    status_list = statuses or ["pending", "matched", "expired"]
    status_list = [s for s in status_list if s in ALLOWED_STATUSES]
    if not status_list:
        status_list = ["pending", "matched", "expired"]

    db = WatchSessionLocal()
    try:
        leader = db.execute(
            select(
                WatchPost.template_id,
                WatchPost.time_window_end,
                WatchPost.created_by,
            ).where(WatchPost.id == int(leader_watch_id)).limit(1)
        ).first()
        if not leader:
            return []

        rows = db.execute(
            select(WatchPost.channel_id).where(
                WatchPost.template_id == leader.template_id,
                WatchPost.time_window_end == leader.time_window_end,
                WatchPost.created_by == leader.created_by,
                WatchPost.status.in_(status_list),
            )
        ).all()
    finally:
        db.close()

    channels: List[int] = []
    for cid in rows:
        try:
            val = int(cid[0])
            if val:
                channels.append(val)
        except Exception:
            continue
    return channels


def cancel_group_watches(leader_watch_id: int) -> bool:
    """
    Ставит pending/matched/expired -> cancelled для групи leader_watch_id.
    """
    db = WatchSessionLocal()
    try:
        leader = db.execute(
            select(
                WatchPost.template_id,
                WatchPost.time_window_end,
                WatchPost.created_by,
            ).where(WatchPost.id == int(leader_watch_id)).limit(1)
        ).first()
        if not leader:
            return False
        now_str = _now_msk_str()
        res = db.execute(
            update(WatchPost)
            .where(
                WatchPost.template_id == leader.template_id,
                WatchPost.time_window_end == leader.time_window_end,
                WatchPost.created_by == leader.created_by,
                WatchPost.status.in_(["pending", "matched", "expired"]),
            )
            .values(status="cancelled", updated_at=now_str)
        )
        db.commit()
        return res.rowcount > 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def set_watch_status_pending(watch_id: int) -> bool:
    """
    Оновлює статус вотчу на pending і проставляє updated_at.
    """
    db = WatchSessionLocal()
    try:
        now_str = _now_msk_str()
        res = db.execute(
            update(WatchPost)
            .where(WatchPost.id == int(watch_id))
            .values(status="pending", updated_at=now_str)
        )
        db.commit()
        return res.rowcount > 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def update_watch_time_window(
    watch_id: int,
    time_window_start: str,
    time_window_end: str,
) -> bool:
    """
    Оновлює time_window_start/time_window_end та updated_at для watch_posts.id = watch_id.
    """
    db = WatchSessionLocal()
    try:
        now_str = _now_msk_str()
        res = db.execute(
            update(WatchPost)
            .where(WatchPost.id == int(watch_id))
            .values(
                time_window_start=time_window_start,
                time_window_end=time_window_end,
                updated_at=now_str,
            )
        )
        db.commit()
        return res.rowcount > 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def update_watch_source_url(watch_id: int, source_url: str) -> bool:
    """
    Оновлює source_url та updated_at для watch_posts.id = watch_id.
    """
    db = WatchSessionLocal()
    try:
        now_str = _now_msk_str()
        res = db.execute(
            update(WatchPost)
            .where(WatchPost.id == int(watch_id))
            .values(source_url=source_url, updated_at=now_str)
        )
        db.commit()
        return res.rowcount > 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def group_active(
    rows: List[Tuple[Any, Any, Any, Any, Any, Any, Any]]
) -> Dict[Tuple[Optional[int], Optional[int], Optional[str], Optional[int]], List[Tuple[int, int]]]:
    """
    Групує активні вотчі за:
      - template_id
      - time_window_end, округленим до хвилини (YYYY-MM-DD HH:MM)
      - created_by

    Повертає dict: ключ = (template_id, tw_end_minute, created_by), значення = список (watch_id, channel_id).
    """
    groups: Dict[Tuple[Optional[int], Optional[int], Optional[str], Optional[int]], List[Tuple[int, int]]] = {}

    for watch_id, template_id, status, time_window_end, created_by, channel_id, group_id in rows:
        template_id_int = int(template_id) if template_id is not None else None
        group_id_int = int(group_id) if group_id is not None else None

        if time_window_end is None:
            tw_end_string: Optional[str] = None
        else:
            raw = str(time_window_end)
            tw_end_string = raw[:16] if len(raw) >= 16 else raw

        created_by_int = int(created_by) if created_by is not None else None
        watch_id_int = int(watch_id)
        channel_id_int = int(channel_id) if channel_id is not None else 0

        key = (group_id_int, template_id_int, tw_end_string, created_by_int)
        groups.setdefault(key, []).append((watch_id_int, channel_id_int))

    return groups


def get_watch_channel_id(watch_id: int) -> Optional[int]:
    """
    Повертає channel_id для вказаного watch_id.
    """
    db = WatchSessionLocal()
    try:
        row = db.execute(
            select(WatchPost.channel_id).where(WatchPost.id == int(watch_id)).limit(1)
        ).first()
    finally:
        db.close()
    if not row or row[0] is None:
        return None
    try:
        return int(row[0])
    except Exception:
        return None


def get_watch_source_url(watch_id: int) -> Optional[str]:
    """
    Повертає source_url для вказаного watch_id.
    """
    db = WatchSessionLocal()
    try:
        row = db.execute(
            select(WatchPost.source_url).where(WatchPost.id == int(watch_id)).limit(1)
        ).first()
    finally:
        db.close()
    if not row or row[0] is None:
        return None
    val = row[0]
    return str(val) if val else None


def manual_mark_matched(
    watch_id: int,
    channel_id: int,
    message_id: int,
    coverage_check_at: Optional[str],
    matched_session: Optional[str],
    source_url: Optional[str] = None,
    is_manual: bool = False,
) -> bool:
    """
    Примусово ставить вотч у matched, додає подію matched і повертає True при успіху.
    Використовується для ручного матчу (бот).
    """
    session_label = matched_session
    if not session_label and source_url:
        try:
            session_label = process_get_session_for_source_url(source_url)
        except Exception:
            session_label = None
    if not session_label:
        session_label = "MAIN"

    db = WatchSessionLocal()
    try:
        now_str = _now_msk_str()
        res = db.execute(
            update(WatchPost)
            .where(WatchPost.id == watch_id, WatchPost.status.in_(["pending", "expired"]))
            .values(
                matched_message_id=message_id,
                matched_at=now_str,
                coverage_check_at=coverage_check_at,
                matched_session=session_label,
                status="matched",
                updated_at=now_str,
            )
        )
        db.commit()
        if res.rowcount == 0:
            return False
    except Exception:
        db.rollback()
        return False
    finally:
        db.close()

    try:
        payload = json.dumps(
            {
                "watch_id": watch_id,
                "channel_id": channel_id,
                "message_id": message_id,
                "session": session_label,
                "manual": bool(is_manual),
                "reason_code": watch_event_reason_codes.WATCH_EVENT_REASON_CODE_MANUAL_MATCHED,
            }
        )
        insert_watch_event(
            watch_id,
            "matched",
            payload,
        )
    except Exception:
        # подію логувати необов'язково; сам матч уже збережено
        return True

    return True


def get_watch_is_reply(watch_id: int) -> bool:
    db = WatchSessionLocal()
    try:
        row = db.execute(
            select(WatchPost.is_reply).where(WatchPost.id == int(watch_id)).limit(1)
        ).first()
    finally:
        db.close()
    if not row:
        return False
    return bool(row[0])


def create_watch_group(
    project: Optional[str] = None,
    title: Optional[str] = None,
    created_by: Optional[int] = None,
    created_via: Optional[str] = None,
    admin_id: Optional[int] = None,
    network_id: Optional[int] = None,
) -> int:
    db = WatchSessionLocal()
    try:
        now_str = _now_msk_str()
        obj = WatchGroup(
            project=project,
            title=title,
            created_by=created_by,
            created_via=created_via,
            created_at=now_str,
            admin_id=admin_id,
            network_id=network_id,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        log.info(
            "watch_group.create id=%s title=%r project=%r admin_id=%s network_id=%s created_by=%s via=%s",
            obj.id,
            obj.title,
            obj.project,
            obj.admin_id,
            obj.network_id,
            obj.created_by,
            obj.created_via,
        )
        return int(obj.id)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_watch(
    channel_id: int,
    group_id: Optional[int] = None,
    template_id: Optional[int] = None,
    expected_text_hash: Optional[str] = None,
    expected_text_norm_len: Optional[int] = None,
    expected_links_json: Optional[str] = None,
    expected_media_fingerprint: Optional[str] = None,
    time_window_start: Optional[str] = None,
    time_window_end: Optional[str] = None,
    source_url: Optional[str] = None,
    created_by: Optional[int] = None,
    created_via: Optional[str] = None,
    project: Optional[str] = None,
    admin_id: Optional[int] = None,
    network_id: Optional[int] = None,
    posted_at: Optional[str] = None,
    views_at_post: Optional[int] = None,
    subs_at_post: Optional[int] = None,
    cpm_at_post: Optional[float] = None,
    price_at_post: Optional[float] = None,
    title: Optional[str] = None,
    is_reply: bool = False,
) -> int:
    _ensure_active_watch_unique_index()
    db = WatchSessionLocal()
    try:
        now_str = _now_msk_str()
        wp = WatchPost(
            channel_id=channel_id,
            group_id=group_id,
            template_id=template_id,
            expected_text_hash=expected_text_hash,
            expected_text_norm_len=expected_text_norm_len,
            expected_links_json=expected_links_json,
            expected_media_fingerprint=expected_media_fingerprint,
            time_window_start=time_window_start,
            time_window_end=time_window_end,
            status="pending",
            created_at=now_str,
            updated_at=now_str,
            source_url=source_url,
            created_by=created_by,
            created_via=created_via,
            project=project,
            admin_id=admin_id,
            network_id=network_id,
            posted_at=posted_at,
            views_at_post=views_at_post,
            subs_at_post=subs_at_post,
            cpm_at_post=cpm_at_post,
            price_at_post=price_at_post,
            title=title,
            is_reply=bool(is_reply),
        )
        db.add(wp)
        db.commit()
        db.refresh(wp)
        log.info(
            "watch.create id=%s group_id=%s channel_id=%s template_id=%s title=%r project=%r admin_id=%s network_id=%s",
            wp.id,
            wp.group_id,
            wp.channel_id,
            wp.template_id,
            wp.title,
            wp.project,
            wp.admin_id,
            wp.network_id,
        )
        return int(wp.id)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def bulk_create_watches(items: List[Dict[str, Any]]) -> List[int]:
    """
    Пакетно створює watch_posts (status=pending) за один commit.
    Очікує список словників з ключами, сумісними з create_watch (окрім status/timestamps).
    Повертає список створених id у тому ж порядку, що і items.
    """
    if not items:
        return []

    _ensure_active_watch_unique_index()
    db = WatchSessionLocal()
    try:
        now_str = _now_msk_str()
        objects: List[WatchPost] = []
        for item in items:
            obj = WatchPost(
                channel_id=item.get("channel_id"),
                group_id=item.get("group_id"),
                template_id=item.get("template_id"),
                expected_text_hash=item.get("expected_text_hash"),
                expected_text_norm_len=item.get("expected_text_norm_len"),
                expected_links_json=item.get("expected_links_json"),
                expected_media_fingerprint=item.get("expected_media_fingerprint"),
                time_window_start=item.get("time_window_start"),
                time_window_end=item.get("time_window_end"),
                status="pending",
                created_at=now_str,
                updated_at=now_str,
                source_url=item.get("source_url"),
                created_by=item.get("created_by"),
                created_via=item.get("created_via"),
                project=item.get("project"),
                admin_id=item.get("admin_id"),
                network_id=item.get("network_id"),
                posted_at=item.get("posted_at"),
                views_at_post=item.get("views_at_post"),
                subs_at_post=item.get("subs_at_post"),
                cpm_at_post=item.get("cpm_at_post"),
                price_at_post=item.get("price_at_post"),
                title=item.get("title"),
                is_reply=bool(item.get("is_reply")),
            )
            objects.append(obj)

        db.add_all(objects)
        db.flush()
        created_ids = [int(obj.id) for obj in objects]
        db.commit()
        return created_ids
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def cancel_watch(watch_id: int) -> None:
    db = WatchSessionLocal()
    try:
        now_str = _now_msk_str()
        db.execute(
            update(WatchPost)
            .where(
                WatchPost.id == int(watch_id),
                WatchPost.status.in_(["pending", "matched"]),
            )
            .values(status="cancelled", updated_at=now_str)
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_watch_links_or_template_links(watch_id: int) -> List[str]:
    """
    Повертає links_json із watch_posts або, якщо порожньо, links із post_template.
    """
    db = WatchSessionLocal()
    try:
        row = db.execute(
            select(
                WatchPost.expected_links_json,
                WatchPost.template_id,
            ).where(WatchPost.id == int(watch_id)).limit(1)
        ).first()
        links_json = None
        template_id = None
        if row:
            links_json = row[0]
            template_id = row[1]
        if not links_json and template_id:
            tpl = db.execute(
                select(m.PostTemplate.links).where(m.PostTemplate.id == int(template_id)).limit(1)
            ).first()
            links_json = tpl[0] if tpl else None
    finally:
        db.close()
    if not links_json:
        return []
    try:
        data = json.loads(links_json)
        if isinstance(data, list):
            seen = set()
            out: List[str] = []
            for x in data:
                u = str(x).strip()
                if u and u not in seen:
                    seen.add(u)
                    out.append(u)
            return out
    except Exception:
        return []
    return []


def find_active_duplicate(
    channel_id: int,
    template_id: Optional[int],
    expected_text_hash: Optional[str],
    time_window_end: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Перевіряє, чи існує активний (pending|matched) watch із тим самим ключем.
    Повертає словник з короткою інформацією або None.
    """
    _ensure_active_watch_unique_index()
    normalized_time_window_end = str(time_window_end).strip() if time_window_end is not None else None
    if normalized_time_window_end == "":
        normalized_time_window_end = None

    db = WatchSessionLocal()
    try:
        row = db.execute(
            select(
                WatchPost.id,
                WatchPost.status,
                WatchPost.created_at,
                WatchPost.time_window_end,
                WatchPost.matched_message_id,
            ).where(
                WatchPost.channel_id == int(channel_id),
                (
                    (WatchPost.template_id.is_(None) if template_id is None else WatchPost.template_id == int(template_id))
                ),
                (
                    (WatchPost.expected_text_hash.is_(None) if expected_text_hash is None else WatchPost.expected_text_hash == expected_text_hash)
                ),
                (
                    (
                        WatchPost.time_window_end.is_(None)
                        if normalized_time_window_end is None
                        else WatchPost.time_window_end == normalized_time_window_end
                    )
                ),
                WatchPost.status.in_(["pending", "matched"]),
            )
            .order_by(WatchPost.id.desc())
            .limit(1)
        ).first()
    finally:
        db.close()
    if not row:
        return None
    return {
        "id": int(row.id),
        "status": str(row.status or ""),
        "created_at": row.created_at,
        "time_window_end": row.time_window_end,
        "matched_message_id": row.matched_message_id,
    }


def find_active_duplicates_bulk(
    channel_ids: List[int],
    template_id: Optional[int],
    expected_text_hash: Optional[str],
    time_window_end: Optional[str] = None,
) -> Dict[int, Dict[str, Any]]:
    """
    Пакетно повертає активні дублікати (pending|matched) для channel_ids.
    Ключ словника — channel_id, значення — найновіший duplicate-рядок для каналу.
    """
    clean_channel_ids = []
    seen_channel_ids: set[int] = set()
    for raw_channel_id in channel_ids or []:
        try:
            channel_id = int(raw_channel_id)
        except Exception:
            continue
        if channel_id <= 0 or channel_id in seen_channel_ids:
            continue
        seen_channel_ids.add(channel_id)
        clean_channel_ids.append(channel_id)

    if not clean_channel_ids:
        return {}

    _ensure_active_watch_unique_index()
    normalized_time_window_end = str(time_window_end).strip() if time_window_end is not None else None
    if normalized_time_window_end == "":
        normalized_time_window_end = None

    db = WatchSessionLocal()
    try:
        rows = db.execute(
            select(
                WatchPost.id,
                WatchPost.channel_id,
                WatchPost.status,
                WatchPost.created_at,
                WatchPost.time_window_end,
                WatchPost.matched_message_id,
            ).where(
                WatchPost.channel_id.in_(clean_channel_ids),
                (
                    (WatchPost.template_id.is_(None) if template_id is None else WatchPost.template_id == int(template_id))
                ),
                (
                    (WatchPost.expected_text_hash.is_(None) if expected_text_hash is None else WatchPost.expected_text_hash == expected_text_hash)
                ),
                (
                    (
                        WatchPost.time_window_end.is_(None)
                        if normalized_time_window_end is None
                        else WatchPost.time_window_end == normalized_time_window_end
                    )
                ),
                WatchPost.status.in_(["pending", "matched"]),
            )
            .order_by(WatchPost.channel_id.asc(), WatchPost.id.desc())
        ).all()
    finally:
        db.close()

    result: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        channel_id = int(row.channel_id)
        if channel_id in result:
            continue
        result[channel_id] = {
            "id": int(row.id),
            "channel_id": channel_id,
            "status": str(row.status or ""),
            "created_at": row.created_at,
            "time_window_end": row.time_window_end,
            "matched_message_id": row.matched_message_id,
        }
    return result


def get_watch_info(watch_id: int) -> Dict[str, Any]:
    """
    Повертає інформацію про watch_posts.id, мінімально необхідну для нотифікацій.
    """
    db = WatchSessionLocal()
    try:
        row = db.execute(
            select(
                WatchPost.channel_id,
                WatchPost.project,
                WatchPost.matched_session,
                WatchPost.created_by,
                WatchPost.created_via,
                WatchPost.source_url,
                WatchPost.status,
                WatchPost.matched_at,
                WatchPost.coverage_check_at,
                WatchPost.deleted_at,
                WatchPost.updated_at,
                WatchPost.group_id,
                WatchPost.final_views,
                WatchPost.template_id,
                WatchPost.expected_links_json,
                WatchPost.expected_text_hash,
                WatchPost.time_window_start,
                WatchPost.admin_id,
                WatchPost.title,
                WatchPost.is_reply,
            ).where(WatchPost.id == int(watch_id)).limit(1)
        ).first()
    finally:
        db.close()
    if not row:
        return {}
    return {
        "channel_id": row.channel_id,
        "project": row.project,
        "matched_session": row.matched_session,
        "created_by": row.created_by,
        "created_via": row.created_via,
        "source_url": row.source_url,
        "status": row.status,
        "matched_at": row.matched_at,
        "coverage_check_at": row.coverage_check_at,
        "deleted_at": row.deleted_at,
        "updated_at": row.updated_at,
        "group_id": row.group_id,
        "final_views": row.final_views,
        "template_id": row.template_id,
        "expected_links_json": row.expected_links_json,
        "expected_text_hash": row.expected_text_hash,
        "time_window_start": row.time_window_start,
        "admin_id": row.admin_id,
        "title": row.title,
        "is_reply": bool(row.is_reply),
    }


def fetch_watches_by_group(group_id: int) -> List[Dict[str, Any]]:
    """
    Повертає всі вотчі групи у вигляді словників.
    """
    db = WatchSessionLocal()
    try:
        rows = db.execute(
            select(
                WatchPost.id,
                WatchPost.channel_id,
                WatchPost.source_url,
                WatchPost.project,
                WatchPost.status,
                WatchPost.created_at,
                WatchPost.updated_at,
                WatchPost.matched_at,
                WatchPost.coverage_check_at,
                WatchPost.deleted_at,
                WatchPost.final_views,
                WatchPost.title,
                WatchPost.is_reply,
                WatchPost.matched_session,
                WatchPost.template_id,
            )
            .where(WatchPost.group_id == int(group_id))
            .order_by(WatchPost.id.asc())
        ).all()
    finally:
        db.close()
    result: List[Dict[str, Any]] = []
    for r in rows:
        result.append(
            {
                "id": int(r.id),
                "channel_id": int(r.channel_id),
                "source_url": str(r.source_url) if r.source_url else None,
                "project": r.project,
                "status": r.status,
                "created_at": str(r.created_at or ""),
                "updated_at": str(r.updated_at or ""),
                "matched_at": str(r.matched_at or ""),
                "coverage_check_at": str(r.coverage_check_at or ""),
                "deleted_at": str(r.deleted_at or ""),
                "final_views": r.final_views,
                "title": r.title,
                "is_reply": bool(r.is_reply),
                "matched_session": str(r.matched_session or ""),
                "template_id": r.template_id,
            }
        )
    return result
