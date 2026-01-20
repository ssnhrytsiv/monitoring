from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import json
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session
from app.db.models import WatchPost, WatchGroup
from app.DAL.watch_processing_operations import get_session_for_source_url_db as process_get_session_for_source_url
from app.DAL.watch_events_operations import insert_watch_event
from app.db import models as m
from app.utils.time_utils import MOSCOW_TIME_FORMAT, moscow_now

# Дозволені статуси вотчів
ALLOWED_STATUSES: Dict[str, str] = {
    "pending": "pending",
    "matched": "matched",
    "expired": "expired",
}


@dataclass
class WatchSummary:
    id: int
    template_id: Optional[int]
    status: str
    time_window_end: Optional[str]
    created_by: Optional[int]
    channel_id: Optional[int]
    source_url: Optional[str] = None

    def _as_tuple(self) -> Tuple[int, Optional[int], str, Optional[str], Optional[int], Optional[int], Optional[str]]:
        return (
            self.id,
            self.template_id,
            self.status,
            self.time_window_end,
            self.created_by,
            self.channel_id,
            self.source_url,
        )

    def __iter__(self):
        return iter(self._as_tuple())

    def __getitem__(self, index: int):
        return self._as_tuple()[index]


@dataclass
class GroupItem:
    id: int
    channel_id: Optional[int]
    status: str
    source_url: Optional[str]
    template_id: Optional[int]

    def _as_tuple(self) -> Tuple[int, Optional[int], str, Optional[str], Optional[int]]:
        return (self.id, self.channel_id, self.status, self.source_url, self.template_id)

    def __iter__(self):
        return iter(self._as_tuple())

    def __getitem__(self, index: int):
        return self._as_tuple()[index]


def _row_to_summary(row: Any) -> WatchSummary:
    return WatchSummary(
        id=int(row.id),
        template_id=int(row.template_id) if row.template_id is not None else None,
        status=str(row.status or ""),
        time_window_end=row.time_window_end if row.time_window_end is None else str(row.time_window_end),
        created_by=int(row.created_by) if row.created_by is not None else None,
        channel_id=int(row.channel_id) if row.channel_id is not None else None,
        source_url=getattr(row, "source_url", None),
    )


def _now_msk_str() -> str:
    return moscow_now().strftime(MOSCOW_TIME_FORMAT)


def _time_window_key(value: Any) -> Optional[str]:
    if value is None:
        return None
    raw = str(value)
    return raw[:16] if len(raw) >= 16 else raw


def list_active_watches(
    db: Session,
    user_id: int,
    statuses: Optional[List[str]] = None,
) -> List[WatchSummary]:
    """
    Повертає активні вотчі користувача (або всі, якщо created_by NULL) з фільтром статусів.
    Результат відсортований за id DESC і обмежений 200 рядками.
    """
    if not statuses:
        statuses = ["pending", "matched"]

    filtered_statuses = [ALLOWED_STATUSES[s] for s in statuses if s in ALLOWED_STATUSES]
    if not filtered_statuses:
        filtered_statuses = ["pending", "matched"]

    rows = db.execute(
        select(
            WatchPost.id,
            WatchPost.template_id,
            WatchPost.status,
            WatchPost.time_window_end,
            WatchPost.created_by,
            WatchPost.channel_id,
        )
        .where(
            or_(WatchPost.created_by == user_id, WatchPost.created_by.is_(None)),
            WatchPost.status.in_(filtered_statuses),
        )
        .order_by(WatchPost.id.desc())
        .limit(200)
    ).all()

    return [_row_to_summary(r) for r in rows]


def get_watch_by_id(db: Session, watch_id: int) -> Optional[Tuple[int, Optional[int], str, Optional[str], Any, Optional[int], Optional[str]]]:
    """
    Повертає один watch за id або None, якщо не знайдено.
    """
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


def get_group_leader_key(db: Session, watch_id: int) -> Optional[Tuple[Optional[int], Optional[str], Any, Optional[int]]]:
    """
    Повертає (template_id, tw_key, created_by, channel_id) для watch_id.
    """
    row = db.execute(
        select(
            WatchPost.template_id,
            WatchPost.time_window_end,
            WatchPost.created_by,
            WatchPost.channel_id,
        ).where(WatchPost.id == int(watch_id)).limit(1)
    ).first()
    if not row:
        return None
    template_id = int(row.template_id) if row.template_id is not None else None
    tw_key = _time_window_key(row.time_window_end)
    channel_id = int(row.channel_id) if row.channel_id is not None else None
    return template_id, tw_key, row.created_by, channel_id


