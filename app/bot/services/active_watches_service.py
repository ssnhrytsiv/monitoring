from typing import Optional, Any, List, Tuple
import logging

from app.DAL import watch_posts_operations as watch_posts_db
from app.DAL import watch_events_operations as watch_events_db

log = logging.getLogger("active_watches.service")

ALLOWED_STATUSES = {"pending", "matched", "expired"}

# Тип елемента групи:
GroupItem = Tuple[int, int, str, str, int]
# (wid, channel_id, status, source_url, template_id)
SingleWatch = Tuple[int, Optional[int], str, Optional[str], Any, Optional[int], Optional[str]]
# (id, template_id, status, time_window_end, created_by, channel_id, source_url)


def get_watch_by_id(wid: int) -> Optional[SingleWatch]:
    """
    Повертає один watch за id або None, якщо не знайдено.
    """
    return watch_posts_db.get_watch_by_id(wid)


def get_group_leader_key(
    leader_wid: int,
) -> Optional[Tuple[Optional[int], Optional[str], Any, Optional[int]]]:
    """
    Повертає (template_id, tw_key (до хвилини), created_by, channel_id) для leader_wid.
    Якщо не знайдено — None.
    """
    return watch_posts_db.get_group_leader_key(leader_wid)


def get_group_leader_for_watch(wid: int) -> Optional[int]:
    """
    Повертає id лідерського watch'а (мінімальний id за ключем групи) для переданого wid.
    Якщо не знайдено – None.
    """
    return watch_posts_db.get_group_leader_for_watch(wid)


def load_group_items(
    template_id: Optional[int],
    tw_key: Optional[str],
    created_by: Any,
    statuses: Optional[List[str]] = None,
) -> List[GroupItem]:
    """
    Завантажує всі вотчі групи за (template_id, tw_key, created_by)
    з обмеженням по статусах (дефолт: pending+matched).

    Повертає список:
      (wid, channel_id, status, source_url, template_id)
    """
    return watch_posts_db.load_group_items(template_id, tw_key, created_by, statuses)


def load_group_channels(
    leader_wid: int,
    statuses: Optional[List[str]] = None,
) -> List[int]:
    """
    Повертає список channel_id для всіх watch'ів групи leader_wid
    (статуси можна задати; дефолт: pending+matched+expired).
    """
    return watch_posts_db.load_group_channels(leader_wid, statuses)


def cancel_group_watches(leader_wid: int) -> bool:
    """
    Скасовує всі watch'і групи (pending/matched/expired -> cancelled).
    Повертає True, якщо апдейт відбувся без виключень.
    """
    updated = watch_posts_db.cancel_group_watches(leader_wid)
    if not updated:
        return False
    try:
        watch_events_db.insert_watch_event(
            leader_wid,
            "cancelled",
            '{"watch_id": %d}' % int(leader_wid),
        )
    except Exception:
        log.exception("failed to insert watch_event for cancelled group")
    return True
