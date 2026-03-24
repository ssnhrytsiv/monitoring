from __future__ import annotations

import html
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, List, Optional

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from sqlalchemy.exc import IntegrityError

from app.DAL import post_templates_operations as watch_post_templates_db
from app.DAL.watch_candidates_operations import (
    CANDIDATE_PENDING_STATUS,
    accept_watch_candidate,
    get_watch_candidate,
    get_watch_expected_links,
    get_watch_expected_text,
    list_candidates_by_hash,
    list_group_watch_candidates,
    set_watch_candidate_status,
)
from app.DAL import watch_posts_operations as watch_posts_db
from app.DAL.notifier_message_pages_operations import (
    bind_notification_page_session_to_message,
    count_notification_pages_for_message_session,
    count_notification_pages_for_session,
    create_notification_page_session_records,
    delete_notification_page_records_for_message,
    delete_notification_page_session_records,
    get_notification_page_text_for_message,
    get_notification_page_text_for_session,
)
from app.db.session import SessionLocal
from app.notificator_bot.models import NotifierMessage
from app.watch_bot.services.active_watches_service import cancel_group_watches
from app.watch_bot.services.channels_repo import get_links_by_channel_ids, get_titles_by_channel_ids


NOTIFICATION_PAGE_CALLBACK_PREFIX = "notifier_page"
NOTIFICATION_PAGE_NOOP_CALLBACK_DATA = "notifier_page_noop"
NOTIFICATION_MANAGE_CALLBACK_PREFIX = "notifier_manage"
NOTIFICATION_PREVIEW_CALLBACK_PREFIX = "notifier_preview"

log = logging.getLogger("notificator.handlers")

ANIMATION_PREFIX = "animation:"
VIDEO_PREFIX = "video:"
PHOTO_PREFIX = "photo:"
V2_MEDIA_PREFIX = "v2media:"
DEFAULT_MEDIA_VARIANT_KEY = "default"

DEFAULT_TESTING_DB_PATH = Path(__file__).resolve().parents[4] / "my_project.db"


def _resolve_testing_db_path() -> Path:
    raw_env_value = str(os.getenv("TESTING_DB_PATH") or os.getenv("MAIN_DB_PATH") or "").strip()
    if raw_env_value:
        return Path(raw_env_value).expanduser().resolve()
    return DEFAULT_TESTING_DB_PATH.resolve()


def _to_int_or_none(value: Any) -> Optional[int]:
    try:
        normalized = int(str(value).strip())
    except Exception:
        return None
    if normalized == 0:
        return None
    return normalized


def _is_media_unavailable_error(exception: TelegramBadRequest) -> bool:
    normalized_error_text = str(exception).lower()
    return (
        "wrong file identifier" in normalized_error_text
        or "failed to get http url content" in normalized_error_text
        or "media_empty" in normalized_error_text
    )


def _decode_template_media_id(raw_media_id: Optional[str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "media_type": None,
        "media_id": None,
        "vault_chat_id": None,
        "vault_message_id": None,
    }
    if raw_media_id is None:
        return result

    media_id_value = str(raw_media_id).strip()
    if not media_id_value or media_id_value.lower() in {"none", "null"}:
        return result

    if media_id_value.startswith(V2_MEDIA_PREFIX):
        payload_raw = media_id_value.removeprefix(V2_MEDIA_PREFIX).strip()
        if not payload_raw:
            return result
        try:
            payload = json.loads(payload_raw)
        except Exception:
            return result
        if not isinstance(payload, dict):
            return result

        media_type = str(payload.get("type") or "photo").strip().lower()
        if media_type not in {"photo", "video", "animation"}:
            media_type = "photo"

        vault_payload = payload.get("vault")
        if isinstance(vault_payload, dict):
            vault_chat_id = _to_int_or_none(vault_payload.get("chat_id"))
            vault_message_id = _to_int_or_none(vault_payload.get("message_id"))
            if vault_chat_id and vault_message_id:
                result["vault_chat_id"] = vault_chat_id
                result["vault_message_id"] = vault_message_id

        ids = payload.get("ids")
        if not isinstance(ids, dict):
            return result

        candidate = ids.get(DEFAULT_MEDIA_VARIANT_KEY) or next((value for value in ids.values() if value), None)
        if candidate:
            candidate_id = str(candidate).strip()
            if candidate_id:
                result["media_type"] = media_type
                result["media_id"] = candidate_id
        return result

    if media_id_value.startswith(ANIMATION_PREFIX):
        animation_id = media_id_value.removeprefix(ANIMATION_PREFIX).strip()
        if animation_id:
            result["media_type"] = "animation"
            result["media_id"] = animation_id
        return result
    if media_id_value.startswith(VIDEO_PREFIX):
        video_id = media_id_value.removeprefix(VIDEO_PREFIX).strip()
        if video_id:
            result["media_type"] = "video"
            result["media_id"] = video_id
        return result
    if media_id_value.startswith(PHOTO_PREFIX):
        photo_id = media_id_value.removeprefix(PHOTO_PREFIX).strip()
        if photo_id:
            result["media_type"] = "photo"
            result["media_id"] = photo_id
        return result

    result["media_type"] = "photo"
    result["media_id"] = media_id_value
    return result


def _normalize_template_title_for_lookup(raw_title: str) -> str:
    value = str(raw_title or "").strip().lower().replace("ё", "е")
    # Normalize punctuation variants so "АМ БЕТ", "АМ БЕТ:", "1:0:" and "1 0" can match.
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _fetch_testing_template_by_title(template_title: str) -> Optional[dict[str, Any]]:
    normalized_title = str(template_title or "").strip()
    if not normalized_title:
        return None

    db_path = _resolve_testing_db_path()
    if not db_path.exists():
        return None

    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            SELECT post_id, name, text, photo_id
            FROM post_templates
            WHERE name = ?
            ORDER BY post_id DESC
            LIMIT 1
            """,
            (normalized_title,),
        ).fetchone()
        if not row:
            normalized_lookup_title = _normalize_template_title_for_lookup(normalized_title)
            if not normalized_lookup_title:
                return None
            candidate_rows = connection.execute(
                """
                SELECT post_id, name, text, photo_id
                FROM post_templates
                WHERE name IS NOT NULL AND TRIM(name) != ''
                ORDER BY post_id DESC
                LIMIT 1200
                """
            ).fetchall()
            for candidate_row in candidate_rows:
                candidate_name = str(candidate_row["name"] or "").strip()
                if not candidate_name:
                    continue
                if _normalize_template_title_for_lookup(candidate_name) != normalized_lookup_title:
                    continue
                row = candidate_row
                break
            if not row:
                return None
        return {
            "post_id": int(row["post_id"]),
            "name": str(row["name"] or ""),
            "text": str(row["text"] or ""),
            "photo_id": str(row["photo_id"] or "") if row["photo_id"] is not None else None,
        }
    except Exception:
        log.exception("Failed to fetch testing template by title=%r from db=%s", normalized_title, db_path)
        return None
    finally:
        connection.close()


def _fetch_testing_template_by_text(template_text: str) -> Optional[dict[str, Any]]:
    normalized_text = str(template_text or "").strip()
    if not normalized_text:
        return None

    db_path = _resolve_testing_db_path()
    if not db_path.exists():
        return None

    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            SELECT post_id, name, text, photo_id
            FROM post_templates
            WHERE text = ?
            ORDER BY post_id DESC
            LIMIT 1
            """,
            (normalized_text,),
        ).fetchone()
        if not row:
            return None
        return {
            "post_id": int(row["post_id"]),
            "name": str(row["name"] or ""),
            "text": str(row["text"] or ""),
            "photo_id": str(row["photo_id"] or "") if row["photo_id"] is not None else None,
        }
    except Exception:
        log.exception("Failed to fetch testing template by text from db=%s", db_path)
        return None
    finally:
        connection.close()


