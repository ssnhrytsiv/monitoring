from typing import List, Any, Dict, Tuple, Optional
from datetime import datetime

from app.services.posts_watch_result_db import raw_connection


def list_active_watches(user_id: int) -> List[Tuple[Any, Any, Any, Any, Any, Any]]:
    conn = raw_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, template_id, status, time_window_end, created_by, channel_id
        FROM watch_posts
        WHERE (created_by=? OR created_by IS NULL)
          AND status IN ('pending','matched', 'expired')
        ORDER BY id DESC
        LIMIT 200
        """,
        (user_id,),
    )
    return cur.fetchall()


def group_active(
    rows: List[Tuple[Any, Any, Any, Any, Any, Any]]
) -> Dict[Tuple[Optional[int], Optional[str], Optional[int]], List[Tuple[int, int]]]:
    """
    Групує active-watches за:
      - template_id
      - time_window_end, приведеним до точності до хвилини (YYYY-MM-DD HH:MM)
      - created_by

    Тобто всі записи з time_window_end 20:59:22 / 20:59:26 потраплять в одну групу '... 20:59'.
    """
    groups: Dict[Tuple[Optional[int], Optional[str], Optional[int]], List[Tuple[int, int]]] = {}

    for wid, tid, st, tw_end, cby, cid in rows:
        tid_i = int(tid) if tid is not None else None

        # tw_end може бути datetime або рядком з БД
        tw_end_s: Optional[str]
        if tw_end is None:
            tw_end_s = None
        else:
            s = str(tw_end)
            # очікуваний формат 'YYYY-MM-DD HH:MM:SS'
            # відрізаємо до хвилини: 'YYYY-MM-DD HH:MM'
            # якщо формат інший, залишаємо як є
            if len(s) >= 16:
                tw_end_s = s[:16]  # '2025-11-29 20:59:26' -> '2025-11-29 20:59'
            else:
                tw_end_s = s

        cby_i = int(cby) if cby is not None else None
        wid_i = int(wid)
        cid_i = int(cid) if cid is not None else 0

        key = (tid_i, tw_end_s, cby_i)
        groups.setdefault(key, []).append((wid_i, cid_i))

    return groups