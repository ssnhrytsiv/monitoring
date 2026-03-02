from __future__ import annotations

import asyncio
import logging
import os
from collections import Counter
from datetime import datetime, timedelta
from threading import Lock
from typing import Callable, Optional, Dict, Any
import re
from difflib import SequenceMatcher
import json

from sqlalchemy import update

from telethon import events
from telethon.tl.types import Message

from app.telethon_client import client as MAIN_CLIENT
from app.logging_json import get_logger
from app.DAL import watch_posts_operations as watch_posts_db
from app.DAL import watch_events_operations as watch_events_db
from app.DAL import watch_processing_operations as watch_proc_db
from app.DAL import watch_candidates_operations as watch_candidates_db
from app.services.html_match import exact_html_equal
from app.services.account_pool import iter_pool_clients, session_name
from app.utils.time_utils import MOSCOW_TIME_FORMAT, moscow_now
from app.services.post_matcher import normalize_text, extract_links_norm
from app.services import watch_event_reason_codes
from app.admin_bot.db import models as m
from app.admin_bot.db.session import SessionLocal
from app import config
import html as _html_mod

try:
    from app.DAL.post_templates_operations import list_templates_full
except Exception:
    list_templates_full = None  # type: ignore

SHEETS_OK = False
try:
    from app.sheet_bot.services import gsheets_buffer

    SHEETS_OK = True
except Exception:
    gsheets_buffer = None  # type: ignore

