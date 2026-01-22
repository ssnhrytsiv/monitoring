from __future__ import annotations

import threading
import time
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime

from app.utils.link_parser import extract_bot_username
from app.sheet_bot.services import gsheets_writer as gw
from app.DAL import bot_links_operations as blo
from app.DAL import sheet_projects_operations as spo
from app.DAL import watch_posts_operations as watch_posts_db
from app.DAL import channels_operations as channels_db
from app.DAL import admins_operations as ao
from app.DAL import session_scope
import logging
from app.utils.time_utils import MOSCOW_TIME_FORMAT, moscow_now

log = logging.getLogger("sheet_bot.gsheets_buffer")

TARGET_FLUSH_SEC = 15.0
MIN_FLUSH_GAP_SEC = 5.0
BULK_THRESHOLD_EVENTS = 600
APPEND_CHUNK = 1000
EVENT_TTL_SEC = 5.0

_buf_lock = threading.Lock()
_flusher_thread: Optional[threading.Thread] = None
_flusher_stop: Optional[threading.Event] = None
_last_flush_ts: float = 0.0

_pending_appends: Dict[Tuple[str, str], List[Tuple[int, List[str]]]] = {}
_pending_updates: Dict[Tuple[str, str], Dict[int, Dict[str, str]]] = {}
_known_row_index: Dict[Tuple[str, str], Dict[int, int]] = {}
_recent_events: Dict[Tuple[str, str, int, str], float] = {}
_oldest_event_ts: Optional[float] = None


def set_flush_interval(seconds: float) -> None:
    global TARGET_FLUSH_SEC
    TARGET_FLUSH_SEC = max(3.0, float(seconds))


def _human(dt: datetime) -> str:
    return dt.strftime(MOSCOW_TIME_FORMAT)


def _only_time(ts: str | None) -> str:
    if not ts:
        return ""
    s = str(ts).strip()
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%H:%M:%S")
    except Exception:
        pass
    if " " in s:
        return s.split(" ", 1)[1].strip()
    return s


def _fmt_views(val: int | None) -> str:
    n = 0 if val is None else int(val)
    s = f"{n:,}"
    return s.replace(",", " ")


def _touch_oldest_event_ts():
    global _oldest_event_ts
    now = time.time()
    if _oldest_event_ts is None or now < _oldest_event_ts:
        _oldest_event_ts = now


def _dedup_ttl_key(sheet_key: Tuple[str, str], wid: int, etype: str) -> bool:
    now = time.time()
    key = (sheet_key[0], sheet_key[1], wid, etype)
    ts = _recent_events.get(key)
    if ts is not None and now - ts < EVENT_TTL_SEC:
        return False
    _recent_events[key] = now
    return True


def _mk_key(sheet: str, ssid: Optional[str]) -> Tuple[str, str]:
    return (ssid or "", sheet)


def _db_get_watch_core(wid: int):
    details = watch_posts_db.get_watch_post_details_by_id(int(wid))
    if not details:
        return None
    if details.channel_id is None:
        log.warning("gsheets_buffer: watch %s missing channel_id", wid)
        return None
    return {
        "channel_id": int(details.channel_id),
        "template_id": int(details.template_id) if details.template_id is not None else None,
        "expected_links_json": details.expected_links_json,
        "time_window_start": details.time_window_start,
        "matched_at": details.matched_at,
        "deleted_at": details.deleted_at,
        "source_url": details.source_url or None,
        "project": details.project,
    }


def _db_get_channel_title_and_owner(channel_id: int):
    try:
        rec = channels_db.get_channel_title_and_owner(int(channel_id))
        if not rec:
            return None, None
        return rec.title, rec.owner_label
    except Exception:
        return None, None