def _resolve_notifier_context(chat_id: int, message_id: int) -> Optional[dict[str, Any]]:
    db = SessionLocal()
    try:
        row = (
            db.query(NotifierMessage)
            .filter(
                NotifierMessage.chat_id == int(chat_id),
                NotifierMessage.message_id == int(message_id),
            )
            .order_by(NotifierMessage.id.desc())
            .first()
        )
        if not row:
            return None
        return {
            "chat_id": int(row.chat_id),
            "project": str(row.project or ""),
            "admin": str(row.admin or ""),
            "group_id": int(row.group_id),
        }
    finally:
        db.close()


def _update_notifier_message_binding(*, context: Optional[dict[str, Any]], new_message_id: int) -> None:
    if not context:
        return

    db = SessionLocal()
    try:
        row = (
            db.query(NotifierMessage)
            .filter(
                NotifierMessage.chat_id == int(context["chat_id"]),
                NotifierMessage.project == str(context.get("project") or ""),
                NotifierMessage.admin == str(context.get("admin") or ""),
                NotifierMessage.group_id == int(context["group_id"]),
            )
            .first()
        )
        if not row:
            return
        row.message_id = int(new_message_id)
        row.updated_at = int(time.time())
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Failed to update notifier message binding context=%s new_message_id=%s", context, new_message_id)
    finally:
        db.close()


def _resolve_template_payload_for_group(group_id: int) -> Optional[dict[str, Any]]:
    try:
        group_watches = watch_posts_db.fetch_watches_by_group(int(group_id))
    except Exception:
        log.exception("Failed to fetch watches for group_id=%s", group_id)
        return None
    if not group_watches:
        return None

    leader_watch_id = int(group_watches[0]["id"])
    try:
        watch_info = watch_posts_db.get_watch_info(leader_watch_id) or {}
    except Exception:
        log.exception("Failed to fetch watch info for watch_id=%s", leader_watch_id)
        watch_info = {}

    template_title = str(watch_info.get("title") or group_watches[0].get("title") or "").strip()
    expected_html = str(watch_info.get("expected_text_hash") or "").strip()

    monitor_template_text = ""
    monitor_template_title = ""
    monitor_template_photo_id = None

    template_id_raw = watch_info.get("template_id")
    try:
        template_id = int(template_id_raw) if template_id_raw is not None else None
    except Exception:
        template_id = None

    if template_id:
        template_row = watch_post_templates_db.get_template_by_id(int(template_id))
        if template_row:
            monitor_template_text = str(template_row[1] or "")
            monitor_template_title = str(template_row[5] or "")
            monitor_template_photo_id = str(template_row[7] or "").strip() or None

    lookup_title = monitor_template_title or template_title

    if monitor_template_text and monitor_template_photo_id:
        media_payload = _decode_template_media_id(monitor_template_photo_id)
        return {
            "title": lookup_title,
            "text": monitor_template_text,
            "media_type": media_payload.get("media_type"),
            "media_id": media_payload.get("media_id"),
            "vault_chat_id": media_payload.get("vault_chat_id"),
            "vault_message_id": media_payload.get("vault_message_id"),
            "source": "monitoring_post_template",
        }

    testing_template = _fetch_testing_template_by_title(lookup_title)
    if not testing_template and template_title and template_title != lookup_title:
        testing_template = _fetch_testing_template_by_title(template_title)
    if not testing_template and monitor_template_title and monitor_template_title != lookup_title:
        testing_template = _fetch_testing_template_by_title(monitor_template_title)
    if not testing_template and monitor_template_text:
        testing_template = _fetch_testing_template_by_text(monitor_template_text)
    if not testing_template and expected_html:
        testing_template = _fetch_testing_template_by_text(expected_html)

    if testing_template:
        media_payload = _decode_template_media_id(testing_template.get("photo_id"))
        return {
            "title": str(testing_template.get("name") or lookup_title or ""),
            "text": str(testing_template.get("text") or ""),
            "media_type": media_payload.get("media_type"),
            "media_id": media_payload.get("media_id"),
            "vault_chat_id": media_payload.get("vault_chat_id"),
            "vault_message_id": media_payload.get("vault_message_id"),
            "source": "testing_post_templates",
        }

    fallback_text = monitor_template_text or expected_html
    if not fallback_text:
        return None

    return {
        "title": lookup_title,
        "text": fallback_text,
        "media_type": None,
        "media_id": None,
        "vault_chat_id": None,
        "vault_message_id": None,
        "source": "watch_template_fallback",
    }