log = get_logger("plugin.posts_watch_listener")
_pylog = logging.getLogger("plugin.posts_watch_listener")
trace_logger = logging.getLogger("plugin.posts_watch_trace")
if not trace_logger.handlers:
    try:
        os.makedirs("logs", exist_ok=True)
    except Exception:
        pass
    handler = logging.FileHandler("logs/posts_watch_trace.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    trace_logger.addHandler(handler)
    trace_logger.setLevel(logging.INFO)
    trace_logger.propagate = False


_WATCH_NOTIFIER_GROUP_IDENTIFIER_CACHE: Dict[int, int | None] = {}


def _parse_watch_identifier_from_trace_payload(trace_payload: dict[str, Any]) -> int | None:
    watch_identifier_value = trace_payload.get("watch_id")
    if isinstance(watch_identifier_value, int):
        return watch_identifier_value
    if isinstance(watch_identifier_value, str):
        normalized_watch_identifier_value = watch_identifier_value.strip()
        if not normalized_watch_identifier_value:
            return None
        try:
            return int(normalized_watch_identifier_value)
        except Exception:
            return None
    return None


def _resolve_notifier_group_identifier_by_watch_id(watch_id: int) -> int | None:
    cached_notifier_group_identifier = _WATCH_NOTIFIER_GROUP_IDENTIFIER_CACHE.get(watch_id)
    if cached_notifier_group_identifier is not None:
        return cached_notifier_group_identifier
    if watch_id in _WATCH_NOTIFIER_GROUP_IDENTIFIER_CACHE:
        return None

    try:
        watch_information = watch_posts_db.get_watch_info(watch_id)
    except Exception:
        _pylog.exception("trace: failed to read watch info for notifier group id (watch_id=%s)", watch_id)
        _WATCH_NOTIFIER_GROUP_IDENTIFIER_CACHE[watch_id] = None
        return None

    notifier_group_identifier_value = watch_information.get("group_id") if watch_information else None
    if notifier_group_identifier_value is None:
        _WATCH_NOTIFIER_GROUP_IDENTIFIER_CACHE[watch_id] = None
        return None

    try:
        normalized_notifier_group_identifier = int(notifier_group_identifier_value)
    except Exception:
        _WATCH_NOTIFIER_GROUP_IDENTIFIER_CACHE[watch_id] = None
        return None

    _WATCH_NOTIFIER_GROUP_IDENTIFIER_CACHE[watch_id] = normalized_notifier_group_identifier
    return normalized_notifier_group_identifier


def _inject_notifier_group_identifier_into_trace_payload(trace_payload: dict[str, Any]) -> None:
    existing_notifier_group_identifier = trace_payload.get("notifier_group_id")
    if isinstance(existing_notifier_group_identifier, int):
        return
    if isinstance(existing_notifier_group_identifier, str):
        normalized_notifier_group_identifier_value = existing_notifier_group_identifier.strip()
        if normalized_notifier_group_identifier_value:
            return

    watch_identifier = _parse_watch_identifier_from_trace_payload(trace_payload)
    if watch_identifier is None:
        return

    resolved_notifier_group_identifier = _resolve_notifier_group_identifier_by_watch_id(watch_identifier)
    if resolved_notifier_group_identifier is None:
        return

    trace_payload["notifier_group_id"] = resolved_notifier_group_identifier


def _trace(event: str, **payload):
    try:
        _inject_notifier_group_identifier_into_trace_payload(payload)
    except Exception:
        pass
    try:
        _record_reason_code_summary_event(event_name=event, event_payload=payload)
    except Exception:
        pass
    try:
        trace_logger.info(json.dumps({"event": event, **payload}, ensure_ascii=False))
    except Exception:
        pass


MATCH_DIAGNOSTIC_TEXT_MAX_LENGTH = 1200


def _truncate_text_for_match_diagnostics(
    source_text: str | None,
    maximum_length: int = MATCH_DIAGNOSTIC_TEXT_MAX_LENGTH,
) -> str:
    normalized_source_text = str(source_text or "")
    if len(normalized_source_text) <= maximum_length:
        return normalized_source_text
    if maximum_length <= 3:
        return normalized_source_text[:maximum_length]
    return normalized_source_text[: maximum_length - 3] + "..."


def _normalize_links_for_match_diagnostics(source_links: list[str]) -> list[str]:
    normalized_unique_links: list[str] = []
    seen_normalized_links: set[str] = set()
    for source_link in source_links:
        normalized_link = str(source_link or "").strip()
        if not normalized_link:
            continue
        if normalized_link in seen_normalized_links:
            continue
        seen_normalized_links.add(normalized_link)
        normalized_unique_links.append(normalized_link)
    return normalized_unique_links


def _build_link_difference_payload(
    expected_links_values: list[str],
    actual_links_values: list[str],
) -> dict[str, list[str]]:
    normalized_expected_links = _normalize_links_for_match_diagnostics(expected_links_values)
    normalized_actual_links = _normalize_links_for_match_diagnostics(actual_links_values)

    normalized_actual_links_set = set(normalized_actual_links)
    normalized_expected_links_set = set(normalized_expected_links)

    expected_only_links = [
        expected_link_value
        for expected_link_value in normalized_expected_links
        if expected_link_value not in normalized_actual_links_set
    ]
    actual_only_links = [
        actual_link_value
        for actual_link_value in normalized_actual_links
        if actual_link_value not in normalized_expected_links_set
    ]
    return {
        "expected_only_links": expected_only_links,
        "actual_only_links": actual_only_links,
    }


def _build_match_diagnostics_payload(
    expected_html_text: str,
    actual_html_text: str,
    expected_plain_text: str,
    actual_plain_text: str,
    expected_links_values: list[str],
    actual_links_values: list[str],
) -> dict[str, Any]:
    expected_html_text_value = expected_html_text or ""
    actual_html_text_value = actual_html_text or ""
    expected_plain_text_value = expected_plain_text or ""
    actual_plain_text_value = actual_plain_text or ""
    normalized_expected_links = _normalize_links_for_match_diagnostics(expected_links_values)
    normalized_actual_links = _normalize_links_for_match_diagnostics(actual_links_values)
    return {
        "expected_html_length": len(expected_html_text_value),
        "actual_html_length": len(actual_html_text_value),
        "expected_plain_length": len(expected_plain_text_value),
        "actual_plain_length": len(actual_plain_text_value),
        "expected_links": normalized_expected_links,
        "actual_links": normalized_actual_links,
        **_build_link_difference_payload(
            expected_links_values=normalized_expected_links,
            actual_links_values=normalized_actual_links,
        ),
        "expected_html_excerpt": _truncate_text_for_match_diagnostics(expected_html_text_value),
        "actual_html_excerpt": _truncate_text_for_match_diagnostics(actual_html_text_value),
        "expected_plain_excerpt": _truncate_text_for_match_diagnostics(expected_plain_text_value),
        "actual_plain_excerpt": _truncate_text_for_match_diagnostics(actual_plain_text_value),
    }


def _trace_match_decision_trail(
    *,
    watch_id: int,
    channel_id: int,
    message_id: int,
    session_name: str,
    exact_html_match_succeeded: bool,
    html_similarity_ratio: float,
    plain_text_similarity_ratio: float,
    similarity_threshold: float,
    similarity_threshold_passed: bool,
    links_mismatch_detected: bool | None,
    final_watch_status: str,
    reason_code: str,
    expected_links_values: list[str],
    actual_links_values: list[str],
) -> None:
    links_check_result = "not_checked"
    if links_mismatch_detected is True:
        links_check_result = "links_mismatch"
    elif links_mismatch_detected is False:
        links_check_result = "links_match"

    _trace(
        "match_decision_trail",
        watch_id=watch_id,
        channel_id=channel_id,
        message_id=message_id,
        session=session_name,
        similarity=html_similarity_ratio,
        similarity_text=plain_text_similarity_ratio,
        similarity_threshold=similarity_threshold,
        decision_stages={
            "normalize_html_for_edit": True,
            "exact_html_match_succeeded": exact_html_match_succeeded,
            "similarity_threshold_passed": similarity_threshold_passed,
            "links_check_result": links_check_result,
        },
        final_watch_status=final_watch_status,
        reason_code=reason_code,
        **_build_link_difference_payload(
            expected_links_values=expected_links_values,
            actual_links_values=actual_links_values,
        ),
    )

COVERAGE_POLL_TICK_SEC = 30

_GLOBAL_DELETED_SEEN: Dict[int, float] = {}
GLOBAL_DELETED_TTL = 180.0
_GLOBAL_CANDIDATE_SEEN: Dict[tuple[int, int], float] = {}
CANDIDATE_SEEN_TTL = 24 * 60 * 60  # 1 доба
CANDIDATE_SIM_THRESHOLD = 0.70
# Якщо текстові кандидат-пости схожі >= 0.99, вважаємо їх одним і тим самим кандидатам (не дублюємо).
NEAR_IDENTICAL_TEXT_THRESHOLD = 0.99
GROUP_NEAR_IDENTICAL_THRESHOLD = 0.95
# Редагування: дрібні відмінності не вважаємо суттєвими, якщо ratio майже 1.0
EDIT_NEAR_THRESHOLD = 0.99


def _read_reason_code_summary_enabled() -> bool:
    watch_reason_code_summary_enabled_raw_value = str(os.getenv("WATCH_REASON_CODE_SUMMARY_ENABLED", "1") or "").strip().lower()
    return watch_reason_code_summary_enabled_raw_value not in {"0", "false", "no", "off"}


def _read_reason_code_summary_flush_interval_seconds() -> int:
    watch_reason_code_summary_flush_interval_raw_value = str(
        os.getenv("WATCH_REASON_CODE_SUMMARY_FLUSH_INTERVAL_SECONDS", "3600") or ""
    ).strip()
    try:
        watch_reason_code_summary_flush_interval_seconds = int(watch_reason_code_summary_flush_interval_raw_value)
    except Exception:
        return 3600
    return max(60, watch_reason_code_summary_flush_interval_seconds)


WATCH_REASON_CODE_SUMMARY_ENABLED = _read_reason_code_summary_enabled()
WATCH_REASON_CODE_SUMMARY_FLUSH_INTERVAL_SECONDS = _read_reason_code_summary_flush_interval_seconds()
WATCH_REASON_CODE_SUMMARY_SOURCE_EVENT_NAMES = {
    "match_decision_trail",
    "views_done",
    "views_entity_miss",
    "views_message_not_found",
    "pending_expired",
    "edited_other_detected",
    "deleted_detected",
}
WATCH_REASON_CODE_SUMMARY_TRACE_EVENT_NAME = "watch_reason_code_summary"

_WATCH_REASON_CODE_SUMMARY_LOCK = Lock()
_WATCH_REASON_CODE_SUMMARY_PERIOD_STARTED_AT: str | None = None
_WATCH_REASON_CODE_SUMMARY_TOTAL_EVENTS = 0
_WATCH_REASON_CODE_SUMMARY_REASON_CODE_COUNTS: Counter[str] = Counter()
_WATCH_REASON_CODE_SUMMARY_EVENT_REASON_CODE_COUNTS: Counter[str] = Counter()


def _format_event_reason_code_key(event_name: str, reason_code_value: str) -> str:
    return f"{event_name}:{reason_code_value}"


def _sorted_counter_to_dictionary(source_counter: Counter[str]) -> dict[str, int]:
    sorted_counter_items = sorted(source_counter.items(), key=lambda source_item: (-source_item[1], source_item[0]))
    return {source_key: source_value for source_key, source_value in sorted_counter_items}


def _record_reason_code_summary_event(event_name: str, event_payload: dict[str, Any]) -> None:
    if event_name not in WATCH_REASON_CODE_SUMMARY_SOURCE_EVENT_NAMES:
        return
    reason_code_value = event_payload.get("reason_code")
    if not isinstance(reason_code_value, str):
        return
    normalized_reason_code_value = reason_code_value.strip()
    if not normalized_reason_code_value:
        return

    reason_code_event_key = _format_event_reason_code_key(event_name, normalized_reason_code_value)
    with _WATCH_REASON_CODE_SUMMARY_LOCK:
        global _WATCH_REASON_CODE_SUMMARY_PERIOD_STARTED_AT
        global _WATCH_REASON_CODE_SUMMARY_TOTAL_EVENTS
        if _WATCH_REASON_CODE_SUMMARY_PERIOD_STARTED_AT is None:
            _WATCH_REASON_CODE_SUMMARY_PERIOD_STARTED_AT = _human(moscow_now())
        _WATCH_REASON_CODE_SUMMARY_TOTAL_EVENTS += 1
        _WATCH_REASON_CODE_SUMMARY_REASON_CODE_COUNTS[normalized_reason_code_value] += 1
        _WATCH_REASON_CODE_SUMMARY_EVENT_REASON_CODE_COUNTS[reason_code_event_key] += 1


def _consume_reason_code_summary_snapshot() -> dict[str, Any] | None:
    period_finished_at = _human(moscow_now())
    with _WATCH_REASON_CODE_SUMMARY_LOCK:
        global _WATCH_REASON_CODE_SUMMARY_PERIOD_STARTED_AT
        global _WATCH_REASON_CODE_SUMMARY_TOTAL_EVENTS
        if _WATCH_REASON_CODE_SUMMARY_TOTAL_EVENTS <= 0:
            if _WATCH_REASON_CODE_SUMMARY_PERIOD_STARTED_AT is None:
                _WATCH_REASON_CODE_SUMMARY_PERIOD_STARTED_AT = period_finished_at
            return None

        period_started_at = _WATCH_REASON_CODE_SUMMARY_PERIOD_STARTED_AT or period_finished_at
        total_reasoned_events = int(_WATCH_REASON_CODE_SUMMARY_TOTAL_EVENTS)
        reason_code_counts = _sorted_counter_to_dictionary(_WATCH_REASON_CODE_SUMMARY_REASON_CODE_COUNTS)
        event_reason_code_counts = _sorted_counter_to_dictionary(_WATCH_REASON_CODE_SUMMARY_EVENT_REASON_CODE_COUNTS)

        _WATCH_REASON_CODE_SUMMARY_PERIOD_STARTED_AT = period_finished_at
        _WATCH_REASON_CODE_SUMMARY_TOTAL_EVENTS = 0
        _WATCH_REASON_CODE_SUMMARY_REASON_CODE_COUNTS.clear()
        _WATCH_REASON_CODE_SUMMARY_EVENT_REASON_CODE_COUNTS.clear()

    return {
        "period_started_at": period_started_at,
        "period_finished_at": period_finished_at,
        "total_reasoned_events": total_reasoned_events,
        "reason_code_counts": reason_code_counts,
        "event_reason_code_counts": event_reason_code_counts,
    }


def _now_monotonic() -> float:
    return asyncio.get_event_loop().time()


def _human(dt: datetime) -> str:
    return dt.strftime(MOSCOW_TIME_FORMAT)


def _read_default_coverage_hours() -> float:
    m = os.getenv("WATCH_COVERAGE_MINUTES")
    if m:
        try:
            return float(m) / 60.0
        except Exception:
            pass
    h = os.getenv("WATCH_COVERAGE_HOURS", "24")
    try:
        return float(h)
    except Exception:
        return 24


DEFAULT_COVERAGE_HOURS: float = _read_default_coverage_hours()


def _calc_coverage_at(hours_after: float | None = None) -> Optional[str]:
    if not config.WATCH_VIEWS_ENABLED:
        return None
    hrs = hours_after if hours_after is not None else DEFAULT_COVERAGE_HOURS
    now_msq = moscow_now()
    return _human(now_msq + timedelta(hours=hrs))


_HTML_RENDER: Optional[Callable[[Message], str]] = None
_HTML_RENDER_SRC = None


def _init_html_renderer():
    global _HTML_RENDER, _HTML_RENDER_SRC
    try:
        from app.plugins.post_templates import _extract_message_html as _rh  # type: ignore
        _HTML_RENDER = _rh
        _HTML_RENDER_SRC = "app.plugins.post_templates._extract_message_html"
        return
    except Exception:
        pass
    try:
        from app.services.html_render import render_html as _rh  # type: ignore
        _HTML_RENDER = _rh
        _HTML_RENDER_SRC = "app.services.html_render.render_html"
        return
    except Exception:
        pass
    for mod, attr in [
        ("app.services.post_match", "render_html"),
        ("app.services.post_matcher", "render_html"),
        ("app.services.post_match", "message_to_html"),
        ("app.services.html_match", "message_to_html"),
    ]:
        try:
            _HTML_RENDER = getattr(__import__(mod, fromlist=[attr]), attr)  # type: ignore
            _HTML_RENDER_SRC = f"{mod}.{attr}"
            return
        except Exception:
            pass

    def _fallback_render(m: Message) -> str:
        txt = getattr(m, "message", "") or ""
        return txt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    _HTML_RENDER = _fallback_render
    _HTML_RENDER_SRC = "fallback_plaintext_no_br"


_init_html_renderer()


def _db_get_watch_core(wid: int) -> Optional[Dict[str, Any]]:
    try:
        info = watch_posts_db.get_watch_info(wid)
        if not info:
            return None
        return {
            "channel_id": int(info["channel_id"]),
            "template_id": int(info["template_id"]) if info.get("template_id") is not None else None,
            "expected_text_hash": info.get("expected_text_hash"),
            "expected_links_json": info.get("expected_links_json"),
            "time_window_start": info.get("time_window_start"),
            "time_window_end": info.get("time_window_end"),
        }
    except Exception:
        _pylog.exception("_db_get_watch_core failed (wid=%s)", wid)
    return None


# --- HTML normalization ------------------------------------------------------

_A_TAG_RE = re.compile(r'<a\s+href=(?P<q1>"|\')(?P<href>.+?)(?P=q1)>(?P<body>.*?)</a>', re.DOTALL | re.IGNORECASE)


def _strip_simple_tags(html_fragment: str) -> str:
    """
    Видаляє прості теги форматування (<b>, <u>, <i>, <strong>, <em>) з фрагмента,
    залишаючи тільки текст усередині.
    """
    # прибираємо відкриваючі/закриваючі теги b/u/i/strong/em (без атрибутів)
    return re.sub(r'</?(?:b|u|i|strong|em)>', '', html_fragment, flags=re.IGNORECASE)

def _collect_links_from_html(text: str) -> list[str]:
    """
    Витягує унікальні посилання: href з HTML + голі URL із очищеного тексту.
    """
    links: list[str] = []
    seen = set()
    if not text:
        return links

    def _clean(u: str) -> str:
        u = _html_mod.unescape(u or "").strip()
        u = u.strip(" '\"<>")
        return u

    for m in re.findall(r'href\s*=\s*(?:"|\')([^"\']+)(?:"|\')', text, flags=re.IGNORECASE):
        u = _clean(m)
        if u and u not in seen:
            seen.add(u)
            links.append(u)

    plain = re.sub(r"<[^>]+>", " ", _html_mod.unescape(text))
    try:
        for u in extract_links_norm(normalize_text(plain)):
            u = _clean(u)
            if u and u not in seen:
                seen.add(u)
                links.append(u)
    except Exception:
        pass

    return links


def _normalize_html_full(html_text: str) -> str:
    """
    Розширена нормалізація HTML для вотчів:
      - застосовує _normalize_html_links (розкриває <a>, приводить &amp; -> &);
      - декодує HTML-ентіті (&quot; -> ", &nbsp; -> пробіл, ...);
      - прибирає службові символи/zero-width/variation selectors;
      - конвертує <br>/<p> у переводи рядків;
      - трохи чистить пробіли/переводи рядків.

    Це якраз фіксить кейси типу:
      <i>&quot;Бывший коллега</i> ...
      <i>"Бывший коллега</i> ...
    щоб вони вважалися однаковими.
    """
    if not html_text:
        return ""

    # 0) нормалізуємо переводи рядків
    html_text = html_text.replace("\r\n", "\n")

    # 1) твоя існуюча нормалізація лінків
    s = _normalize_html_links(html_text)

    # 2) декодуємо HTML-ентіті (&quot; -> ", &nbsp; -> пробіл, &amp; -> &, ...)
    s = _html_mod.unescape(s)

    # 2.1) ігноруємо службовий хештег #реклама (будь-який регістр, з/без лінка)
    s = re.sub(r"<a[^>]*>\s*#\s*реклама\s*</a>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"#\s*реклама\b", "", s, flags=re.IGNORECASE)

    # 3) перетворюємо <br>/<p> у переводи рядків, щоб зрівняти рендери
    s = re.sub(r"<\s*br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</\s*p\s*>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<\s*p\s*>", "", s, flags=re.IGNORECASE)

    # 4) прибираємо невидимі/службові символи (zero-width, variation selectors, BOM)
    s = re.sub(r"[\u200b\u200c\u200d\uFEFF\uFE0F]", "", s)

    # 5) &nbsp; → пробіл (ще раз, якщо лишилось після unescape)
    s = s.replace("\xa0", " ")

    # 6) легка нормалізація пробілів/переводів рядків
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = s.strip()

    return s


def _normalize_html_for_edit(html_text: str) -> str:
    """
    Нормалізація для порівняння редагувань: мінімально прибираємо шум,
    але НЕ стискаємо пробіли/переноси, щоб будь-яка правка (навіть пробіл) фіксувалася.
    """
    if not html_text:
        return ""

    s = html_text.replace("\r\n", "\n")
    s = _normalize_html_links(s)
    s = _html_mod.unescape(s)
    s = re.sub(r"<a[^>]*>\s*#\s*реклама\s*</a>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"#\s*реклама\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"<\s*br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</\s*p\s*>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<\s*p\s*>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"[\u200b\u200c\u200d\uFEFF\uFE0F]", "", s)
    s = s.replace("\xa0", " ")
    # спеціально не стискаємо пробіли/переноси
    return s


def _strip_tags_to_text(html_text: str) -> str:
    """
    Грубо прибирає теги і декодує HTML-ентіті, щоб порівняти лише текст.
    """
    try:
        txt = re.sub(r"<[^>]+>", " ", html_text)
        txt = _html_mod.unescape(txt)
        return re.sub(r"\s+", " ", txt).strip()
    except Exception:
        return html_text


def _normalize_html_links(html: str) -> str:
    """
    Нормалізує HTML так, щоб такі варіанти вважалися однаковими:

      X
      <u>X</u>
      <b><u>X</u></b>
      <a href="X">X</a>
      <a href="X"><u>X</u></a>
      <a href="X"><b><u>X</u></b></a>
      та подібні комбінації форматування навколо X.

    Якщо весь текст усередині <a> після видалення простих тегів дорівнює href,
    ми розкриваємо <a> і залишаємо лише його тіло (з форматуванням).
    """
    if not html:
        return html

    def _replace_a(m: re.Match) -> str:
        href = m.group("href")
        body = m.group("body")

        # Текст усередині <a> без b/u/i/strong/em
        inner_plain = _strip_simple_tags(body)
        # Також прибираємо зайві пробіли
        inner_plain_stripped = inner_plain.strip()
        href_stripped = href.strip()

        if inner_plain_stripped == href_stripped:
            # href і (розформатований) текст однакові → прибираємо сам <a>,
            # але зберігаємо внутрішні теги форматування (<b>, <u>, ...)
            return body
        else:
            # інакше залишаємо <a> як є
            return m.group(0)

    # 1) Нормалізація <a href="X">...</a>, де ... по суті X з простим форматуванням
    html = _A_TAG_RE.sub(_replace_a, html)

    # 2) &amp; → &
    html = html.replace("&amp;", "&")

    # 3) Прибрати зайві пробіли навколо <a> (якщо ще лишилися)
    html = re.sub(r">\s+([^<])", r">\1", html)  # <a ...>  X -> <a ...>X
    html = re.sub(r"([^>])\s+</a>", r"\1</a>", html)  # X  </a> -> X</a>

    return html


# --- Workers -----------------------------------------------------------------


async def _views_worker():
    if not config.WATCH_VIEWS_ENABLED:
        log.info("posts_watch_listener: views disabled")
        return

    log.info("posts_watch_listener: views worker started (tick=%ss)", COVERAGE_POLL_TICK_SEC)
    while True:
        try:
            slots = iter_pool_clients()
            if not slots:
                await asyncio.sleep(COVERAGE_POLL_TICK_SEC)
                continue
            pool_map = {session_name(s.client): s.client for s in slots}
            any_cli = next(iter(pool_map.values()))

            due = watch_proc_db.list_due_coverage()
            for watch_id, channel_id, msg_id, matched_session in due:
                cli = pool_map.get(matched_session) if matched_session else None
                if cli is None:
                    cli = any_cli
                _trace(
                    "views_due",
                    watch_id=watch_id,
                    channel_id=channel_id,
                    message_id=msg_id,
                    matched_session=matched_session,
                    session_used=session_name(cli),
                )
                msg: Message | None = None
                try:
                    msg = await cli.get_messages(entity=channel_id, ids=msg_id)
                except Exception as e:
                    _pylog.exception("views: get_messages failed (wid=%s cid=%s mid=%s): %s", watch_id, channel_id,
                                     msg_id, e)
                    _trace(
                        "views_get_messages_error",
                        watch_id=watch_id,
                        channel_id=channel_id,
                        message_id=msg_id,
                        error=str(e),
                    )
                    # Спроба підвантажити entity через source_url (username/інвайт)
                    fallback_url: str | None = None
                    try:
                        fallback_url = watch_posts_db.get_watch_source_url(watch_id)
                    except Exception:
                        _pylog.exception("views: get_watch_source_url failed (wid=%s)", watch_id)

                    if fallback_url:
                        try:
                            ent = await cli.get_entity(fallback_url)
                            msg = await cli.get_messages(entity=ent, ids=msg_id)
                            _pylog.info(
                                "views: resolved entity via source_url (wid=%s cid=%s url=%s)",
                                watch_id,
                                channel_id,
                                fallback_url,
                            )
                            _trace(
                                "views_fallback_entity",
                                watch_id=watch_id,
                                channel_id=channel_id,
                                message_id=msg_id,
                                fallback_url=fallback_url,
                            )
                        except Exception as e2:
                            _pylog.exception(
                                "views: fallback get_messages failed (wid=%s cid=%s url=%s): %s",
                                watch_id,
                                channel_id,
                                fallback_url,
                                e2,
                            )
                            _trace(
                                "views_fallback_error",
                                watch_id=watch_id,
                                channel_id=channel_id,
                                message_id=msg_id,
                                fallback_url=fallback_url,
                                error=str(e2),
                            )

                    # якщо не змогли отримати entity — вважаємо покритим, щоб не зациклитись
                    if msg is None:
                        try:
                            watch_proc_db.mark_done_views(watch_id, 0)
                            watch_events_db.insert_watch_event(
                                watch_id,
                                "views",
                                json.dumps(
                                    {
                                        "watch_id": watch_id,
                                        "channel_id": channel_id,
                                        "message_id": msg_id,
                                        "views": 0,
                                        "status": "entity_miss",
                                        "reason_code": watch_event_reason_codes.WATCH_EVENT_REASON_CODE_VIEWS_ENTITY_MISS,
                                    }
                                ),
                            )
                        except Exception:
                            _pylog.exception("views: mark_done_views failed (wid=%s) after entity miss", watch_id)
                        msg = None
                        _trace(
                            "views_entity_miss",
                            watch_id=watch_id,
                            channel_id=channel_id,
                            message_id=msg_id,
                            reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_VIEWS_ENTITY_MISS,
                        )

                if msg is None:
                    _pylog.warning(
                        "views: get_messages returned no message (wid=%s cid=%s mid=%s sess=%s)",
                        watch_id,
                        channel_id,
                        msg_id,
                        session_name(cli),
                    )
                    _trace(
                        "views_message_not_found",
                        watch_id=watch_id,
                        channel_id=channel_id,
                        message_id=msg_id,
                        matched_session=matched_session,
                        session_used=session_name(cli),
                        reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_VIEWS_MESSAGE_NOT_FOUND,
                    )
                    continue

                views = int(getattr(msg, "views", 0) or 0)
                _trace(
                    "views_got_message",
                    watch_id=watch_id,
                    channel_id=channel_id,
                    message_id=msg_id,
                    views=views,
                )
                try:
                    watch_proc_db.mark_done_views(watch_id, views)
                    watch_events_db.insert_watch_event(
                        watch_id,
                        "views",
                        json.dumps(
                            {
                                "watch_id": watch_id,
                                "channel_id": channel_id,
                                "message_id": msg_id,
                                "views": views,
                                "reason_code": watch_event_reason_codes.WATCH_EVENT_REASON_CODE_VIEWS_COVERAGE_CHECK,
                            }
                        ),
                    )
                    log.info("views: wid=%s views=%s -> done", watch_id, views)
                    _trace(
                        "views_done",
                        watch_id=watch_id,
                        channel_id=channel_id,
                        message_id=msg_id,
                        views=views,
                        reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_VIEWS_COVERAGE_CHECK,
                    )
                except Exception:
                    _pylog.exception("views: mark_done_views failed (wid=%s)", watch_id)

                if SHEETS_OK and gsheets_buffer:
                    try:
                        gsheets_buffer.record_views(watch_id, views)
                    except Exception:
                        _pylog.exception("gsheets_buffer.record_views failed (wid=%s)", watch_id)

        except asyncio.CancelledError:
            log.warning("views worker cancelled")
            break
        except Exception:
            _pylog.exception("views tick failed")

        await asyncio.sleep(COVERAGE_POLL_TICK_SEC)


async def _pending_expire_worker():
    log.info("posts_watch_listener: pending-expire worker started (tick=%ss)", COVERAGE_POLL_TICK_SEC)
    while True:
        try:
            due_ids = watch_proc_db.list_due_pending_expire()
            for wid in due_ids:
                try:
                    watch_proc_db.mark_expired(wid)
                    watch_events_db.insert_watch_event(
                        wid,
                        "expired",
                        json.dumps(
                            {
                                "watch_id": wid,
                                "reason_code": watch_event_reason_codes.WATCH_EVENT_REASON_CODE_PENDING_WINDOW_EXPIRED,
                            }
                        ),
                    )
                    _trace(
                        "pending_expired",
                        watch_id=wid,
                        reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_PENDING_WINDOW_EXPIRED,
                    )
                    log.info("expire: wid=%s -> expired", wid)
                except Exception:
                    _pylog.exception("expire: mark_expired failed (wid=%s)", wid)

                if SHEETS_OK and gsheets_buffer:
                    try:
                        gsheets_buffer.record_expired(wid)
                    except Exception:
                        _pylog.exception("gsheets_buffer.record_expired failed (wid=%s)", wid)

        except asyncio.CancelledError:
            log.warning("pending-expire worker cancelled")
            break
        except Exception:
            _pylog.exception("pending-expire tick failed")

        await asyncio.sleep(COVERAGE_POLL_TICK_SEC)


async def _reason_code_summary_worker():
    if not WATCH_REASON_CODE_SUMMARY_ENABLED:
        log.info("posts_watch_listener: reason-code summary worker disabled")
        return

    log.info(
        "posts_watch_listener: reason-code summary worker started (tick=%ss)",
        WATCH_REASON_CODE_SUMMARY_FLUSH_INTERVAL_SECONDS,
    )
    while True:
        try:
            await asyncio.sleep(WATCH_REASON_CODE_SUMMARY_FLUSH_INTERVAL_SECONDS)
            reason_code_summary_payload = _consume_reason_code_summary_snapshot()
            if not reason_code_summary_payload:
                continue
            _trace(
                WATCH_REASON_CODE_SUMMARY_TRACE_EVENT_NAME,
                **reason_code_summary_payload,
            )
            _pylog.info(
                "reason-summary: period=(%s..%s) total=%s reasons=%s",
                reason_code_summary_payload.get("period_started_at"),
                reason_code_summary_payload.get("period_finished_at"),
                reason_code_summary_payload.get("total_reasoned_events"),
                reason_code_summary_payload.get("reason_code_counts"),
            )
        except asyncio.CancelledError:
            reason_code_summary_payload = _consume_reason_code_summary_snapshot()
            if reason_code_summary_payload:
                _trace(
                    WATCH_REASON_CODE_SUMMARY_TRACE_EVENT_NAME,
                    **reason_code_summary_payload,
                )
            log.warning("reason-code summary worker cancelled")
            break
        except Exception:
            _pylog.exception("reason-code summary worker tick failed")


def _mark_done_edited_other(wid: int) -> str:
    now_str = _human(moscow_now())
    try:
        db = SessionLocal()
        try:
            db.execute(
                update(m.WatchPost)
                .where(
                    m.WatchPost.id == int(wid),
                    m.WatchPost.status.in_(["matched", "done", "edited"]),
                )
                .values(status="edited", updated_at=now_str)
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
    except Exception:
        _pylog.exception("mark edited-other failed (wid=%s)", wid)
    finally:
        try:
            db.close()
        except Exception:
            pass
    return now_str


# --- Telethon listeners ------------------------------------------------------


def _attach_listener_for_client(tag: str, cli) -> None:
    @cli.on(events.NewMessage())
    async def _on_new_message(ev: events.NewMessage.Event):
        m: Message = ev.message
        #_pylog.info(m)
        cid = None
        # ігноруємо MAIN
        if tag == "MAIN":
            return
        try:
            if hasattr(m, "peer_id") and getattr(m.peer_id, "channel_id", None) is not None:
                cid = int(m.peer_id.channel_id)
            elif getattr(m, "chat_id", None) is not None:
                cid = int(m.chat_id)
        except Exception as e:
            _pylog.info(f"Exception: {m.message}{e}")
            cid = None

        if not cid or cid <= 0:
            return

        mid = int(getattr(m, "id", 0) or 0)

        #_pylog.info("listen: NEW_MESSAGE cid=%s mid=%s session=%s", cid, mid, tag)

        try:
            pending = watch_proc_db.get_pending_by_channel(cid)
        except Exception:
            _pylog.exception("listen: get_pending_by_channel failed (cid=%s)", cid)
            return

        if not pending:
            return

        _pylog.info("listen: found %s pending watches for cid=%s mid=%s sess=%s", len(pending), cid, mid, tag)
        _trace(
            "listen_new_message",
            session=tag,
            channel_id=cid,
            message_id=mid,
            pending_count=len(pending),
        )

        try:
            msg_html = _HTML_RENDER(m) if _HTML_RENDER else (getattr(m, "message", "") or "")
        except Exception:
            _pylog.exception("listen: HTML render failed (cid=%s mid=%s)", cid, mid)
            msg_html = (getattr(m, "message", "") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        matched_any = False

        for row in pending:
            wid = int(row["id"])
            expected_html = row.get("expected_text_hash")
            expected_links_json = row.get("expected_links_json")
            group_id = row.get("group_id")
            if not expected_html:
                _pylog.warning("listen: wid=%s cid=%s mid=%s has no expected_html, skip", wid, cid, mid)
                _trace(
                    "match_skipped_missing_expected_html",
                    watch_id=wid,
                    channel_id=cid,
                    message_id=mid,
                    session=tag,
                    reason=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_MISSING_EXPECTED_HTML,
                    reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_MISSING_EXPECTED_HTML,
                )
                _trace_match_decision_trail(
                    watch_id=wid,
                    channel_id=cid,
                    message_id=mid,
                    session_name=tag,
                    exact_html_match_succeeded=False,
                    html_similarity_ratio=0.0,
                    plain_text_similarity_ratio=0.0,
                    similarity_threshold=CANDIDATE_SIM_THRESHOLD,
                    similarity_threshold_passed=False,
                    links_mismatch_detected=None,
                    final_watch_status="skipped",
                    reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_MISSING_EXPECTED_HTML,
                    expected_links_values=[],
                    actual_links_values=[],
                )
                continue
            _pylog.debug(
                "listen: match_start wid=%s cid=%s mid=%s exp_len=%s links=%s tw=(%s,%s)",
                wid,
                cid,
                mid,
                len(expected_html or ""),
                expected_links_json,
                row.get("time_window_start"),
                row.get("time_window_end"),
            )
            msg_html_norm = msg_html
            expected_html_norm = expected_html
            ratio = 0.0
            ratio_text = 0.0
            expected_plain_text_for_diagnostics = expected_html_norm or ""
            actual_plain_text_for_diagnostics = msg_html_norm or ""
            expected_links_for_diagnostics: list[str] = []
            actual_links_for_diagnostics: list[str] = []

            try:
                # Строга нормалізація: мінімальні правки (пробіл/перенос) не ігноруються.
                msg_html_norm = _normalize_html_for_edit(msg_html)
                expected_html_norm = _normalize_html_for_edit(expected_html)
                ok = exact_html_equal(msg_html_norm, expected_html_norm)
            except Exception:
                _pylog.exception("listen: exact_html_equal failed (wid=%s cid=%s mid=%s)", wid, cid, mid)
                ok = False
            if ok:
                try:
                    expected_links_for_diagnostics = _collect_links_from_html(expected_html_norm)
                except Exception:
                    expected_links_for_diagnostics = []
                try:
                    actual_links_for_diagnostics = _collect_links_from_html(msg_html_norm)
                except Exception:
                    actual_links_for_diagnostics = []
                _pylog.info(
                    "listen: exact_match wid=%s cid=%s mid=%s sess=%s exp_len=%s msg_len=%s",
                    wid,
                    cid,
                    mid,
                    tag,
                    len(expected_html_norm or ""),
                    len(msg_html_norm or ""),
                )
                _trace(
                    "match_exact",
                    watch_id=wid,
                    channel_id=cid,
                    message_id=mid,
                    session=tag,
                    reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_EXACT_HTML_MATCH,
                )
                _trace_match_decision_trail(
                    watch_id=wid,
                    channel_id=cid,
                    message_id=mid,
                    session_name=tag,
                    exact_html_match_succeeded=True,
                    html_similarity_ratio=1.0,
                    plain_text_similarity_ratio=1.0,
                    similarity_threshold=CANDIDATE_SIM_THRESHOLD,
                    similarity_threshold_passed=True,
                    links_mismatch_detected=False,
                    final_watch_status="matched",
                    reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_EXACT_HTML_MATCH,
                    expected_links_values=expected_links_for_diagnostics,
                    actual_links_values=actual_links_for_diagnostics,
                )
            _pylog.debug(
                "similar_check: wid=%s cid=%s mid=%s ok=%s exp_len=%s msg_len=%s",
                wid,
                cid,
                mid,
                ok,
                len(expected_html_norm or ""),
                len(msg_html_norm or ""),
            )

            if not ok:
                try:
                    exp_links_dbg = _collect_links_from_html(expected_html_norm)
                except Exception:
                    exp_links_dbg = []
                try:
                    msg_links_dbg = _collect_links_from_html(msg_html_norm)
                except Exception:
                    msg_links_dbg = []
                try:
                    msg_plain = _strip_tags_to_text(msg_html_norm)
                    expected_plain = _strip_tags_to_text(expected_html_norm)
                except Exception:
                    msg_plain = msg_html_norm
                    expected_plain = expected_html_norm
                expected_links_for_diagnostics = list(exp_links_dbg)
                actual_links_for_diagnostics = list(msg_links_dbg)
                expected_plain_text_for_diagnostics = expected_plain or ""
                actual_plain_text_for_diagnostics = msg_plain or ""
                _pylog.debug(
                    "listen: no_exact wid=%s cid=%s mid=%s exp_links=%s msg_links=%s "
                    "exp_snip=%r msg_snip=%r plain_exp_snip=%r plain_msg_snip=%r",
                    wid,
                    cid,
                    mid,
                    exp_links_dbg,
                    msg_links_dbg,
                    (expected_html_norm or "")[:120],
                    (msg_html_norm or "")[:120],
                    (expected_plain or "")[:120],
                    (msg_plain or "")[:120],
                )
                # Фаззі-перевірка схожості (якщо дуже схоже, додаємо в кандидати)
                try:
                    ratio = SequenceMatcher(None, msg_html_norm, expected_html_norm).ratio()
                except Exception:
                    ratio = 0.0
                ratio_text = 0.0
                try:
                    msg_plain = _strip_tags_to_text(msg_html_norm)
                    expected_plain = _strip_tags_to_text(expected_html_norm)
                    ratio_text = SequenceMatcher(None, msg_plain, expected_plain).ratio()
                except Exception:
                    ratio_text = 0.0

                if ratio >= CANDIDATE_SIM_THRESHOLD or ratio_text >= CANDIDATE_SIM_THRESHOLD:
                    _pylog.debug(
                        "listen: fuzzy_candidate wid=%s cid=%s mid=%s ratio=%.3f ratio_text=%.3f",
                        wid,
                        cid,
                        mid,
                        ratio,
                        ratio_text,
                    )
                    # якщо лінки не збігаються — відправляємо у foreign
                    exp_links = _collect_links_from_html(expected_html_norm)
                    if not exp_links and expected_links_json:
                        try:
                            data = json.loads(expected_links_json)
                            if isinstance(data, list):
                                exp_links = [str(x) for x in data if x]
                        except Exception:
                            pass
                    cand_links = _collect_links_from_html(msg_html_norm)
                    expected_links_for_diagnostics = list(exp_links)
                    actual_links_for_diagnostics = list(cand_links)

                    links_mismatch = False
                    if exp_links and cand_links and sorted(exp_links) != sorted(cand_links):
                        links_mismatch = True
                    elif not exp_links and cand_links:
                        # якщо очікуваних лінків немає, а у фактичному повідомленні вони є — теж вважаємо mismatch
                        links_mismatch = True
                    _pylog.debug(
                        "links_compare: wid=%s cid=%s mid=%s exp=%d msg=%d mismatch=%s exp_raw=%s msg_raw=%s",
                        wid,
                        cid,
                        mid,
                        len(exp_links),
                        len(cand_links),
                        links_mismatch,
                        exp_links,
                        cand_links,
                    )

                    if links_mismatch:
                        expected_links_for_diagnostics = list(exp_links)
                        actual_links_for_diagnostics = list(cand_links)
                        try:
                            watch_proc_db.insert_watch_candidate(
                                watch_id=wid,
                                channel_id=cid,
                                message_id=mid,
                                similarity=ratio,
                                message_text=msg_html,
                                text_hash="",
                                ttl_days=1.0,
                                status="foreign",
                            )
                            try:
                                watch_events_db.insert_watch_event(
                                    wid,
                                    "foreign",
                                    json.dumps(
                                        {
                                            "watch_id": wid,
                                            "channel_id": cid,
                                            "message_id": mid,
                                            "similarity": ratio,
                                            "reason": watch_event_reason_codes.WATCH_EVENT_REASON_CODE_LINKS_MISMATCH,
                                            "reason_code": watch_event_reason_codes.WATCH_EVENT_REASON_CODE_LINKS_MISMATCH,
                                        }
                                    ),
                                )
                            except Exception:
                                _pylog.exception("similar: insert foreign event failed (wid=%s cid=%s mid=%s)", wid, cid, mid)
                            log.info("similar: wid=%s cid=%s mid=%s ratio=%.3f -> foreign (links mismatch)", wid, cid, mid, ratio)
                            _trace(
                                "match_foreign_links_mismatch",
                                watch_id=wid,
                                channel_id=cid,
                                message_id=mid,
                                similarity=ratio,
                                similarity_text=ratio_text,
                                similarity_threshold=CANDIDATE_SIM_THRESHOLD,
                                reason=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_LINKS_MISMATCH,
                                reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_LINKS_MISMATCH,
                                expected_links=exp_links,
                                candidate_links=cand_links,
                                **_build_match_diagnostics_payload(
                                    expected_html_text=expected_html_norm or "",
                                    actual_html_text=msg_html_norm or "",
                                    expected_plain_text=expected_plain_text_for_diagnostics,
                                    actual_plain_text=actual_plain_text_for_diagnostics,
                                    expected_links_values=expected_links_for_diagnostics,
                                    actual_links_values=actual_links_for_diagnostics,
                                ),
                            )
                            _trace_match_decision_trail(
                                watch_id=wid,
                                channel_id=cid,
                                message_id=mid,
                                session_name=tag,
                                exact_html_match_succeeded=False,
                                html_similarity_ratio=ratio,
                                plain_text_similarity_ratio=ratio_text,
                                similarity_threshold=CANDIDATE_SIM_THRESHOLD,
                                similarity_threshold_passed=True,
                                links_mismatch_detected=True,
                                final_watch_status="foreign",
                                reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_LINKS_MISMATCH,
                                expected_links_values=expected_links_for_diagnostics,
                                actual_links_values=actual_links_for_diagnostics,
                            )
                        except Exception:
                            _pylog.exception("similar: insert foreign candidate failed (wid=%s cid=%s mid=%s)", wid, cid, mid)
                        continue

                    text_hash_input = msg_plain or msg_html_norm
                    text_hash = watch_proc_db.calc_text_hash(text_hash_input)
                    key = (wid, text_hash)
                    now_m = _now_monotonic()
                    last_seen = _GLOBAL_CANDIDATE_SEEN.get(key)
                    if last_seen is None or (now_m - last_seen) >= CANDIDATE_SEEN_TTL:
                        _GLOBAL_CANDIDATE_SEEN[key] = now_m

                        try:
                            watch_proc_db.insert_watch_candidate(
                                watch_id=wid,
                                channel_id=cid,
                                message_id=mid,
                                similarity=ratio,
                                message_text=msg_html,
                                text_hash=text_hash,
                                ttl_days=1.0,
                                status=watch_candidates_db.CANDIDATE_PENDING_STATUS,
                            )
                            try:
                                watch_events_db.insert_watch_event(
                                    wid,
                                    "candidate",
                                    json.dumps(
                                        {
                                            "watch_id": wid,
                                            "channel_id": cid,
                                            "message_id": mid,
                                            "similarity": ratio,
                                            "text_hash": text_hash,
                                            "reason_code": (
                                                watch_event_reason_codes.WATCH_EVENT_REASON_CODE_SIMILARITY_ABOVE_THRESHOLD
                                            ),
                                        }
                                    ),
                                )
                            except Exception:
                                _pylog.exception("similar: insert candidate event failed (wid=%s cid=%s mid=%s)", wid, cid, mid)
                            log.info("similar: wid=%s cid=%s mid=%s ratio=%.3f -> candidate", wid, cid, mid, ratio)
                            _trace(
                                "match_candidate",
                                watch_id=wid,
                                channel_id=cid,
                                message_id=mid,
                                similarity=ratio,
                                similarity_text=ratio_text,
                                similarity_threshold=CANDIDATE_SIM_THRESHOLD,
                                text_hash=text_hash,
                                reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_SIMILARITY_ABOVE_THRESHOLD,
                                **_build_match_diagnostics_payload(
                                    expected_html_text=expected_html_norm or "",
                                    actual_html_text=msg_html_norm or "",
                                    expected_plain_text=expected_plain_text_for_diagnostics,
                                    actual_plain_text=actual_plain_text_for_diagnostics,
                                    expected_links_values=expected_links_for_diagnostics,
                                    actual_links_values=actual_links_for_diagnostics,
                                ),
                            )
                            _trace_match_decision_trail(
                                watch_id=wid,
                                channel_id=cid,
                                message_id=mid,
                                session_name=tag,
                                exact_html_match_succeeded=False,
                                html_similarity_ratio=ratio,
                                plain_text_similarity_ratio=ratio_text,
                                similarity_threshold=CANDIDATE_SIM_THRESHOLD,
                                similarity_threshold_passed=True,
                                links_mismatch_detected=False,
                                final_watch_status="candidate",
                                reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_SIMILARITY_ABOVE_THRESHOLD,
                                expected_links_values=expected_links_for_diagnostics,
                                actual_links_values=actual_links_for_diagnostics,
                            )
                        except Exception:
                            _pylog.exception("similar: insert_watch_candidate failed (wid=%s cid=%s mid=%s)", wid, cid, mid)
                    else:
                        candidate_seen_age_seconds = now_m - last_seen
                        _pylog.info(
                            "similar: wid=%s cid=%s mid=%s ratio=%.3f -> candidate_suppressed "
                            "(duplicate within ttl age=%.1fs ttl=%ss)",
                            wid,
                            cid,
                            mid,
                            ratio,
                            candidate_seen_age_seconds,
                            CANDIDATE_SEEN_TTL,
                        )
                        _trace(
                            "match_candidate_suppressed_duplicate_ttl",
                            watch_id=wid,
                            channel_id=cid,
                            message_id=mid,
                            session=tag,
                            similarity=ratio,
                            similarity_text=ratio_text,
                            similarity_threshold=CANDIDATE_SIM_THRESHOLD,
                            text_hash=text_hash,
                            duplicate_seen_age_seconds=candidate_seen_age_seconds,
                            duplicate_ttl_seconds=CANDIDATE_SEEN_TTL,
                            reason=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_CANDIDATE_DUPLICATE_WITHIN_TTL,
                            reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_CANDIDATE_DUPLICATE_WITHIN_TTL,
                            **_build_match_diagnostics_payload(
                                expected_html_text=expected_html_norm or "",
                                actual_html_text=msg_html_norm or "",
                                expected_plain_text=expected_plain_text_for_diagnostics,
                                actual_plain_text=actual_plain_text_for_diagnostics,
                                expected_links_values=expected_links_for_diagnostics,
                                actual_links_values=actual_links_for_diagnostics,
                            ),
                        )
                        _trace_match_decision_trail(
                            watch_id=wid,
                            channel_id=cid,
                            message_id=mid,
                            session_name=tag,
                            exact_html_match_succeeded=False,
                            html_similarity_ratio=ratio,
                            plain_text_similarity_ratio=ratio_text,
                            similarity_threshold=CANDIDATE_SIM_THRESHOLD,
                            similarity_threshold_passed=True,
                            links_mismatch_detected=False,
                            final_watch_status="candidate_suppressed_duplicate",
                            reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_CANDIDATE_DUPLICATE_WITHIN_TTL,
                            expected_links_values=expected_links_for_diagnostics,
                            actual_links_values=actual_links_for_diagnostics,
                        )
                else:
                    _pylog.info(
                        "listen: no_match wid=%s cid=%s mid=%s sess=%s ratio=%.3f ratio_text=%.3f reason=ratio_low",
                        wid,
                        cid,
                        mid,
                        tag,
                        ratio,
                        ratio_text,
                    )
                    _trace(
                        "match_no_match",
                        watch_id=wid,
                        channel_id=cid,
                        message_id=mid,
                        session=tag,
                        similarity=ratio,
                        similarity_text=ratio_text,
                        similarity_threshold=CANDIDATE_SIM_THRESHOLD,
                        reason=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_SIMILARITY_BELOW_THRESHOLD,
                        reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_SIMILARITY_BELOW_THRESHOLD,
                        **_build_match_diagnostics_payload(
                            expected_html_text=expected_html_norm or "",
                            actual_html_text=msg_html_norm or "",
                            expected_plain_text=expected_plain_text_for_diagnostics,
                            actual_plain_text=actual_plain_text_for_diagnostics,
                            expected_links_values=expected_links_for_diagnostics,
                            actual_links_values=actual_links_for_diagnostics,
                        ),
                    )
                    _trace_match_decision_trail(
                        watch_id=wid,
                        channel_id=cid,
                        message_id=mid,
                        session_name=tag,
                        exact_html_match_succeeded=False,
                        html_similarity_ratio=ratio,
                        plain_text_similarity_ratio=ratio_text,
                        similarity_threshold=CANDIDATE_SIM_THRESHOLD,
                        similarity_threshold_passed=False,
                        links_mismatch_detected=None,
                        final_watch_status="no_match",
                        reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_SIMILARITY_BELOW_THRESHOLD,
                        expected_links_values=expected_links_for_diagnostics,
                        actual_links_values=actual_links_for_diagnostics,
                    )
                continue

            # exact match пройшов — фіксуємо matched
            coverage_at = _calc_coverage_at()
            matched_session = tag
            matched_ok = True
            try:
                watch_proc_db.mark_matched(wid, mid, coverage_at, matched_session=matched_session)
                watch_events_db.insert_watch_event(
                    wid,
                    "matched",
                    json.dumps(
                        {
                            "watch_id": wid,
                            "channel_id": cid,
                            "message_id": mid,
                            "session": matched_session,
                            "reason_code": watch_event_reason_codes.WATCH_EVENT_REASON_CODE_EXACT_HTML_MATCH,
                        }
                    ),
                )
            except Exception:
                matched_ok = False

            if matched_ok:
                matched_any = True
                if SHEETS_OK and gsheets_buffer:
                    try:
                        gsheets_buffer.record_matched(wid)
                    except Exception:
                        _pylog.exception("gsheets_buffer.record_matched failed (wid=%s)", wid)

    @cli.on(events.MessageEdited())
    async def _on_edited(ev: events.MessageEdited.Event):
        m: Message = ev.message

        cid = None
        try:
            if hasattr(m, "peer_id") and getattr(m.peer_id, "channel_id", None) is not None:
                cid = int(m.peer_id.channel_id)
            elif getattr(m, "chat_id", None) is not None:
                cid = int(m.chat_id)
        except Exception:
            cid = None

        if not cid or cid <= 0:
            return

        mid = int(getattr(m, "id", 0) or 0)
        if not mid:
            return

        try:
            wids = watch_proc_db.find_matched_by_message(cid, mid)
        except Exception:
            _pylog.exception("edited: find_matched_by_message failed (cid=%s mid=%s)", cid, mid)
            return

        candidate_entries: list[Dict[str, Any]] = []
        if not wids:
            try:
                candidate_entries = watch_candidates_db.find_candidates_by_channel_message(
                    cid, mid, status=watch_candidates_db.CANDIDATE_PENDING_STATUS
                )
            except Exception:
                _pylog.exception("edited: find_candidates_by_channel_message failed (cid=%s mid=%s)", cid, mid)
                candidate_entries = []
            if not candidate_entries:
                return

        try:
            msg_html = _HTML_RENDER(m) if _HTML_RENDER else (getattr(m, "message", "") or "")
        except Exception:
            _pylog.exception("edited: HTML render failed (cid=%s mid=%s)", cid, mid)
            msg_html = (getattr(m, "message", "") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        target_wids = wids if wids else [int(c.get("watch_id")) for c in candidate_entries if c.get("watch_id")]

        for wid in target_wids:
            wc = _db_get_watch_core(int(wid))
            if not wc:
                continue
            expected_html = wc.get("expected_text_hash")
            if not expected_html:
                continue

            try:
                msg_html_norm = _normalize_html_for_edit(msg_html)
                expected_html_norm = _normalize_html_for_edit(expected_html)
                # Для edit: або повна ідентичність, або допускаємо дуже малу різницю (ratio>=EDIT_NEAR_THRESHOLD) без зміни лінків
                ok = msg_html_norm == expected_html_norm
                diff_ratio = 1.0
                links_same = True
                if not ok:
                    try:
                        exp_links = sorted(_collect_links_from_html(expected_html_norm))
                        msg_links = sorted(_collect_links_from_html(msg_html_norm))
                        links_same = exp_links == msg_links
                    except Exception:
                        links_same = True
                    try:
                        diff_ratio = SequenceMatcher(None, msg_html_norm, expected_html_norm).ratio()
                    except Exception:
                        diff_ratio = 0.0
                    if diff_ratio >= EDIT_NEAR_THRESHOLD and links_same:
                        ok = True
                        _pylog.debug(
                            "edited: wid=%s cid=%s mid=%s diff_ratio=%.3f (links unchanged) -> skip minor edit",
                            wid,
                            cid,
                            mid,
                            diff_ratio,
                        )
            except Exception:
                _pylog.exception("edited: exact_html_equal failed (wid=%s cid=%s mid=%s)", wid, cid, mid)
                ok = False

            if ok:
                continue

            # Лог додаткових даних для аналізу відмінностей
            try:
                diff_ratio = SequenceMatcher(None, msg_html_norm, expected_html_norm).ratio()
            except Exception:
                diff_ratio = 0.0
            _pylog.info(
                "edited: wid=%s cid=%s mid=%s -> edited (ratio=%.3f exp_len=%s msg_len=%s)",
                wid,
                cid,
                mid,
                diff_ratio,
                len(expected_html_norm or ""),
                len(msg_html_norm or ""),
            )

            now_str = _mark_done_edited_other(int(wid))
            event_type = "edited_other" if wid in wids else "edited_candidate"
            try:
                watch_events_db.insert_watch_event(
                    int(wid),
                    event_type,
                    json.dumps(
                        {
                            "watch_id": int(wid),
                            "channel_id": cid,
                            "message_id": mid,
                            "edited_at": now_str,
                            "reason_code": watch_event_reason_codes.WATCH_EVENT_REASON_CODE_EDIT_DETECTED,
                        }
                    ),
                )
            except Exception:
                pass
            _trace(
                "edited_other_detected",
                watch_id=int(wid),
                channel_id=cid,
                message_id=mid,
                event_type=event_type,
                edited_at=now_str,
                reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_EDIT_DETECTED,
            )

            if wid not in wids and candidate_entries:
                for c in candidate_entries:
                    if int(c.get("watch_id") or 0) != int(wid):
                        continue
                    try:
                        msg_plain = _strip_tags_to_text(msg_html_norm)
                        expected_plain = _strip_tags_to_text(expected_html_norm)
                        sim_val = SequenceMatcher(None, msg_plain, expected_plain).ratio()
                    except Exception:
                        sim_val = 0.0
                    try:
                        watch_candidates_db.merge_watch_candidate(
                            int(c.get("id")),
                            mid,
                            watch_proc_db.calc_text_hash(msg_html_norm),
                            sim_val,
                            msg_html_norm,
                        )
                    except Exception:
                        _pylog.exception("edited: merge_watch_candidate failed (cid=%s mid=%s cand_id=%s)", cid, mid, c.get("id"))

            log.info("edited: wid=%s cid=%s mid=%s -> edited_other at=%s", wid, cid, mid, now_str)

            if SHEETS_OK and gsheets_buffer:
                try:
                    gsheets_buffer.record_edited_other_post(int(wid), now_str)
                except Exception:
                    _pylog.exception("gsheets_buffer.record_edited_other_post failed (wid=%s)", wid)

    @cli.on(events.MessageDeleted())
    async def _on_deleted(ev: events.MessageDeleted.Event):
        cid: Optional[int] = None

        try:
            chat = await ev.get_chat()
            if chat is not None and getattr(chat, "id", None) is not None:
                cid = int(chat.id)
        except Exception:
            cid = None

        if not cid:
            try:
                raw = int(getattr(ev, "chat_id", 0) or 0)
                if raw:
                    cid = abs(raw)
                    if cid > 10 ** 12:
                        cid = cid - 10 ** 12
            except Exception:
                cid = None

        if not cid or cid <= 0:
            return

        for mid in (ev.deleted_ids or []):
            try:
                wids = watch_proc_db.find_matched_by_message(cid, int(mid))
            except Exception:
                _pylog.exception("deleted: DB lookup failed (cid=%s mid=%s)", cid, mid)
                continue

            if not wids:
                continue

            now_m = _now_monotonic()

            for wid in wids:
                last = _GLOBAL_DELETED_SEEN.get(wid)
                if last is not None and (now_m - last) < GLOBAL_DELETED_TTL:
                    continue
                _GLOBAL_DELETED_SEEN[wid] = now_m

                try:
                    prev_status = watch_proc_db.mark_done_deleted(wid)
                except Exception:
                    _pylog.exception("deleted: mark_done_deleted failed (wid=%s)", wid)
                    continue

                # Якщо пост уже відстояв перегляди (status=done), не шлемо повторну подію
                if prev_status == "done":
                    log.info("deleted: wid=%s cid=%s mid=%s -> status done, event skipped", wid, cid, mid)
                    continue

                try:
                    watch_events_db.insert_watch_event(
                        wid,
                        "deleted",
                        json.dumps(
                            {
                                "watch_id": wid,
                                "channel_id": cid,
                                "message_id": int(mid),
                                "reason_code": watch_event_reason_codes.WATCH_EVENT_REASON_CODE_MESSAGE_DELETED,
                            }
                        ),
                    )
                    _trace(
                        "deleted_detected",
                        watch_id=wid,
                        channel_id=cid,
                        message_id=int(mid),
                        reason_code=watch_event_reason_codes.WATCH_EVENT_REASON_CODE_MESSAGE_DELETED,
                    )
                    log.info("deleted: wid=%s cid=%s mid=%s -> deleted", wid, cid, mid)
                except Exception:
                    _pylog.exception("deleted: insert_watch_event failed (wid=%s)", wid)

                if SHEETS_OK and gsheets_buffer:
                    try:
                        gsheets_buffer.record_deleted(wid)
                    except Exception:
                        _pylog.exception("gsheets_buffer.record_deleted failed (wid=%s)", wid)


# --- Setup -------------------------------------------------------------------


def setup(client=None, control_peer=None, monitor_buffer=None, **_):
    active_channels = set(watch_proc_db.list_active_channels())
    log.info("posts_watch_listener: active_channels=%s", len(active_channels))

    if SHEETS_OK and gsheets_buffer:
        try:
            gsheets_buffer.set_flush_interval(15)
            gsheets_buffer.start_flusher()
            log.info("posts_watch_listener: gsheets_buffer flusher started")
        except Exception:
            _pylog.exception("failed to start gsheets_buffer flusher")

    slots = iter_pool_clients()
    for s in slots:
        try:
            tag = session_name(s.client)
            _attach_listener_for_client(tag, s.client)
            log.info("posts_watch_listener: attached listener to pool client: %s %s", tag, s.client)
        except Exception:
            _pylog.exception("attach failed for pool client: %s", getattr(s, "name", "?"))

    # _attach_listener_for_client("MAIN", MAIN_CLIENT)
    # log.info("posts_watch_listener: attached listener to MAIN client")

    loop = asyncio.get_event_loop()

    if config.WATCH_VIEWS_ENABLED:
        loop.create_task(_views_worker(), name="posts_watch_views")
        log.info("posts_watch_listener: views worker scheduled")

    loop.create_task(_pending_expire_worker(), name="posts_watch_expire_pending")
    log.info("posts_watch_listener: pending-expire worker scheduled")

    if WATCH_REASON_CODE_SUMMARY_ENABLED:
        loop.create_task(_reason_code_summary_worker(), name="posts_watch_reason_code_summary")
        log.info("posts_watch_listener: reason-code summary worker scheduled")

    try:
        missing = watch_proc_db.list_pending_without_expected(limit=50)
        if missing:
            _pylog.warning("health-check: pending watches without expected_html: count=%s sample=%s", len(missing), missing[:10])
    except Exception:
        _pylog.exception("health-check: list_pending_without_expected failed")