def _resolve_title_and_owner(channel_id: int, source_url: str | None):
    """
    Повертаємо title/owner з таблиці channels або, якщо це бот, з bot_links.
    """
    ch_title, owner_label = _db_get_channel_title_and_owner(channel_id)
    if ch_title or owner_label:
        return ch_title, owner_label

    username = extract_bot_username(source_url or "")
    if username:
        with session_scope() as db:
            bot = blo.get_bot_link_by_username(db, username)
            if bot:
                title = bot.title or username
                owner_label = None
                if bot.owner_admin_id:
                    adm = ao.get_admin_label(db, bot.owner_admin_id)
                    if adm and adm.display:
                        owner_label = adm.display
                    elif adm and adm.username:
                        owner_label = adm.username
                if not owner_label:
                    owner_label = bot.owner_username
                return title, owner_label
    return ch_title, owner_label


def _db_get_template_title(tid: int | None):
    if not tid:
        return None
    try:
        with session_scope() as db:
            conn = db.connection().connection
            cur = conn.cursor()
            cur.execute("SELECT title FROM post_template WHERE id = ? LIMIT 1", (int(tid),))
            row = cur.fetchone()
            if not row:
                return None
            return str(row[0]) if row[0] else None
    except Exception:
        return None


def _links_text_from_json(links_json: str | None) -> str:
    if not links_json:
        return ""
    try:
        import json
        arr = json.loads(links_json)
        if isinstance(arr, list):
            return "\n".join(str(x) for x in arr if x)
    except Exception:
        pass
    return ""


def _edited_other_value(when_str: str | None) -> str:
    t = _only_time(when_str or _human(moscow_now()))
    return f"Відредаговано, інший пост ({t})"


def _select_sheet_for_watch(wc: dict) -> Tuple[Optional[str], Optional[str]]:
    """
    Визначає аркуш і Spreadsheet ID для проєкту (якщо обрано).
    Повертає (sheet_title_override, spreadsheet_id_override).
    """
    sheet_title_override = None
    ssid_override = None
    project = wc.get("project")
    if project:
        with session_scope() as db:
            rec = spo.get_active_sheet(db, project)
            if rec and rec.active_spreadsheet_id:
                ssid_override = rec.active_spreadsheet_id
                log.info(
                    "sheet_select: project=%s -> spreadsheet=%s",
                    project,
                    ssid_override,
                )
    return sheet_title_override, ssid_override


def _build_row_for_matched(wid: int) -> Tuple[str, List[str], Optional[str]]:
    wc = _db_get_watch_core(wid)
    if not wc:
        date_str = gw.sheet_title_from_time_window_start(None)
        return date_str, [""] * 9, None
    date_str = gw.sheet_title_from_time_window_start(wc.get("time_window_start"))
    ch_title, owner_label = _resolve_title_and_owner(wc["channel_id"], wc.get("source_url"))
    t_title = _db_get_template_title(wc.get("template_id"))
    links_text = _links_text_from_json(wc.get("expected_links_json"))
    posted_at = wc.get("matched_at") or _human(moscow_now())
    posted_time = _only_time(posted_at)
    source_url = wc.get("source_url") or ""
    sheet_title_override, ssid_override = _select_sheet_for_watch(wc)
    row = [
        ch_title or "",
        source_url,
        posted_time,  # C
        "",
        "",
        t_title or "",
        links_text,
        owner_label or "",
        wid,
    ]
    return sheet_title_override or date_str, row, ssid_override


def _build_row_for_expired(wid: int) -> Tuple[str, List[str], Optional[str]]:
    wc = _db_get_watch_core(wid)
    if not wc:
        date_str = gw.sheet_title_from_time_window_start(None)
        return date_str, [""] * 9, None
    date_str = gw.sheet_title_from_time_window_start(wc.get("time_window_start"))
    ch_title, owner_label = _resolve_title_and_owner(wc["channel_id"], wc.get("source_url"))
    t_title = _db_get_template_title(wc.get("template_id"))
    links_text = _links_text_from_json(wc.get("expected_links_json"))
    source_url = wc.get("source_url") or ""
    sheet_title_override, ssid_override = _select_sheet_for_watch(wc)
    row = [
        ch_title or "",
        source_url,
        "Не вийшов",
        "",
        "",
        t_title or "",
        links_text,
        owner_label or "",
        wid,
    ]
    return sheet_title_override or date_str, row, ssid_override