def _read_manual_candidate_coverage_hours() -> Optional[float]:
    coverage_minutes_raw = os.getenv("WATCH_COVERAGE_MINUTES")
    if coverage_minutes_raw:
        try:
            return float(coverage_minutes_raw) / 60.0
        except Exception:
            pass

    coverage_hours_raw = os.getenv("WATCH_COVERAGE_HOURS")
    if coverage_hours_raw:
        try:
            return float(coverage_hours_raw)
        except Exception:
            pass

    return (23.0 * 60.0 + 59.0) / 60.0


def _resolve_group_watches(group_id: int) -> list[dict[str, Any]]:
    try:
        return watch_posts_db.fetch_watches_by_group(int(group_id))
    except Exception:
        log.exception("Failed to fetch watches for notifier group_id=%s", group_id)
        return []


def _resolve_group_titles_and_links(group_watches: list[dict[str, Any]]) -> tuple[dict[int, str], dict[int, str]]:
    channel_ids: list[int] = []
    for watch_row in group_watches:
        try:
            channel_identifier = int(watch_row.get("channel_id") or 0)
        except Exception:
            channel_identifier = 0
        if channel_identifier:
            channel_ids.append(channel_identifier)

    if not channel_ids:
        return {}, {}

    unique_channel_ids = list(dict.fromkeys(channel_ids))
    try:
        return (
            get_titles_by_channel_ids(unique_channel_ids) or {},
            get_links_by_channel_ids(unique_channel_ids) or {},
        )
    except Exception:
        log.exception("Failed to resolve titles/links for notifier channels=%s", unique_channel_ids)
        return {}, {}


def _watch_bot_preview_html(message_text: str, *, max_visible_chars: int = 80) -> str:
    try:
        from app.watch_bot.handlers.active_watches_group import _candidate_html_to_preview_html  # type: ignore

        return str(_candidate_html_to_preview_html(message_text, max_visible_chars=max_visible_chars) or "").strip()
    except Exception:
        preview_plain_text = str(message_text or "").strip()
        if len(preview_plain_text) > max_visible_chars:
            preview_plain_text = preview_plain_text[:max_visible_chars].rstrip() + "…"
        return html.escape(preview_plain_text)


def _watch_bot_message_html(message_text: str) -> str:
    try:
        from app.watch_bot.handlers.active_watches_group import _sanitize_bot_api_html_fragment  # type: ignore

        return str(_sanitize_bot_api_html_fragment(message_text) or "").strip()
    except Exception:
        return html.escape(str(message_text or "").strip())


def _watch_bot_collect_links(message_text: str) -> list[str]:
    try:
        from app.watch_bot.handlers.active_watches_group import _collect_links  # type: ignore

        return list(_collect_links(message_text) or [])
    except Exception:
        return []


def _build_notifier_candidates_list_markup(
    *,
    notification_page_session_identifier: str,
    current_page_number: int,
    candidate_ids: list[int],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, candidate_id in enumerate(candidate_ids, start=1):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Відкрити кандидат ({index})",
                    callback_data=(
                        f"{NOTIFICATION_MANAGE_CALLBACK_PREFIX}:{notification_page_session_identifier}:"
                        f"{int(current_page_number)}:cv:{int(candidate_id)}"
                    ),
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=(
                    f"{NOTIFICATION_MANAGE_CALLBACK_PREFIX}:{notification_page_session_identifier}:"
                    f"{int(current_page_number)}:back"
                ),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_notifier_candidate_detail_markup(
    *,
    notification_page_session_identifier: str,
    current_page_number: int,
    candidate_id: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Заметчити",
                    callback_data=(
                        f"{NOTIFICATION_MANAGE_CALLBACK_PREFIX}:{notification_page_session_identifier}:"
                        f"{int(current_page_number)}:ca:{int(candidate_id)}"
                    ),
                ),
                InlineKeyboardButton(
                    text="❌ Ні",
                    callback_data=(
                        f"{NOTIFICATION_MANAGE_CALLBACK_PREFIX}:{notification_page_session_identifier}:"
                        f"{int(current_page_number)}:cr:{int(candidate_id)}"
                    ),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=(
                        f"{NOTIFICATION_MANAGE_CALLBACK_PREFIX}:{notification_page_session_identifier}:"
                        f"{int(current_page_number)}:cl"
                    ),
                )
            ],
        ]
    )


