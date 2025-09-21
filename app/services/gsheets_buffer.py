from __future__ import annotations

import threading
import time
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.posts_watch_result_db import raw_connection
from app.services import gsheets_writer as gw

# Таймзона для часових полів
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

# Конфіг (можеш підкрутити під себе)
TARGET_FLUSH_SEC = 15.0     # цільовий інтервал «є робота → флаш»
MIN_FLUSH_GAP_SEC = 5.0     # мінімальна пауза між флашами (дебаунс)
BULK_THRESHOLD_EVENTS = 600 # поріг об’єму для позачергового флаша
APPEND_CHUNK = 1000         # розмір пачки для append_rows
EVENT_TTL_SEC = 5.0         # TTL для дідупу повторних подій одного типу

# Стан
_buf_lock = threading.Lock()
_flusher_thread: Optional[threading.Thread] = None
_flusher_stop: Optional[threading.Event] = None
_last_flush_ts: float = 0.0

# Буфери
_pending_appends: Dict[str, List[Tuple[int, List[str]]]] = {}     # {sheet: [(watch_id, [A..I]), ...]}
_pending_updates: Dict[str, Dict[int, Dict[str, str]]] = {}       # {sheet: {wid: {"C"?, "D"?, "E"?: val}}}
_known_row_index: Dict[str, Dict[int, int]] = {}                   # {sheet: {wid: row_index}}
_recent_events: Dict[Tuple[str, int, str], float] = {}             # TTL дідуп: (sheet, wid, type) -> ts
_oldest_event_ts: Optional[float] = None                           # для правила «найстаріша подія ≥ 30 с»

# ---------- налаштування інтервалу ----------
def set_flush_interval(seconds: float) -> None:
    global TARGET_FLUSH_SEC
    TARGET_FLUSH_SEC = max(3.0, float(seconds))