def get_group_leader_for_watch(db: Session, watch_id: int) -> Optional[int]:
    """
    Повертає мінімальний watch_id за ключем групи (template_id + tw_key + created_by).
    """
    leader_key = get_group_leader_key(db, watch_id)
    if not leader_key:
        return None
    template_id, tw_key, created_by, _ = leader_key
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
    if not row:
        return None
    return int(row.id)


def load_group_items(
    db: Session,
    template_id: Optional[int],
    tw_key: Optional[str],
    created_by: Any,
    statuses: Optional[List[str]] = None,
) -> List[GroupItem]:
    """
    Повертає вотчі групи у форматі GroupItem (iterable як tuple для сумісності).
    """
    status_list = statuses or ["pending", "matched"]
    status_list = [s for s in status_list if s in ALLOWED_STATUSES]
    if not status_list:
        status_list = ["pending", "matched"]

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

    items: List[GroupItem] = []
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
        items.append(
            GroupItem(
                id=wid_int,
                channel_id=cid_int,
                status=status_str,
                source_url=src,
                template_id=tid_row_int if tid_row_int is not None else 0,
            )
        )
    return items


def load_group_channels(
    db: Session,
    leader_watch_id: int,
    statuses: Optional[List[str]] = None,
) -> List[int]:
    """
    Повертає channel_id для всіх watch'ів групи leader_watch_id.
    """
    status_list = statuses or ["pending", "matched", "expired"]
    status_list = [s for s in status_list if s in ALLOWED_STATUSES]
    if not status_list:
        status_list = ["pending", "matched", "expired"]

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

    channels: List[int] = []
    for cid in rows:
        try:
            val = int(cid[0])
            if val:
                channels.append(val)
        except Exception:
            continue
    return channels


def cancel_group_watches(db: Session, leader_watch_id: int) -> bool:
    """
    Ставит pending/matched/expired -> cancelled для групи leader_watch_id.
    """
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


def set_watch_status_pending_db(db: Session, watch_id: int) -> bool:
    """
    Оновлює статус вотчу на pending і проставляє updated_at.
    """
    now_str = _now_msk_str()
    res = db.execute(
        update(WatchPost)
        .where(WatchPost.id == int(watch_id))
        .values(status="pending", updated_at=now_str)
    )
    db.commit()
    return res.rowcount > 0


def update_watch_time_window(
    db: Session,
    watch_id: int,
    time_window_start: str,
    time_window_end: str,
) -> bool:
    """
    Оновлює time_window_start/time_window_end та updated_at для watch_posts.id = watch_id.
    """
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


def update_watch_source_url_db(db: Session, watch_id: int, source_url: str) -> bool:
    """
    Оновлює source_url та updated_at для watch_posts.id = watch_id.
    """
    now_str = _now_msk_str()
    res = db.execute(
        update(WatchPost)
        .where(WatchPost.id == int(watch_id))
        .values(source_url=source_url, updated_at=now_str)
    )
    db.commit()
    return res.rowcount > 0


def group_active(
    rows: List[Tuple[Any, Any, Any, Any, Any, Any]]
) -> Dict[Tuple[Optional[int], Optional[str], Optional[int]], List[Tuple[int, int]]]:
    """
    Групує активні вотчі за:
      - template_id
      - time_window_end, округленим до хвилини (YYYY-MM-DD HH:MM)
      - created_by

    Повертає dict: ключ = (template_id, tw_end_minute, created_by), значення = список (watch_id, channel_id).
    """
    groups: Dict[Tuple[Optional[int], Optional[str], Optional[int]], List[Tuple[int, int]]] = {}

    for watch_id, template_id, status, time_window_end, created_by, channel_id in rows:
        template_id_int = int(template_id) if template_id is not None else None

        if time_window_end is None:
            tw_end_string: Optional[str] = None
        else:
            raw = str(time_window_end)
            tw_end_string = raw[:16] if len(raw) >= 16 else raw

        created_by_int = int(created_by) if created_by is not None else None
        watch_id_int = int(watch_id)
        channel_id_int = int(channel_id) if channel_id is not None else 0

        key = (template_id_int, tw_end_string, created_by_int)
        groups.setdefault(key, []).append((watch_id_int, channel_id_int))

    return groups