def _build_notifier_candidates_list_view(
    *,
    group_id: int,
    notification_page_session_identifier: str,
    current_page_number: int,
) -> tuple[str, InlineKeyboardMarkup]:
    group_watches = _resolve_group_watches(group_id)
    watch_ids = [int(watch_row["id"]) for watch_row in group_watches if watch_row.get("id") is not None]
    if not watch_ids:
        return (
            "Кандидатів для цієї групи немає.",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад",
                            callback_data=(
                                f"{NOTIFICATION_MANAGE_CALLBACK_PREFIX}:{notification_page_session_identifier}:"
                                f"{int(current_page_number)}:back"
                            ),
                        )
                    ]
                ]
            ),
        )

    candidates = list_group_watch_candidates(watch_ids, status=CANDIDATE_PENDING_STATUS) or []
    if not candidates:
        return (
            "Кандидатів для цієї групи немає.",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад",
                            callback_data=(
                                f"{NOTIFICATION_MANAGE_CALLBACK_PREFIX}:{notification_page_session_identifier}:"
                                f"{int(current_page_number)}:back"
                            ),
                        )
                    ]
                ]
            ),
        )

    titles_map, links_map = _resolve_group_titles_and_links(group_watches)
    grouped_candidates: dict[str, dict[str, Any]] = {}
    for candidate_row in candidates:
        group_key = str(candidate_row.get("text_hash") or f"id:{candidate_row.get('id')}")
        candidate_bucket = grouped_candidates.setdefault(group_key, {"items": [], "repr": candidate_row})
        candidate_bucket["items"].append(candidate_row)

    lines: list[str] = ["Кандидати цієї групи:"]
    candidate_ids_for_buttons: list[int] = []
    candidate_index = 1
    for candidate_bucket in grouped_candidates.values():
        candidate_repr = candidate_bucket["repr"]
        candidate_id = int(candidate_repr["id"])
        candidate_ids_for_buttons.append(candidate_id)
        preview_html = _watch_bot_preview_html(str(candidate_repr.get("message_text") or ""), max_visible_chars=80)
        lines.append(f"Пост #{candidate_index}")
        if preview_html:
            lines.append(f"   Прев'ю: {preview_html}")
        lines.append("   Канали:")
        for channel_index, candidate_item in enumerate(candidate_bucket["items"], start=1):
            channel_id = int(candidate_item.get("channel_id") or 0)
            title = titles_map.get(channel_id, f"cid={channel_id}") if channel_id else "—"
            link = links_map.get(channel_id) if channel_id else None
            watch_id = candidate_item.get("watch_id")
            prefix = f"wid={watch_id}: " if watch_id else ""
            if link:
                lines.append(
                    f"      {channel_index}. {prefix}<a href=\"{html.escape(str(link))}\">{html.escape(str(title))}</a>"
                )
            else:
                lines.append(f"      {channel_index}. {prefix}{html.escape(str(title))}")
        candidate_index += 1

    return (
        "\n".join(lines),
        _build_notifier_candidates_list_markup(
            notification_page_session_identifier=notification_page_session_identifier,
            current_page_number=current_page_number,
            candidate_ids=candidate_ids_for_buttons,
        ),
    )


def _build_notifier_candidate_detail_view(
    *,
    group_id: int,
    candidate_id: int,
    notification_page_session_identifier: str,
    current_page_number: int,
) -> Optional[tuple[str, InlineKeyboardMarkup]]:
    group_watches = _resolve_group_watches(group_id)
    watch_ids = {int(watch_row["id"]) for watch_row in group_watches if watch_row.get("id") is not None}
    if not watch_ids:
        return None

    candidate = get_watch_candidate(int(candidate_id))
    if not candidate:
        return None
    watch_id = int(candidate.get("watch_id") or 0)
    if watch_id not in watch_ids:
        return None

    same_hash_candidates = (
        list_candidates_by_hash(str(candidate.get("text_hash") or ""), status=CANDIDATE_PENDING_STATUS)
        if candidate.get("text_hash")
        else [candidate]
    )
    same_hash_candidates = [item for item in same_hash_candidates if int(item.get("watch_id") or 0) in watch_ids] or [candidate]

    titles_map, links_map = _resolve_group_titles_and_links(group_watches)

    raw_message_text = str(candidate.get("message_text") or "")
    message_html = _watch_bot_message_html(raw_message_text) or "—"

    expected_links: list[str] = []
    try:
        expected_html = get_watch_expected_text(watch_id) if watch_id else None
        if expected_html:
            expected_links = _watch_bot_collect_links(str(expected_html))
        if not expected_links:
            expected_links = get_watch_expected_links(watch_id) if watch_id else []
    except Exception:
        expected_links = []
    candidate_links = _watch_bot_collect_links(raw_message_text)

    lines: list[str] = [
        f"<b>Кандидат #{int(candidate_id)}</b>",
        f"watch_id: {html.escape(str(watch_id or '—'))}",
        f"Схожість: {int((candidate.get('similarity') or 0) * 100)}%",
        f"Створено: {html.escape(str(candidate.get('created_at') or '—'))}",
        "",
        "<b>Пост:</b>",
        message_html,
        "",
        "<b>Канали:</b>",
    ]
    for same_hash_candidate in same_hash_candidates:
        channel_id = int(same_hash_candidate.get("channel_id") or 0)
        title = titles_map.get(channel_id, f"cid={channel_id}") if channel_id else "—"
        link = links_map.get(channel_id) if channel_id else None
        same_hash_watch_id = same_hash_candidate.get("watch_id")
        prefix = f"wid={same_hash_watch_id}: " if same_hash_watch_id else ""
        if link:
            lines.append(f"- {prefix}<a href=\"{html.escape(str(link))}\">{html.escape(str(title))}</a>")
        else:
            lines.append(f"- {prefix}{html.escape(str(title))}")

    lines.append("")
    lines.append("<b>Очікувані лінки:</b>")
    if expected_links:
        for link_value in expected_links:
            link_safe = html.escape(str(link_value))
            lines.append(f"- <a href=\"{link_safe}\">{link_safe}</a>")
    else:
        lines.append("- немає")

    lines.append("<b>Лінки кандидата:</b>")
    if candidate_links:
        for link_value in candidate_links:
            link_safe = html.escape(str(link_value))
            lines.append(f"- <a href=\"{link_safe}\">{link_safe}</a>")
    else:
        lines.append("- немає")

    return (
        "\n".join(lines),
        _build_notifier_candidate_detail_markup(
            notification_page_session_identifier=notification_page_session_identifier,
            current_page_number=current_page_number,
            candidate_id=int(candidate_id),
        ),
    )


def _reject_candidate_group(candidate_id: int) -> bool:
    candidate = get_watch_candidate(int(candidate_id))
    if not candidate:
        return False

    text_hash = str(candidate.get("text_hash") or "")
    rejected_any = False
    if text_hash:
        for candidate_row in list_candidates_by_hash(text_hash, status=CANDIDATE_PENDING_STATUS):
            set_watch_candidate_status(int(candidate_row["id"]), "rejected")
            rejected_any = True
        return rejected_any

    return set_watch_candidate_status(int(candidate_id), "rejected")