# ---------- форматери ----------
def _human(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")

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

def _dedup_ttl_key(sheet: str, wid: int, etype: str) -> bool:
    """Повертає True, якщо подію слід обробити (не дубль у TTL-вікні)."""
    now = time.time()
    key = (sheet, wid, etype)
    ts = _recent_events.get(key)
    if ts is not None and now - ts < EVENT_TTL_SEC:
        return False
    _recent_events[key] = now
    return True

# ---------- доступ до БД ----------
def _db_get_watch_core(wid: int):
    """Основні поля для побудови рядка."""
    try:
        conn = raw_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT channel_id, template_id, expected_links_json,
                   time_window_start, matched_at, deleted_at,
                   source_url
            FROM watch_posts
            WHERE id = ?
            """,
            (wid,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "channel_id": int(row[0]),
            "template_id": int(row[1]) if row[1] is not None else None,
            "expected_links_json": row[2],
            "time_window_start": row[3],
            "matched_at": row[4],
            "deleted_at": row[5],
            "source_url": row[6] if row[6] else None,
        }
    except Exception:
        return None

def _db_get_channel_title_and_owner(channel_id: int):
    try:
        conn = raw_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT title, owner_display FROM channels WHERE channel_id = ? LIMIT 1",
            (int(channel_id),),
        )
        row = cur.fetchone()
        if not row:
            return None, None
        title, owner_display = row[0], row[1]
        return (str(title) if title else None, str(owner_display) if owner_display else None)
    except Exception:
        return None, None

def _db_get_template_title(tid: int | None):
    if not tid:
        return None
    try:
        conn = raw_connection()
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

# ---------- побудова рядка для matched ----------
def _build_row_for_matched(wid: int) -> Tuple[str, List[str]]:
    wc = _db_get_watch_core(wid)
    if not wc:
        date_str = gw.sheet_title_from_time_window_start(None)
        return date_str, [""] * 9
    date_str = gw.sheet_title_from_time_window_start(wc.get("time_window_start"))
    ch_title, owner_display = _db_get_channel_title_and_owner(wc["channel_id"])
    t_title = _db_get_template_title(wc.get("template_id"))
    links_text = _links_text_from_json(wc.get("expected_links_json"))
    posted_at = wc.get("matched_at") or _human(datetime.now(MOSCOW_TZ))
    posted_time = _only_time(posted_at)
    source_url = wc.get("source_url") or ""
    row = [
        ch_title or "",        # A
        source_url,            # B
        posted_time,           # C
        "",                    # D
        "",                    # E
        t_title or "",         # F
        links_text,            # G
        owner_display or "",   # H
        wid,                   # I
    ]
    return date_str, row

# ---------- публічні entrypoints подій ----------
def record_matched(watch_id: int) -> bool:
    """Прийняти подію MATCHED — просто покласти повний рядок у буфер append."""
    date_str, row = _build_row_for_matched(watch_id)
    if not date_str:
        return False
    with _buf_lock:
        gw.ensure_daily_sheet(date_str)
        _pending_appends.setdefault(date_str, []).append((watch_id, row))
        _touch_oldest_event_ts()
    return True

def record_views(watch_id: int, views: int | None) -> bool:
    """Прийняти подію VIEWS — оновити pending_updates по D."""
    wc = _db_get_watch_core(watch_id)
    if not wc:
        return False
    date_str = gw.sheet_title_from_time_window_start(wc.get("time_window_start"))
    if not _dedup_ttl_key(date_str, watch_id, "views"):
        return True
    with _buf_lock:
        bucket = _pending_updates.setdefault(date_str, {})
        entry = bucket.setdefault(watch_id, {})
        entry["D"] = _fmt_views(views)
        _touch_oldest_event_ts()
    return True

def record_deleted(watch_id: int, when_str: str | None = None) -> bool:
    """Прийняти подію DELETED — оновити pending_updates по E."""
    wc = _db_get_watch_core(watch_id)
    if not wc:
        return False
    date_str = gw.sheet_title_from_time_window_start(wc.get("time_window_start"))
    when = when_str or wc.get("deleted_at") or _human(datetime.now(MOSCOW_TZ))
    if not _dedup_ttl_key(date_str, watch_id, "deleted"):
        return True
    with _buf_lock:
        bucket = _pending_updates.setdefault(date_str, {})
        entry = bucket.setdefault(watch_id, {})
        entry["E"] = _only_time(when)
        _touch_oldest_event_ts()
    return True

# ---------- планувальник флаша ----------
def start_flusher() -> None:
    """Запустити фоновий цикл, що тригерить флаш кожні ~30 с (або за порогами)."""
    global _flusher_thread, _flusher_stop
    if _flusher_thread and _flusher_thread.is_alive():
        return
    _flusher_stop = threading.Event()

    def _loop():
        global _last_flush_ts
        while not _flusher_stop.is_set():
            time.sleep(5.0)  # легкий «тикер»
            now = time.time()
            with _buf_lock:
                has_work = any(_pending_appends.values()) or any(_pending_updates.values())
                oldest_age = (now - _oldest_event_ts) if _oldest_event_ts else 0.0
                since_last = now - _last_flush_ts
                # рахуємо приблизний bulk
                bulk = 0
                for s in _pending_appends:
                    bulk += len(_pending_appends.get(s, []))
                for s in _pending_updates:
                    bulk += len(_pending_updates.get(s, {}))
            should_time = has_work and since_last >= TARGET_FLUSH_SEC
            should_bulk = has_work and bulk >= BULK_THRESHOLD_EVENTS
            should_old = has_work and oldest_age >= TARGET_FLUSH_SEC
            # дебаунс, щоб не «стріляти» занадто часто
            if (should_time or should_bulk or should_old) and since_last >= MIN_FLUSH_GAP_SEC:
                flush_now()
                _last_flush_ts = time.time()

    _flusher_thread = threading.Thread(target=_loop, daemon=True)
    _flusher_thread.start()

def stop_flusher() -> None:
    """Зупинити фоновий флашер (для graceful shutdown виклич `flush_now()` окремо)."""
    global _flusher_thread, _flusher_stop
    if _flusher_stop:
        _flusher_stop.set()
    if _flusher_thread:
        _flusher_thread.join(timeout=1.0)
    _flusher_thread = None
    _flusher_stop = None

# ---------- виконання флаша ----------
def flush_now() -> None:
    """Синхронно відправити все накопичене по всіх аркушах."""
    with _buf_lock:
        sheets = sorted(set(_pending_appends.keys()) | set(_pending_updates.keys()))
    for sheet in sheets:
        _flush_sheet(sheet)

def _flush_sheet(sheet: str) -> None:
    """Флаш одного аркуша: append → read I → batchUpdate."""
    # Виймаємо буфери (copy&clear під замком)
    with _buf_lock:
        appends = list(_pending_appends.get(sheet, []))
        updates = dict(_pending_updates.get(sheet, {}))
        _pending_appends[sheet] = []
        _pending_updates[sheet] = {}

    merged_rows: List[List[str]] = []

    # 1) APPEND нових рядків (із підшитими C/D/E з updates — якщо є)
    if appends:
        for wid, row in appends:
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
                gw.append_rows(sheet, merged_rows[i : i + APPEND_CHUNK])

    # 2) Точкові оновлення C/D/E для існуючих рядків
    if updates:
        values_i = gw.read_col_I(sheet)  # одне читання I-колонки на флаш
        mapping: Dict[int, int] = {}
        # values_i містить із I1; шукаємо з другого рядка (рядок 1 — шапка)
        for idx in range(2, len(values_i) + 1):
            try:
                wid = int(str(values_i[idx - 1]).strip())
            except Exception:
                continue
            mapping[wid] = idx

        # Оновлюємо довгоживучий кеш відомих рядків
        with _buf_lock:
            km = _known_row_index.setdefault(sheet, {})
            km.update(mapping)

        # Готуємо один batchUpdate діапазонів
        data: List[Dict[str, Any]] = []
        for wid, fields in updates.items():
            row_idx = mapping.get(wid) or _known_row_index.get(sheet, {}).get(wid)
            if not row_idx:
                continue
            if "C" in fields:
                data.append({"range": f"'{sheet}'!C{row_idx}:C{row_idx}", "values": [[fields["C"]]]})
            if "D" in fields:
                data.append({"range": f"'{sheet}'!D{row_idx}:D{row_idx}", "values": [[fields["D"]]]})
            if "E" in fields:
                data.append({"range": f"'{sheet}'!E{row_idx}:E{row_idx}", "values": [[fields["E"]]]})
        if data:
            gw.batch_update_values(sheet, data)

    _cleanup_recent()

def _cleanup_recent():
    """Періодично чистимо TTL-дідуп і скидаємо найстарішу подію, якщо роботи вже нема."""
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