def get_watch_channel_id(db: Session, watch_id: int) -> Optional[int]:
    """
    Повертає channel_id для вказаного watch_id.
    """
    row = db.execute(
        select(WatchPost.channel_id).where(WatchPost.id == int(watch_id)).limit(1)
    ).first()
    if not row or row[0] is None:
        return None
    try:
        return int(row[0])
    except Exception:
        return None


def get_watch_source_url(db: Session, watch_id: int) -> Optional[str]:
    """
    Повертає source_url для вказаного watch_id.
    """
    row = db.execute(
        select(WatchPost.source_url).where(WatchPost.id == int(watch_id)).limit(1)
    ).first()
    if not row or row[0] is None:
        return None
    val = row[0]
    return str(val) if val else None
def manual_mark_matched(
    db: Session,
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
            session_label = process_get_session_for_source_url(db, source_url)
        except Exception:
            session_label = None
    if not session_label:
        session_label = "MAIN"

    if db is None:
        raise ValueError("db Session is required")
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

    try:
        payload = json.dumps(
            {
                "watch_id": watch_id,
                "channel_id": channel_id,
                "message_id": message_id,
                "session": session_label,
                "manual": bool(is_manual),
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


def create_watch_group(
    db: Session,
    project: Optional[str] = None,
    title: Optional[str] = None,
    created_by: Optional[int] = None,
    created_via: Optional[str] = None,
    admin_id: Optional[int] = None,
    network_id: Optional[int] = None,
) -> int:
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
    return int(obj.id)


def create_watch(
    db: Session,
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
) -> int:
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
    )
    db.add(wp)
    db.commit()
    db.refresh(wp)
    return int(wp.id)


def cancel_watch(watch_id: int) -> None:
    raise ValueError("cancel_watch requires explicit db; use cancel_group_watches/cancel_group_watches_db instead")


def get_watch_links_or_template_links(db: Session, watch_id: int) -> List[str]:
    """
    Повертає links_json із watch_posts або, якщо порожньо, links із post_template.
    """
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
    db: Session,
    channel_id: int,
    template_id: Optional[int],
    expected_text_hash: Optional[str],
) -> Optional[Dict[str, Any]]:
    """
    Перевіряє, чи існує активний (pending|matched) watch із тим самим ключем.
    Повертає словник з короткою інформацією або None.
    """
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
            WatchPost.status.in_(["pending", "matched"]),
        )
        .order_by(WatchPost.id.desc())
        .limit(1)
    ).first()
    if not row:
        return None
    return {
        "id": int(row.id),
        "status": str(row.status or ""),
        "created_at": row.created_at,
        "time_window_end": row.time_window_end,
        "matched_message_id": row.matched_message_id,
    }


def get_watch_info_db(db: Session, watch_id: int) -> Dict[str, Any]:
    """
    Повертає інформацію про watch_posts.id, мінімально необхідну для нотифікацій.
    """
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
            WatchPost.deleted_at,
            WatchPost.updated_at,
            WatchPost.group_id,
            WatchPost.final_views,
            WatchPost.template_id,
            WatchPost.expected_links_json,
            WatchPost.expected_text_hash,
            WatchPost.time_window_start,
            WatchPost.admin_id,
        ).where(WatchPost.id == int(watch_id)).limit(1)
    ).first()
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
        "deleted_at": row.deleted_at,
        "updated_at": row.updated_at,
        "group_id": row.group_id,
        "final_views": row.final_views,
        "template_id": row.template_id,
        "expected_links_json": row.expected_links_json,
        "expected_text_hash": row.expected_text_hash,
        "time_window_start": row.time_window_start,
        "admin_id": row.admin_id,
    }


def fetch_watches_by_group_db(db: Session, group_id: int) -> List[Dict[str, Any]]:
    """
    Повертає всі вотчі групи у вигляді словників.
    """
    rows = db.execute(
        select(
            WatchPost.id,
            WatchPost.channel_id,
            WatchPost.source_url,
            WatchPost.project,
            WatchPost.status,
            WatchPost.created_at,
            WatchPost.updated_at,
            WatchPost.deleted_at,
            WatchPost.final_views,
        )
        .where(WatchPost.group_id == int(group_id))
        .order_by(WatchPost.id.asc())
    ).all()
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
                "deleted_at": str(r.deleted_at or ""),
                "final_views": r.final_views,
            }
        )
    return result