async def inline_handler(inline_query: InlineQuery) -> None:
    query = inline_query.query.strip()
    if not query:
        title = "Статусы вотчей"
        message = "Скоро тут будуть швидкі команди для статусів."
    else:
        title = f"Запит: {query}"
        message = f"Ви надіслали: {query}\n(інлайн-режим тестовий)"

    result = InlineQueryResultArticle(
        id="status_1",
        title=title,
        input_message_content=InputTextMessageContent(message_text=message),
        description="Тестова відповідь нотіфікатора",
    )
    await inline_query.answer([result], cache_time=1, is_personal=True)


def discard_notification_page_session(notification_page_session_identifier: str) -> None:
    delete_notification_page_session_records(notification_page_session_identifier)


def create_notification_page_session(notification_page_texts: List[str]) -> str:
    for _ in range(3):
        notification_page_session_identifier = uuid.uuid4().hex
        try:
            create_notification_page_session_records(
                notification_page_session_identifier,
                notification_page_texts,
            )
            return notification_page_session_identifier
        except IntegrityError:
            continue
    raise RuntimeError("Failed to create unique notification page session identifier")


def attach_notification_page_session_to_message(
    chat_id: int,
    message_id: int,
    notification_page_session_identifier: str,
) -> None:
    delete_notification_page_records_for_message(chat_id, message_id)
    bind_notification_page_session_to_message(
        notification_page_session_identifier,
        chat_id,
        message_id,
    )


def _bootstrap_notification_page_session_from_message(
    notification_page_session_identifier: str,
    message,
) -> int:
    if message is None:
        return 0

    existing_total_page_count = count_notification_pages_for_session(notification_page_session_identifier)
    if existing_total_page_count > 0:
        try:
            bind_notification_page_session_to_message(
                notification_page_session_identifier,
                int(message.chat.id),
                int(message.message_id),
            )
        except Exception:
            log.exception(
                "Failed to rebind legacy notifier session=%s to chat_id=%s message_id=%s",
                notification_page_session_identifier,
                getattr(getattr(message, "chat", None), "id", None),
                getattr(message, "message_id", None),
            )
        return existing_total_page_count

    page_text = str(
        getattr(message, "html_text", None)
        or getattr(message, "caption_html", None)
        or getattr(message, "text", None)
        or getattr(message, "caption", None)
        or ""
    ).strip()
    if not page_text:
        return 0

    try:
        create_notification_page_session_records(
            notification_page_session_identifier,
            [page_text],
        )
    except IntegrityError:
        pass
    except Exception:
        log.exception(
            "Failed to bootstrap legacy notifier session=%s from message chat_id=%s message_id=%s",
            notification_page_session_identifier,
            int(message.chat.id),
            int(message.message_id),
        )
        return 0

    try:
        bind_notification_page_session_to_message(
            notification_page_session_identifier,
            int(message.chat.id),
            int(message.message_id),
        )
    except Exception:
        log.exception(
            "Failed to bind bootstrapped notifier session=%s to chat_id=%s message_id=%s",
            notification_page_session_identifier,
            int(message.chat.id),
            int(message.message_id),
        )
        return 0

    rebound_total_page_count = count_notification_pages_for_message_session(
        notification_page_session_identifier,
        int(message.chat.id),
        int(message.message_id),
    )
    return rebound_total_page_count or 0


def _message_has_media(message) -> bool:
    content_type = str(getattr(message, "content_type", "") or "").strip().lower()
    if content_type in {"photo", "video", "animation", "document"}:
        return True
    return bool(
        getattr(message, "photo", None)
        or getattr(message, "video", None)
        or getattr(message, "animation", None)
        or getattr(message, "document", None)
    )


def _resolve_session_total_pages(
    notification_page_session_identifier: str,
    chat_id: int,
    message_id: int,
) -> int:
    total_page_count = count_notification_pages_for_message_session(
        notification_page_session_identifier,
        chat_id,
        message_id,
    )
    if total_page_count > 0:
        return total_page_count

    fallback_total_page_count = count_notification_pages_for_session(
        notification_page_session_identifier
    )
    if fallback_total_page_count <= 0:
        return 0

    # Rebind session to current message so navigation/back keeps working.
    try:
        bind_notification_page_session_to_message(
            notification_page_session_identifier,
            chat_id,
            message_id,
        )
    except Exception:
        log.exception(
            "Failed to rebind notification page session=%s to chat_id=%s message_id=%s",
            notification_page_session_identifier,
            chat_id,
            message_id,
        )
        return fallback_total_page_count

    rebound_total_page_count = count_notification_pages_for_message_session(
        notification_page_session_identifier,
        chat_id,
        message_id,
    )
    return rebound_total_page_count if rebound_total_page_count > 0 else fallback_total_page_count


def _resolve_page_text(
    notification_page_session_identifier: str,
    chat_id: int,
    message_id: int,
    page_number: int,
) -> Optional[str]:
    target_page_text = get_notification_page_text_for_message(
        notification_page_session_identifier,
        chat_id,
        message_id,
        page_number,
    )
    if target_page_text is not None:
        return target_page_text
    return get_notification_page_text_for_session(
        notification_page_session_identifier,
        page_number,
    )


def remove_notification_page_session_for_message(chat_id: int, message_id: int) -> None:
    delete_notification_page_records_for_message(chat_id, message_id)