def _build_row_for_edited_other(wid: int, when_str: str | None) -> Tuple[str, List[str], Optional[str]]:
    wc = _db_get_watch_core(wid)
    if not wc:
        date_str = gw.sheet_title_from_time_window_start(None)
        return date_str, [""] * 9, None
    date_str = gw.sheet_title_from_time_window_start(wc.get("time_window_start"))
    ch_title, owner_label = _resolve_title_and_owner(wc["channel_id"], wc.get("source_url"))
    t_title = _db_get_template_title(wc.get("template_id"))
    links_text = _links_text_from_json(wc.get("expected_links_json"))
    source_url = wc.get("source_url") or ""
    sheet_title_override, ssid_override = _select_sheet_for_watch(wc)
    row = [
        ch_title or "",
        source_url,
        _edited_other_value(when_str),
        "",
        "",
        t_title or "",
        links_text,
        owner_label or "",
        wid,
    ]
    return sheet_title_override or date_str, row, ssid_override


def record_matched(watch_id: int) -> bool:
    """
    Записує matched у буфер.

    Логіка:
      - якщо вже є append для цього watch_id у цьому дні – перезаписуємо рядок;
      - якщо відомий індекс рядка (через _known_row_index) – додаємо update по C;
      - якщо в кеші немає, але рядок уже існує в шиті – знаходимо його по колонці I і додаємо update;
      - лише якщо рядка взагалі ніде немає – додаємо новий append.
    """
    date_str, row, ssid = _build_row_for_matched(watch_id)
    if not date_str:
        return False
    key = _mk_key(date_str, ssid)
    log.info("record_matched: wid=%s sheet=%s ssid=%s project_row=%s", watch_id, date_str, ssid, row[0:2])

    # Спочатку перевіряємо буфери під локом
    with _buf_lock:
        gw.ensure_daily_sheet(date_str, spreadsheet_id=ssid)

        # 1) оновлюємо вже запланований append, якщо він є
        bucket_app = _pending_appends.setdefault(key, [])
        for idx, (wid, existing_row) in enumerate(bucket_app):
            if wid == watch_id:
                bucket_app[idx] = (watch_id, row)
                _touch_oldest_event_ts()
                return True

        # 2) якщо знаємо рядок у вже записаному шиті – робимо update по C
        known_rows = _known_row_index.get(key, {})
        if watch_id in known_rows:
            bucket_upd = _pending_updates.setdefault(key, {})
            entry = bucket_upd.setdefault(watch_id, {})
            entry["C"] = row[2]
            _touch_oldest_event_ts()
            return True

    # 2.5) поза локом: спробувати знайти рядок напряму в Google Sheets по колонці I
    values_i = gw.read_col_I(date_str, spreadsheet_id=ssid)
    mapping: Dict[int, int] = {}
    for idx in range(2, len(values_i) + 1):
        try:
            wid = int(str(values_i[idx - 1]).strip())
        except Exception:
            continue
        mapping[wid] = idx

    row_idx = mapping.get(watch_id)

    with _buf_lock:
        # оновлюємо кеш відомих рядків
        km = _known_row_index.setdefault(key, {})
        km.update(mapping)

        if row_idx:
            # 3) тепер знаємо рядок -> робимо update по C
            bucket_upd = _pending_updates.setdefault(key, {})
            entry = bucket_upd.setdefault(watch_id, {})
            entry["C"] = row[2]
            _touch_oldest_event_ts()
            return True

        # 4) взагалі не знайшли цей watch_id у шиті -> створюємо новий рядок
        _pending_appends.setdefault(key, []).append((watch_id, row))
        _touch_oldest_event_ts()
    return True


