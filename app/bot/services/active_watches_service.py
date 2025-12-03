from typing import Optional, Any, List, Tuple, Dict
import logging

from app.services.posts_watch_result_db import raw_connection
from app.services.time_utils import msk_now
from app.services.posts_watch_result_db import insert_watch_event

log = logging.getLogger("active_watches.service")

# Тип елемента групи:
GroupItem = Tuple[int, int, str, str, int]
# (wid, channel_id, status, source_url, template_id)
SingleWatch = Tuple[int, Optional[int], str, Optional[str], Any, Optional[int], Optional[str]]
# (id, template_id, status, time_window_end, created_by, channel_id, source_url)


def get_watch_by_id(wid: int) -> Optional[SingleWatch]:
    """
    Повертає один watch за id або None, якщо не знайдено.
    """
    conn = raw_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, template_id, status, time_window_end, created_by, channel_id, source_url
        FROM watch_posts
        WHERE id = ?
        """,
        (wid,),
    )
    row = cur.fetchone()
    if not row:
        return None

    return row


def get_group_leader_key(
    leader_wid: int,
) -> Optional[Tuple[Optional[int], Optional[str], Any, Optional[int]]]:
    """
    Повертає (template_id, tw_key (до хвилини), created_by, channel_id) для leader_wid.
    Якщо не знайдено — None.
    """
    conn = raw_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT template_id, time_window_end, created_by, channel_id "
        "FROM watch_posts WHERE id=?",
        (leader_wid,),
    )
    row = cur.fetchone()
    if not row:
        return None

    tid, tw_end, cby, cid = row
    tid_i = int(tid) if tid is not None else None

    if tw_end is None:
        tw_key = None
    else:
        s = str(tw_end)
        tw_key = s[:16] if len(s) >= 16 else s  # до хвилини

    cid_i = int(cid) if cid is not None else None
    return tid_i, tw_key, cby, cid_i


def load_group_items(
    template_id: Optional[int],
    tw_key: Optional[str],
    created_by: Any,
) -> List[GroupItem]:
    """
    Завантажує всі вотчі групи за (template_id, tw_key, created_by)
    зі статусами pending/matched/expired.

    Повертає список:
      (wid, channel_id, status, source_url, template_id)
    """
    conn = raw_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, template_id, status, time_window_end, created_by, channel_id, source_url
        FROM watch_posts
        WHERE status IN ('pending','matched','expired')
          AND template_id IS ?
          AND (created_by IS ? OR created_by IS NULL)
        ORDER BY id DESC
        """,
        (template_id, created_by),
    )
    rows = cur.fetchall()

    items: List[GroupItem] = []

    for wid, tid_row, st, tw_row, cby_row, cid, source_url in rows:
        tid_row_i = int(tid_row) if tid_row is not None else None
        if tid_row_i != template_id:
            continue

        if tw_row is None:
            tw_row_key = None
        else:
            s = str(tw_row)
            tw_row_key = s[:16] if len(s) >= 16 else s

        if tw_row_key != tw_key:
            continue

        wid_i = int(wid)
        cid_i = int(cid) if cid is not None else 0
        status_s = str(st or "").strip()
        src = str(source_url).strip() if source_url else ""

        items.append((wid_i, cid_i, status_s, src, tid_row_i))

    return items


def load_group_channels(
    leader_wid: int,
) -> List[int]:
    """
    Повертає список channel_id для всіх watch'ів групи leader_wid
    (статуси pending/matched/expired).
    """
    conn = raw_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT template_id, time_window_end, created_by "
        "FROM watch_posts WHERE id=?",
        (leader_wid,),
    )
    row = cur.fetchone()
    if not row:
        return []

    tid, tw_end, cby = row
    tid_i = int(tid) if tid is not None else None
    tw_end_s = str(tw_end) if tw_end is not None else None

    cur.execute(
        """
        SELECT id, channel_id
        FROM watch_posts
        WHERE template_id IS ?
          AND time_window_end IS ?
          AND created_by IS ?
          AND status IN ('pending','matched','expired')
        """,
        (tid_i, tw_end_s, cby),
    )
    items = cur.fetchall()

    cids: List[int] = []
    for _, cid in items:
        try:
            ci = int(cid)
            if ci:
                cids.append(ci)
        except Exception:
            continue

    return cids


def cancel_group_watches(leader_wid: int) -> bool:
    """
    Скасовує всі watch'і групи (pending/matched/expired -> cancelled).
    Повертає True, якщо апдейт відбувся без виключень.
    """
    conn = raw_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT template_id, time_window_end, created_by "
        "FROM watch_posts WHERE id=?",
        (leader_wid,),
    )
    row = cur.fetchone()
    if not row:
        return False

    tid, tw_end, cby = row
    tid_i = int(tid) if tid is not None else None
    tw_end_s = str(tw_end) if tw_end is not None else None

    now_s = msk_now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute(
        """
        UPDATE watch_posts
        SET status='cancelled', updated_at=?
        WHERE template_id IS ?
          AND time_window_end IS ?
          AND created_by IS ?
          AND status IN ('pending','matched','expired')
        """,
        (now_s, tid_i, tw_end_s, cby),
    )
    conn.commit()

    try:
        insert_watch_event(leader_wid, "cancelled", {"watch_id": leader_wid})
    except Exception:
        log.exception("failed to insert watch_event for cancelled group")

    return True