def build_notification_navigation_markup(
    notification_page_session_identifier: str,
    current_page_number: int,
    total_page_count: int,
) -> InlineKeyboardMarkup | None:
    if total_page_count <= 0:
        return None

    rows: List[List[InlineKeyboardButton]] = []
    navigation_buttons: List[InlineKeyboardButton] = []

    if current_page_number > 0:
        previous_page_number = current_page_number - 1
        navigation_buttons.append(
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=(
                    f"{NOTIFICATION_PAGE_CALLBACK_PREFIX}:{notification_page_session_identifier}:{previous_page_number}"
                ),
            )
        )

    navigation_buttons.append(
        InlineKeyboardButton(
            text=f"{current_page_number + 1}/{total_page_count}",
            callback_data=NOTIFICATION_PAGE_NOOP_CALLBACK_DATA,
        )
    )

    if current_page_number < total_page_count - 1:
        next_page_number = current_page_number + 1
        navigation_buttons.append(
            InlineKeyboardButton(
                text="Вперед ➡️",
                callback_data=(
                    f"{NOTIFICATION_PAGE_CALLBACK_PREFIX}:{notification_page_session_identifier}:{next_page_number}"
                ),
            )
        )

    if navigation_buttons:
        rows.append(navigation_buttons)

    rows.append(
        [
            InlineKeyboardButton(
                text="⚙️ Управление постом",
                callback_data=(
                    f"{NOTIFICATION_MANAGE_CALLBACK_PREFIX}:{notification_page_session_identifier}:"
                    f"{int(current_page_number)}:open"
                ),
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_management_menu_markup(
    notification_page_session_identifier: str,
    current_page_number: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑️ Удалить вотч",
                    callback_data=(
                        f"{NOTIFICATION_MANAGE_CALLBACK_PREFIX}:{notification_page_session_identifier}:"
                        f"{int(current_page_number)}:dl"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔍 Кандидаты",
                    callback_data=(
                        f"{NOTIFICATION_MANAGE_CALLBACK_PREFIX}:{notification_page_session_identifier}:"
                        f"{int(current_page_number)}:cl"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Посмотреть пост",
                    callback_data=(
                        f"{NOTIFICATION_MANAGE_CALLBACK_PREFIX}:{notification_page_session_identifier}:"
                        f"{int(current_page_number)}:view"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=(
                        f"{NOTIFICATION_MANAGE_CALLBACK_PREFIX}:{notification_page_session_identifier}:"
                        f"{int(current_page_number)}:back"
                    ),
                )
            ],
        ]
    )


def _build_template_view_back_markup(
    notification_page_session_identifier: str,
    current_page_number: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=f"{NOTIFICATION_PREVIEW_CALLBACK_PREFIX}:close",
                )
            ]
        ]
    )


async def _replace_message_with_content(
    callback_query: CallbackQuery,
    *,
    context: Optional[dict[str, Any]],
    notification_page_session_identifier: str,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup],
    media_type: Optional[str] = None,
    media_id: Optional[str] = None,
    vault_chat_id: Optional[int] = None,
    vault_message_id: Optional[int] = None,
) -> None:
    message = callback_query.message
    if message is None:
        return

    chat_id = int(message.chat.id)
    old_message_id = int(message.message_id)
    bot = callback_query.bot

    normalized_media_type = str(media_type or "").strip().lower()
    normalized_media_id = str(media_id or "").strip()
    normalized_vault_chat_id = _to_int_or_none(vault_chat_id)
    normalized_vault_message_id = _to_int_or_none(vault_message_id)

    sent_message = None
    if normalized_media_type and normalized_media_id:
        try:
            if normalized_media_type == "photo":
                sent_message = await bot.send_photo(
                    chat_id=chat_id,
                    photo=normalized_media_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            elif normalized_media_type == "video":
                sent_message = await bot.send_video(
                    chat_id=chat_id,
                    video=normalized_media_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            elif normalized_media_type == "animation":
                sent_message = await bot.send_animation(
                    chat_id=chat_id,
                    animation=normalized_media_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
        except TelegramBadRequest as exception:
            # file_id is often invalid for another bot/session. Fallback to text to keep UX working.
            if _is_media_unavailable_error(exception):
                log.warning(
                    "notifier template media unavailable; fallback to text. chat_id=%s media_type=%s error=%s",
                    chat_id,
                    normalized_media_type,
                    exception,
                )
                sent_message = None
            else:
                raise

    if sent_message is None and normalized_vault_chat_id and normalized_vault_message_id:
        try:
            sent_message = await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=normalized_vault_chat_id,
                message_id=normalized_vault_message_id,
                reply_markup=reply_markup,
            )
        except TelegramBadRequest as exception:
            log.warning(
                "notifier template media vault copy failed; fallback to text. chat_id=%s vault=%s:%s error=%s",
                chat_id,
                normalized_vault_chat_id,
                normalized_vault_message_id,
                exception,
            )
            sent_message = None

    # Keep markup/text consistent if copy_message was used.
    if (
        sent_message is not None
        and normalized_vault_chat_id
        and normalized_vault_message_id
        and text
    ):
        try:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=int(sent_message.message_id),
                caption=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        except TelegramBadRequest:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=int(sent_message.message_id),
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=reply_markup,
                )
            except TelegramBadRequest:
                pass

    if sent_message is None:
        sent_message = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )

    attach_notification_page_session_to_message(
        chat_id=chat_id,
        message_id=int(sent_message.message_id),
        notification_page_session_identifier=notification_page_session_identifier,
    )
    _update_notifier_message_binding(context=context, new_message_id=int(sent_message.message_id))

    try:
        await bot.delete_message(chat_id=chat_id, message_id=old_message_id)
    except Exception:
        pass