def record_views(watch_id: int, views: int | None) -> bool:
    wc = _db_get_watch_core(watch_id)
    if not wc:
        return False
    date_str = gw.sheet_title_from_time_window_start(wc.get("time_window_start"))
    sheet_title_override, ssid_override = _select_sheet_for_watch(wc)
    sheet_title = sheet_title_override or date_str
    key = _mk_key(sheet_title, ssid_override)
    if not _dedup_ttl_key(key, watch_id, "views"):
        return True
    with _buf_lock:
        bucket = _pending_updates.setdefault(key, {})
        entry = bucket.setdefault(watch_id, {})
        entry["D"] = _fmt_views(views)
        _touch_oldest_event_ts()
    return True


def record_deleted(watch_id: int, when_str: str | None = None) -> bool:
    wc = _db_get_watch_core(watch_id)
    if not wc:
        return False
    date_str = gw.sheet_title_from_time_window_start(wc.get("time_window_start"))
    sheet_title_override, ssid_override = _select_sheet_for_watch(wc)
    sheet_title = sheet_title_override or date_str
    key = _mk_key(sheet_title, ssid_override)
    when = when_str or wc.get("deleted_at") or _human(moscow_now())
    if not _dedup_ttl_key(key, watch_id, "deleted"):
        return True
    with _buf_lock:
        bucket = _pending_updates.setdefault(key, {})
        entry = bucket.setdefault(watch_id, {})
        entry["E"] = _only_time(when)
        _touch_oldest_event_ts()
    return True


def record_expired(watch_id: int) -> bool:
    wc = _db_get_watch_core(watch_id)
    if not wc:
        return False
    date_str = gw.sheet_title_from_time_window_start(wc.get("time_window_start"))
    sheet_title_override, ssid_override = _select_sheet_for_watch(wc)
    sheet_title = sheet_title_override or date_str
    key = _mk_key(sheet_title, ssid_override)
    if not _dedup_ttl_key(key, watch_id, "expired"):
        return True
    with _buf_lock:
        existing = False
        if _known_row_index.get(key, {}).get(watch_id):
            existing = True
        if not existing:
            for wid, _ in _pending_appends.get(key, []):
                if wid == watch_id:
                    existing = True
                    break
        if existing:
            bucket = _pending_updates.setdefault(key, {})
            entry = bucket.setdefault(watch_id, {})
            entry["C"] = "Не вийшов"
        else:
            d, row, ssid = _build_row_for_expired(watch_id)
            key_inner = _mk_key(d, ssid)
            log.info("record_expired: wid=%s sheet=%s ssid=%s", watch_id, d, ssid)
            gw.ensure_daily_sheet(d, spreadsheet_id=ssid)
            _pending_appends.setdefault(key_inner, []).append((watch_id, row))
        _touch_oldest_event_ts()
    return True


def record_edited_other_post(watch_id: int, when_str: str | None = None) -> bool:
    wc = _db_get_watch_core(watch_id)
    if not wc:
        return False
    date_str = gw.sheet_title_from_time_window_start(wc.get("time_window_start"))
    sheet_title_override, ssid_override = _select_sheet_for_watch(wc)
    sheet_title = sheet_title_override or date_str
    key = _mk_key(sheet_title, ssid_override)
    if not _dedup_ttl_key(key, watch_id, "edited_other"):
        return True
    val_c = _edited_other_value(when_str)
    with _buf_lock:
        bucket = _pending_updates.setdefault(key, {})
        entry = bucket.setdefault(watch_id, {})
        entry["C"] = val_c
        _touch_oldest_event_ts()
    return True