async def _send_template_preview_reply(
    *,
    callback_query: CallbackQuery,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup],
    media_type: Optional[str] = None,
    media_id: Optional[str] = None,
    vault_chat_id: Optional[int] = None,
    vault_message_id: Optional[int] = None,
) -> None:
    message = callback_query.message
    if message is None:
        return

    chat_id = int(message.chat.id)
    reply_to_message_id = int(message.message_id)
    bot = callback_query.bot

    normalized_media_type = str(media_type or "").strip().lower()
    normalized_media_id = str(media_id or "").strip()
    normalized_vault_chat_id = _to_int_or_none(vault_chat_id)
    normalized_vault_message_id = _to_int_or_none(vault_message_id)

    sent_message = None
    if normalized_media_type and normalized_media_id:
        try:
            if normalized_media_type == "photo":
                sent_message = await bot.send_photo(
                    chat_id=chat_id,
                    photo=normalized_media_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    reply_to_message_id=reply_to_message_id,
                )
            elif normalized_media_type == "video":
                sent_message = await bot.send_video(
                    chat_id=chat_id,
                    video=normalized_media_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    reply_to_message_id=reply_to_message_id,
                )
            elif normalized_media_type == "animation":
                sent_message = await bot.send_animation(
                    chat_id=chat_id,
                    animation=normalized_media_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    reply_to_message_id=reply_to_message_id,
                )
        except TelegramBadRequest as exception:
            if _is_media_unavailable_error(exception):
                log.warning(
                    "notifier preview media unavailable; fallback. chat_id=%s media_type=%s error=%s",
                    chat_id,
                    normalized_media_type,
                    exception,
                )
                sent_message = None
            else:
                raise

    if sent_message is None and normalized_vault_chat_id and normalized_vault_message_id:
        try:
            sent_message = await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=normalized_vault_chat_id,
                message_id=normalized_vault_message_id,
                reply_markup=reply_markup,
                reply_to_message_id=reply_to_message_id,
            )
        except TelegramBadRequest as exception:
            log.warning(
                "notifier preview media vault copy failed; fallback to text. chat_id=%s vault=%s:%s error=%s",
                chat_id,
                normalized_vault_chat_id,
                normalized_vault_message_id,
                exception,
            )
            sent_message = None

    if (
        sent_message is not None
        and normalized_vault_chat_id
        and normalized_vault_message_id
        and text
    ):
        try:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=int(sent_message.message_id),
                caption=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        except TelegramBadRequest:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=int(sent_message.message_id),
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=reply_markup,
                )
            except TelegramBadRequest:
                pass

    if sent_message is None:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
        )