def start_flusher() -> None:
    global _flusher_thread, _flusher_stop
    if _flusher_thread and _flusher_thread.is_alive():
        return
    _flusher_stop = threading.Event()

    def _loop():
        global _last_flush_ts
        while not _flusher_stop.is_set():
            time.sleep(5.0)
            now = time.time()
            with _buf_lock:
                has_work = any(_pending_appends.values()) or any(_pending_updates.values())
                oldest_age = (now - _oldest_event_ts) if _oldest_event_ts else 0.0
                since_last = now - _last_flush_ts
                bulk = 0
                for s in _pending_appends:
                    bulk += len(_pending_appends.get(s, []))
                for s in _pending_updates:
                    bulk += len(_pending_updates.get(s, {}))
            should_time = has_work and since_last >= TARGET_FLUSH_SEC
            should_bulk = has_work and bulk >= BULK_THRESHOLD_EVENTS
            should_old = has_work and oldest_age >= TARGET_FLUSH_SEC
            if (should_time or should_bulk or should_old) and since_last >= MIN_FLUSH_GAP_SEC:
                flush_now()
                _last_flush_ts = time.time()

    _flusher_thread = threading.Thread(target=_loop, daemon=True)
    _flusher_thread.start()


def stop_flusher() -> None:
    global _flusher_thread, _flusher_stop
    if _flusher_stop:
        _flusher_stop.set()
    if _flusher_thread:
        _flusher_thread.join(timeout=1.0)
    _flusher_thread = None
    _flusher_stop = None


def flush_now() -> None:
    with _buf_lock:
        sheets = sorted(set(_pending_appends.keys()) | set(_pending_updates.keys()))
    for sheet_key in sheets:
        _flush_sheet(sheet_key)


def _flush_sheet(sheet_key: Tuple[str, str]) -> None:
    ssid = sheet_key[0] or None
    sheet = sheet_key[1]
    log.info("flush_sheet: sheet=%s ssid=%s", sheet, ssid)
    gw.ensure_daily_sheet(sheet, spreadsheet_id=ssid)
    with _buf_lock:
        appends = list(_pending_appends.get(sheet_key, []))
        updates = dict(_pending_updates.get(sheet_key, {}))
        _pending_appends[sheet_key] = []
        _pending_updates[sheet_key] = {}

    merged_rows: List[List[str]] = []

    if appends:
        for wid, row in appends:
            # якщо є update для цього wid – застосовуємо його до рядка
            fields = updates.pop(wid, None)
            if fields:
                if "C" in fields:
                    row[2] = fields["C"]
                if "D" in fields:
                    row[3] = fields["D"]
                if "E" in fields:
                    row[4] = fields["E"]
            merged_rows.append(row)
        if merged_rows:
            for i in range(0, len(merged_rows), APPEND_CHUNK):
                gw.append_rows(sheet, merged_rows[i: i + APPEND_CHUNK], spreadsheet_id=ssid)

    # у updates залишилися тільки ті wid, для яких немає append'ів
    if updates:
        values_i = gw.read_col_I(sheet, spreadsheet_id=ssid)
        mapping: Dict[int, int] = {}
        for idx in range(2, len(values_i) + 1):
            try:
                wid = int(str(values_i[idx - 1]).strip())
            except Exception:
                continue
            mapping[wid] = idx

        with _buf_lock:
            km = _known_row_index.setdefault(sheet_key, {})
            km.update(mapping)

        data: List[Dict[str, Any]] = []
        for wid, fields in updates.items():
            row_idx = mapping.get(wid) or _known_row_index.get(sheet_key, {}).get(wid)
            if not row_idx:
                continue
            if "C" in fields:
                data.append({"range": f"'{sheet}'!C{row_idx}:C{row_idx}", "values": [[fields["C"]]]})
            if "D" in fields:
                data.append({"range": f"'{sheet}'!D{row_idx}:D{row_idx}", "values": [[fields["D"]]]})
            if "E" in fields:
                data.append({"range": f"'{sheet}'!E{row_idx}:E{row_idx}", "values": [[fields["E"]]]})
        if data:
            gw.batch_update_values(sheet, data, spreadsheet_id=ssid)

    _cleanup_recent()


def _cleanup_recent():
    now = time.time()
    keys = list(_recent_events.keys())
    for k in keys:
        if now - _recent_events.get(k, 0.0) >= EVENT_TTL_SEC:
            _recent_events.pop(k, None)
    global _oldest_event_ts
    with _buf_lock:
        has_work = any(_pending_appends.values()) or any(_pending_updates.values())
        if not has_work:
            _oldest_event_ts = None