async def _safe_edit_html_message(
    message,
    *,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup],
) -> None:
    try:
        await message.edit_text(
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as exception:
        if "message is not modified" in str(exception).lower():
            return
        raise


async def _restore_notification_page(
    callback_query: CallbackQuery,
    *,
    notification_page_session_identifier: str,
    target_page_number: int,
    answer_text: Optional[str] = None,
) -> None:
    message = callback_query.message
    if message is None:
        await callback_query.answer()
        return

    chat_id = int(message.chat.id)
    message_id = int(message.message_id)

    total_page_count = _resolve_session_total_pages(
        notification_page_session_identifier,
        chat_id,
        message_id,
    )
    if total_page_count <= 0:
        total_page_count = _bootstrap_notification_page_session_from_message(
            notification_page_session_identifier,
            message,
        )
    if total_page_count <= 0:
        await callback_query.answer("Сторінки вже недоступні")
        return

    clamped_page_number = min(max(0, int(target_page_number)), total_page_count - 1)
    target_page_text = _resolve_page_text(
        notification_page_session_identifier,
        chat_id,
        message_id,
        clamped_page_number,
    )
    if target_page_text is None:
        await callback_query.answer("Сторінки вже недоступні")
        return

    navigation_markup = build_notification_navigation_markup(
        notification_page_session_identifier,
        clamped_page_number,
        total_page_count,
    )

    # Telegram cannot always convert media message back to text via edit_text.
    if _message_has_media(message):
        context = _resolve_notifier_context(chat_id=chat_id, message_id=message_id)
        await _replace_message_with_content(
            callback_query,
            context=context,
            notification_page_session_identifier=notification_page_session_identifier,
            text=target_page_text,
            reply_markup=navigation_markup,
            media_type=None,
            media_id=None,
        )
        await callback_query.answer(answer_text or f"{clamped_page_number + 1}/{total_page_count}")
        return

    try:
        await _safe_edit_html_message(
            message,
            text=target_page_text,
            reply_markup=navigation_markup,
        )
    except TelegramBadRequest as exception:
        normalized_error_text = str(exception).lower()
        if "message is not modified" in normalized_error_text:
            await callback_query.answer(answer_text or f"{clamped_page_number + 1}/{total_page_count}")
            return

        context = _resolve_notifier_context(chat_id=chat_id, message_id=message_id)
        await _replace_message_with_content(
            callback_query,
            context=context,
            notification_page_session_identifier=notification_page_session_identifier,
            text=target_page_text,
            reply_markup=navigation_markup,
            media_type=None,
            media_id=None,
        )

    await callback_query.answer(answer_text or f"{clamped_page_number + 1}/{total_page_count}")


async def notification_page_navigation_handler(callback_query: CallbackQuery) -> None:
    callback_data = callback_query.data or ""
    callback_parts = callback_data.split(":", 2)
    if len(callback_parts) != 3:
        await callback_query.answer()
        return

    _, notification_page_session_identifier, requested_page_number_raw = callback_parts

    try:
        requested_page_number = int(requested_page_number_raw)
    except ValueError:
        await callback_query.answer()
        return

    await _restore_notification_page(
        callback_query,
        notification_page_session_identifier=notification_page_session_identifier,
        target_page_number=requested_page_number,
    )


async def notification_page_noop_handler(callback_query: CallbackQuery) -> None:
    await callback_query.answer()


async def notification_manage_handler(callback_query: CallbackQuery) -> None:
    callback_data = callback_query.data or ""
    callback_parts = callback_data.split(":", 3)
    if len(callback_parts) != 4:
        await callback_query.answer()
        return

    _, notification_page_session_identifier, current_page_number_raw, action = callback_parts

    message = callback_query.message
    if message is None:
        await callback_query.answer()
        return

    chat_id = int(message.chat.id)
    message_id = int(message.message_id)

    total_page_count = _resolve_session_total_pages(
        notification_page_session_identifier,
        chat_id,
        message_id,
    )
    if total_page_count <= 0:
        total_page_count = _bootstrap_notification_page_session_from_message(
            notification_page_session_identifier,
            message,
        )
    if total_page_count <= 0:
        await callback_query.answer("Сторінки вже недоступні")
        return

    try:
        current_page_number = int(current_page_number_raw)
    except Exception:
        current_page_number = 0
    current_page_number = min(max(0, current_page_number), total_page_count - 1)

    if action == "first":
        action = "dl"
    elif action == "second":
        action = "cl"

    if action == "open":
        await message.edit_reply_markup(
            reply_markup=_build_management_menu_markup(
                notification_page_session_identifier=notification_page_session_identifier,
                current_page_number=current_page_number,
            )
        )
        await callback_query.answer()
        return

    if action == "back":
        await _restore_notification_page(
            callback_query,
            notification_page_session_identifier=notification_page_session_identifier,
            target_page_number=current_page_number,
        )
        return

    context = None
    if action in {"view", "dl", "cl"} or action.startswith(("cv:", "ca:", "cr:")):
        context = _resolve_notifier_context(chat_id=chat_id, message_id=message_id)
        if not context:
            await callback_query.answer("Контекст уведомления не найден")
            return

    if action == "dl":
        group_watches = _resolve_group_watches(int(context["group_id"]))
        leader_watch_id = int(group_watches[0]["id"]) if group_watches else 0
        if not leader_watch_id:
            await callback_query.answer("Вотчі групи не знайдено", show_alert=True)
            return

        try:
            cancelled = cancel_group_watches(leader_watch_id)
        except Exception:
            log.exception("Failed to cancel notifier watches group_id=%s leader_wid=%s", context["group_id"], leader_watch_id)
            cancelled = False

        if not cancelled:
            await callback_query.answer("Не вдалося скасувати вотчі", show_alert=True)
            return

        await _restore_notification_page(
            callback_query,
            notification_page_session_identifier=notification_page_session_identifier,
            target_page_number=current_page_number,
            answer_text="Вотчі скасовано",
        )
        return

    if action == "cl":
        candidates_text, candidates_markup = _build_notifier_candidates_list_view(
            group_id=int(context["group_id"]),
            notification_page_session_identifier=notification_page_session_identifier,
            current_page_number=current_page_number,
        )
        await _safe_edit_html_message(
            message,
            text=candidates_text,
            reply_markup=candidates_markup,
        )
        await callback_query.answer()
        return

    if action.startswith("cv:"):
        candidate_id_raw = action.split(":", 1)[1] if ":" in action else ""
        candidate_id = _to_int_or_none(candidate_id_raw)
        if not candidate_id:
            await callback_query.answer("Кандидат не знайдений", show_alert=True)
            return

        candidate_detail = _build_notifier_candidate_detail_view(
            group_id=int(context["group_id"]),
            candidate_id=int(candidate_id),
            notification_page_session_identifier=notification_page_session_identifier,
            current_page_number=current_page_number,
        )
        if not candidate_detail:
            await callback_query.answer("Кандидат не знайдений", show_alert=True)
            return

        candidate_text, candidate_markup = candidate_detail
        await _safe_edit_html_message(
            message,
            text=candidate_text,
            reply_markup=candidate_markup,
        )
        await callback_query.answer()
        return

    if action.startswith("ca:"):
        candidate_id_raw = action.split(":", 1)[1] if ":" in action else ""
        candidate_id = _to_int_or_none(candidate_id_raw)
        if not candidate_id:
            await callback_query.answer("Кандидат не знайдений", show_alert=True)
            return

        matched = accept_watch_candidate(
            int(candidate_id),
            coverage_hours=_read_manual_candidate_coverage_hours(),
        )
        if not matched:
            await callback_query.answer("Не вдалося заметчити", show_alert=True)
            return

        candidates_text, candidates_markup = _build_notifier_candidates_list_view(
            group_id=int(context["group_id"]),
            notification_page_session_identifier=notification_page_session_identifier,
            current_page_number=current_page_number,
        )
        await _safe_edit_html_message(
            message,
            text=candidates_text,
            reply_markup=candidates_markup,
        )
        await callback_query.answer("Кандидат заметчено")
        return

    if action.startswith("cr:"):
        candidate_id_raw = action.split(":", 1)[1] if ":" in action else ""
        candidate_id = _to_int_or_none(candidate_id_raw)
        if not candidate_id:
            await callback_query.answer("Кандидат не знайдений", show_alert=True)
            return

        rejected = _reject_candidate_group(int(candidate_id))
        if not rejected:
            await callback_query.answer("Нема що відхиляти", show_alert=True)
            return

        candidates_text, candidates_markup = _build_notifier_candidates_list_view(
            group_id=int(context["group_id"]),
            notification_page_session_identifier=notification_page_session_identifier,
            current_page_number=current_page_number,
        )
        await _safe_edit_html_message(
            message,
            text=candidates_text,
            reply_markup=candidates_markup,
        )
        await callback_query.answer("Кандидат відхилено")
        return

    if action != "view":
        await callback_query.answer()
        return

    template_payload = _resolve_template_payload_for_group(int(context["group_id"]))
    if not template_payload:
        await callback_query.answer("Шаблон не найден")
        return

    post_text = str(template_payload.get("text") or "").strip() or "Шаблон пустой"
    template_view_markup = _build_template_view_back_markup(
        notification_page_session_identifier=notification_page_session_identifier,
        current_page_number=current_page_number,
    )

    media_type = str(template_payload.get("media_type") or "").strip().lower() or None
    media_id = str(template_payload.get("media_id") or "").strip() or None
    vault_chat_id = _to_int_or_none(template_payload.get("vault_chat_id"))
    vault_message_id = _to_int_or_none(template_payload.get("vault_message_id"))

    await _send_template_preview_reply(
        callback_query=callback_query,
        text=post_text,
        reply_markup=template_view_markup,
        media_type=media_type,
        media_id=media_id,
        vault_chat_id=vault_chat_id,
        vault_message_id=vault_message_id,
    )

    await callback_query.answer()


async def notification_preview_handler(callback_query: CallbackQuery) -> None:
    callback_data = callback_query.data or ""
    callback_parts = callback_data.split(":", 1)
    if len(callback_parts) != 2:
        await callback_query.answer()
        return

    _, action = callback_parts
    message = callback_query.message
    if message is None:
        await callback_query.answer()
        return

    if action != "close":
        await callback_query.answer()
        return

    try:
        await callback_query.bot.delete_message(
            chat_id=int(message.chat.id),
            message_id=int(message.message_id),
        )
    except Exception:
        # Preview may already be deleted or not editable/deletable anymore.
        pass
    await callback_query.answer()
