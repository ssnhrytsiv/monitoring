from __future__ import annotations

import html as html_mod
import json
import logging
import re
import hashlib
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy import case, func

from app.DAL import channels_operations as cho
from app.DAL import post_templates_operations as post_watch_db
from app.DAL import watch_posts_operations as watch_posts_db
from app.DAL import watch_events_operations as watch_events_db
from app.admin_bot.db import models as adm_models
from app.admin_bot.db.session import SessionLocal as AdminSession
from app.utils.link_parser import sanitize_link
from app.watch_bot.services.channels_repo import get_links_by_channel_ids, get_titles_by_channel_ids
from app.utils.watch_link_extractor import (
    extract_links_from_text_for_watch,
    normalize_links_for_watch,
)

log = logging.getLogger("watch_network_batch")


@dataclass
class WatchBatchCreateCommand:
    network_id: int
    project: Optional[str] = None
    admin_id: Optional[int] = None
    time_window_start: Optional[str] = None
    time_window_end: Optional[str] = None
    template_id: Optional[int] = None
    expected_html: Optional[str] = None
    expected_links_json: Optional[str] = None
    preferred_title: Optional[str] = None
    created_by: Optional[int] = None
    created_via: Optional[str] = None


@dataclass
class WatchCreatedItem:
    channel_id: int
    watch_id: int
    link: str
    title: str

    def to_dict(self) -> dict:
        return {
            "channel_id": int(self.channel_id),
            "watch_id": int(self.watch_id),
            "link": str(self.link or ""),
            "title": str(self.title or ""),
        }


@dataclass
class WatchFailedItem:
    channel_id: Optional[int]
    target: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "channel_id": int(self.channel_id) if self.channel_id else None,
            "target": str(self.target or ""),
            "reason": str(self.reason or ""),
        }


@dataclass
class WatchBatchCreateResult:
    status: str
    network_id: int
    admin_id: Optional[int] = None
    project: Optional[str] = None
    group_id: Optional[int] = None
    trace_id: Optional[str] = None
    created: list[WatchCreatedItem] = field(default_factory=list)
    skipped: list[WatchFailedItem] = field(default_factory=list)
    failed: list[WatchFailedItem] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def created_count(self) -> int:
        return len(self.created)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def failed_count(self) -> int:
        return len(self.failed)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "network_id": int(self.network_id),
            "admin_id": int(self.admin_id) if self.admin_id else None,
            "project": self.project,
            "group_id": int(self.group_id) if self.group_id else None,
            "trace_id": self.trace_id,
            "created_count": self.created_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "created": [item.to_dict() for item in self.created],
            "skipped": [item.to_dict() for item in self.skipped],
            "failed": [item.to_dict() for item in self.failed],
            "error": self.error,
        }


def _safe_int(value) -> Optional[int]:
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _build_trace_id(command: WatchBatchCreateCommand, expected_html: str) -> str:
    seed = "|".join(
        [
            str(command.created_via or ""),
            str(command.network_id or ""),
            str(command.time_window_end or ""),
            str(command.template_id or ""),
            str(command.project or ""),
            str(command.admin_id or ""),
            str(expected_html or "")[:180],
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return digest[:16]


def _safe_emit_watch_event(watch_id: int, event_type: str, payload: dict) -> None:
    try:
        watch_events_db.insert_watch_event(
            int(watch_id),
            str(event_type),
            json.dumps(payload, ensure_ascii=False),
        )
    except Exception:
        log.warning("watch batch: failed to insert watch_event wid=%s type=%s", watch_id, event_type, exc_info=True)


def _first_line_title(text: str) -> str:
    raw_text = str(text or "").strip()
    if not raw_text:
        return ""
    raw_text = re.sub(r"^\W+", "", raw_text, flags=re.UNICODE)
    words = re.findall(r"[\w’'\-]+", raw_text, flags=re.UNICODE)
    words = [word for word in words if re.search(r"\w", word, flags=re.UNICODE)]
    if not words:
        return raw_text[:80]
    return " ".join(words[:2])[:80]


def _fallback_normalize_html_full(html_text: str) -> str:
    if not html_text:
        return ""
    value = str(html_text or "").replace("\r\n", "\n")
    value = html_mod.unescape(value)
    value = re.sub(r"<\s*br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"</\s*p\s*>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<\s*p\s*>", "", value, flags=re.IGNORECASE)
    value = re.sub(r"[\u200b\u200c\u200d\uFEFF\uFE0F]", "", value)
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _fallback_strip_tags_to_text(html_text: str) -> str:
    try:
        plain = re.sub(r"<[^>]+>", " ", str(html_text or ""))
        plain = html_mod.unescape(plain)
        return re.sub(r"\s+", " ", plain).strip()
    except Exception:
        return str(html_text or "")


def _resolve_expected_payload(command: WatchBatchCreateCommand) -> tuple[Optional[dict], Optional[str]]:
    template_id = _safe_int(command.template_id)
    expected_html = str(command.expected_html or "").strip()
    expected_links_json = command.expected_links_json
    template_title = str(command.preferred_title or "").strip()
    is_reply = False

    if template_id:
        template_row = post_watch_db.get_template_by_id(int(template_id))
        if not template_row:
            return None, f"template_not_found:{template_id}"
        _, template_html, _, _, _, row_title, row_links_json, _row_photo_id = template_row
        is_reply = bool(post_watch_db.is_template_reply(int(template_id)))
        if not expected_html:
            expected_html = str(template_html or "").strip()
        if expected_links_json is None:
            expected_links_json = row_links_json
        if not template_title:
            template_title = str(row_title or "").strip()

    if not expected_html:
        return None, "expected_html_empty"

    normalize_html = _fallback_normalize_html_full
    strip_tags = _fallback_strip_tags_to_text
    try:
        from app.plugins.posts_watch_listener import _normalize_html_full, _strip_tags_to_text

        normalize_html = _normalize_html_full
        strip_tags = _strip_tags_to_text
    except Exception:
        pass

    expected_html_normalized = normalize_html(expected_html)
    expected_plain_text = strip_tags(expected_html_normalized)
    expected_plain_len = len(expected_plain_text or "")

    normalized_expected_links: list[str] | None = None
    if expected_links_json is not None:
        parsed_links: list[str] = []
        parsed_links_payload_is_valid = False
        try:
            payload_links = json.loads(expected_links_json)
            if isinstance(payload_links, list):
                parsed_links = [str(value or "") for value in payload_links if str(value or "").strip()]
                parsed_links_payload_is_valid = True
        except Exception:
            parsed_links_payload_is_valid = False
        if parsed_links_payload_is_valid:
            normalized_expected_links = normalize_links_for_watch(parsed_links)

    if normalized_expected_links is None:
        normalized_expected_links = extract_links_from_text_for_watch(expected_html_normalized)

    expected_links_json = (
        json.dumps(normalized_expected_links, ensure_ascii=False)
        if normalized_expected_links
        else None
    )

    if not template_id:
        try:
            existing_template = post_watch_db.find_template_exact(
                text=expected_html_normalized,
                links=expected_links_json,
            )
            if existing_template:
                template_id = int(existing_template[0])
                if not template_title:
                    template_title = str(existing_template[5] or "").strip()
            else:
                resolved_title = template_title or _first_line_title(expected_plain_text or expected_html_normalized)
                template_id = int(
                    post_watch_db.add_template(
                        text=expected_html_normalized,
                        mode="exact",
                        threshold=1.0,
                        title=resolved_title or None,
                        links=expected_links_json,
                        is_reply=False,
                    )
                )
                if not template_title:
                    template_title = resolved_title
        except Exception as error:
            return None, f"template_resolve_failed:{error}"

    return {
        "template_id": template_id,
        "expected_html": expected_html_normalized,
        "expected_links_json": expected_links_json,
        "expected_plain_text": expected_plain_text,
        "expected_plain_len": expected_plain_len,
        "template_title": template_title or None,
        "is_reply": bool(is_reply),
    }, None


def _load_network_channels(network_id: int) -> tuple[Optional[int], str, list[dict]]:
    db = AdminSession()
    try:
        network_row = (
            db.query(adm_models.Network.id, adm_models.Network.admin_id, adm_models.Network.name)
            .filter(adm_models.Network.id == int(network_id))
            .first()
        )
        if not network_row:
            return None, "", []

        channel_rows = (
            db.query(
                adm_models.Channel.channel_id.label("channel_id"),
                adm_models.Channel.title.label("title"),
                adm_models.Channel.username.label("username"),
            )
            .join(
                adm_models.NetworkChannel,
                adm_models.NetworkChannel.channel_id == adm_models.Channel.channel_id,
            )
            .filter(adm_models.NetworkChannel.network_id == int(network_id))
            .order_by(
                case((adm_models.NetworkChannel.sort_order.is_(None), 1), else_=0),
                adm_models.NetworkChannel.sort_order.asc(),
                func.lower(func.coalesce(adm_models.Channel.title, "")),
                adm_models.Channel.channel_id.asc(),
            )
            .all()
        )

        channels: list[dict] = []
        seen_cids: set[int] = set()
        for row in channel_rows:
            channel_id = _safe_int(row.channel_id)
            if not channel_id or channel_id in seen_cids:
                continue
            seen_cids.add(channel_id)
            username = str(row.username or "").strip()
            title = str(row.title or "").strip()
            target = f"@{username.lstrip('@')}" if username else str(channel_id)
            channels.append(
                {
                    "channel_id": channel_id,
                    "username": username,
                    "title": title,
                    "target": target,
                }
            )

        network_admin_id = _safe_int(network_row.admin_id)
        network_name = str(network_row.name or "").strip() or f"Network {int(network_id)}"
        return network_admin_id, network_name, channels
    finally:
        db.close()


def _enrich_links_map_for_channels(channel_ids: list[int], base_links_map: dict[int, str]) -> dict[int, str]:
    if not channel_ids:
        return {}

    links_map: dict[int, str] = {}
    for cid, link_value in (base_links_map or {}).items():
        channel_id = _safe_int(cid)
        link_text = str(link_value or "").strip()
        if not channel_id or not link_text:
            continue
        links_map[channel_id] = link_text

    try:
        extra_links_map = cho.get_links_by_channel_ids(channel_ids)
        for cid, link_value in (extra_links_map or {}).items():
            channel_id = _safe_int(cid)
            link_text = str(link_value or "").strip()
            if not channel_id or not link_text or channel_id in links_map:
                continue
            links_map[channel_id] = link_text
    except Exception:
        log.warning("watch batch links enrich: failed to load links via channels_operations", exc_info=True)

    missing_channel_ids = [cid for cid in channel_ids if cid not in links_map]
    if not missing_channel_ids:
        return links_map

    db = AdminSession()
    try:
        channel_link_rows = (
            db.query(adm_models.ChannelLink.channel_id, adm_models.ChannelLink.link_url_norm)
            .filter(adm_models.ChannelLink.channel_id.in_(missing_channel_ids))
            .all()
        )
        for channel_id_value, link_url_norm in channel_link_rows:
            channel_id = _safe_int(channel_id_value)
            link_text = str(link_url_norm or "").strip()
            if not channel_id or not link_text or channel_id in links_map:
                continue
            links_map[channel_id] = link_text

        missing_channel_ids = [cid for cid in missing_channel_ids if cid not in links_map]
        if missing_channel_ids:
            raw_link_rows = (
                db.query(adm_models.Link.channel_id, adm_models.Link.raw_url)
                .filter(
                    adm_models.Link.channel_id.in_(missing_channel_ids),
                    adm_models.Link.raw_url.isnot(None),
                )
                .order_by(adm_models.Link.id.desc())
                .all()
            )
            for channel_id_value, raw_url in raw_link_rows:
                channel_id = _safe_int(channel_id_value)
                if not channel_id or channel_id in links_map or not raw_url:
                    continue
                try:
                    resolved_link = sanitize_link(raw_url) or raw_url
                except Exception:
                    resolved_link = raw_url
                resolved_link_text = str(resolved_link or "").strip()
                if resolved_link_text:
                    links_map[channel_id] = resolved_link_text
    except Exception:
        log.warning("watch batch links enrich: failed to load links via channel_links/raw links", exc_info=True)
    finally:
        db.close()

    return links_map


def _resolve_similarity_title(expected_plain_text: str) -> Optional[str]:
    if not expected_plain_text:
        return None
    try:
        templates = post_watch_db.list_templates_full(limit=200)
        best_ratio = 0.0
        best_title: Optional[str] = None
        for tpl_id, tpl_text, tpl_mode, tpl_threshold, tpl_created_at, tpl_title, tpl_links, _tpl_photo_id in templates:
            if not tpl_title:
                continue
            ratio = SequenceMatcher(None, expected_plain_text, tpl_text or "").ratio()
            if ratio >= 0.8 and ratio > best_ratio:
                best_ratio = ratio
                best_title = str(tpl_title)
        return best_title
    except Exception:
        log.warning("watch batch title similarity failed", exc_info=True)
        return None


def _resolve_watch_title(
    *,
    resolved_similarity_title: Optional[str],
    expected_plain_text: str,
    expected_html: str,
    template_title: Optional[str],
    channel_title: str,
    group_title: str,
) -> str:
    resolved_title: Optional[str] = None
    if resolved_similarity_title:
        resolved_title = str(resolved_similarity_title)

    base_title_source = (
        resolved_title
        or template_title
        or expected_plain_text
        or expected_html
        or channel_title
        or group_title
        or ""
    )
    final_title = _first_line_title(base_title_source)
    if final_title:
        return final_title
    if group_title:
        return group_title
    return ""


def create_watches_from_network(command: WatchBatchCreateCommand) -> WatchBatchCreateResult:
    network_id = _safe_int(command.network_id)
    if not network_id:
        return WatchBatchCreateResult(
            status="error",
            network_id=0,
            project=command.project,
            error="invalid_network_id",
        )

    network_admin_id, network_name, channels = _load_network_channels(network_id)
    if not channels:
        return WatchBatchCreateResult(
            status="error",
            network_id=network_id,
            admin_id=_safe_int(command.admin_id) or network_admin_id,
            project=command.project,
            error="network_has_no_channels_or_missing",
        )

    expected_payload, expected_error = _resolve_expected_payload(command)
    if not expected_payload:
        return WatchBatchCreateResult(
            status="error",
            network_id=network_id,
            admin_id=_safe_int(command.admin_id) or network_admin_id,
            project=command.project,
            error=expected_error or "expected_payload_error",
        )

    admin_id = _safe_int(command.admin_id) or network_admin_id
    trace_id = _build_trace_id(command, str(expected_payload.get("expected_html") or ""))
    result = WatchBatchCreateResult(
        status="error",
        network_id=network_id,
        admin_id=admin_id,
        project=command.project,
        trace_id=trace_id,
    )
    log.info(
        "watch_batch_trace start trace_id=%s network_id=%s admin_id=%s project=%s tw_end=%s template_id=%s created_via=%s",
        trace_id,
        network_id,
        admin_id,
        command.project,
        command.time_window_end,
        expected_payload.get("template_id"),
        command.created_via,
    )

    channel_ids = [int(channel["channel_id"]) for channel in channels if channel.get("channel_id")]
    links_map = _enrich_links_map_for_channels(channel_ids, get_links_by_channel_ids(channel_ids))
    titles_map = get_titles_by_channel_ids(channel_ids)

    group_title_source = (
        expected_payload.get("template_title")
        or expected_payload.get("expected_plain_text")
        or expected_payload.get("expected_html")
        or network_name
    )
    group_title = _first_line_title(str(group_title_source or ""))
    created_via = str(command.created_via or "watch_network_batch").strip() or "watch_network_batch"
    resolved_similarity_title = _resolve_similarity_title(str(expected_payload.get("expected_plain_text") or ""))
    duplicate_map = watch_posts_db.find_active_duplicates_bulk(
        channel_ids=channel_ids,
        template_id=expected_payload.get("template_id"),
        expected_text_hash=str(expected_payload.get("expected_html") or ""),
        time_window_end=command.time_window_end,
    )

    channels_to_create: list[dict] = []
    for channel in channels:
        channel_id = _safe_int(channel.get("channel_id"))
        target = str(channel.get("target") or channel_id or "")
        if not channel_id:
            result.failed.append(
                WatchFailedItem(channel_id=None, target=target, reason="missing_channel_id")
            )
            continue

        duplicate = duplicate_map.get(int(channel_id))
        if duplicate:
            duplicate_time_window_end = str(duplicate.get("time_window_end") or "").strip()
            command_time_window_end = str(command.time_window_end or "").strip()
            duplicate_watch_id = int(duplicate.get("id") or 0)
            duplicate_status = str(duplicate.get("status") or "").strip() or "active"
            if duplicate_watch_id > 0:
                _safe_emit_watch_event(
                    duplicate_watch_id,
                    "batch_duplicate_skip",
                    {
                        "trace_id": trace_id,
                        "network_id": network_id,
                        "admin_id": admin_id,
                        "project": command.project,
                        "channel_id": int(channel_id),
                        "time_window_end": command.time_window_end,
                        "existing_time_window_end": duplicate_time_window_end or None,
                        "created_via": command.created_via,
                        "reason": "active_duplicate_same_unique_key",
                        "duplicate_status": duplicate_status,
                    },
                )
            log.info(
                "watch_batch_trace duplicate trace_id=%s watch_id=%s channel_id=%s status=%s tw_new=%s tw_existing=%s",
                trace_id,
                duplicate_watch_id,
                channel_id,
                duplicate_status,
                command_time_window_end or "—",
                duplicate_time_window_end or "—",
            )
            result.skipped.append(
                WatchFailedItem(
                    channel_id=int(channel_id),
                    target=target,
                    reason=(
                        f"duplicate_watch_id={duplicate_watch_id},status={duplicate_status},"
                        f"time_window_end={duplicate_time_window_end or '—'}"
                    ),
                )
            )
            continue

        channels_to_create.append(channel)

    if not channels_to_create:
        if result.skipped and not result.failed:
            result.status = "skipped"
            result.error = "idempotent_all_duplicates"
        else:
            result.status = "error"
            result.error = result.error or "no_channels_to_create"
        return result

    group_id = None
    try:
        group_id = watch_posts_db.create_watch_group(
            project=command.project,
            title=group_title,
            created_by=command.created_by,
            created_via=created_via,
            admin_id=admin_id,
            network_id=network_id,
        )
        log.info(
            "watch_batch_trace group trace_id=%s group_id=%s title=%r network_id=%s",
            trace_id,
            group_id,
            group_title,
            network_id,
        )
    except Exception:
        log.warning("watch batch create group failed", exc_info=True)
    result.group_id = group_id

    watch_insert_rows: list[dict] = []
    watch_insert_meta: list[dict] = []
    for channel in channels_to_create:
        channel_id = _safe_int(channel.get("channel_id"))
        target = str(channel.get("target") or channel_id or "")
        if not channel_id:
            result.failed.append(
                WatchFailedItem(channel_id=None, target=target, reason="missing_channel_id")
            )
            continue

        watch_title = _resolve_watch_title(
            resolved_similarity_title=resolved_similarity_title,
            expected_plain_text=str(expected_payload.get("expected_plain_text") or ""),
            expected_html=str(expected_payload.get("expected_html") or ""),
            template_title=expected_payload.get("template_title"),
            channel_title=str(channel.get("title") or titles_map.get(channel_id) or ""),
            group_title=group_title,
        )
        title_label = str(titles_map.get(channel_id) or channel.get("title") or target)
        source_url = str(links_map.get(channel_id) or target or "")

        watch_insert_rows.append(
            {
                "channel_id": int(channel_id),
                "group_id": group_id,
                "template_id": expected_payload.get("template_id"),
                "expected_text_hash": str(expected_payload.get("expected_html") or ""),
                "expected_text_norm_len": expected_payload.get("expected_plain_len"),
                "expected_links_json": expected_payload.get("expected_links_json"),
                "expected_media_fingerprint": None,
                "time_window_start": command.time_window_start,
                "time_window_end": command.time_window_end,
                "source_url": source_url,
                # direct-watch fallback зберігає created_by=None у watch_posts.
                "created_by": None,
                "created_via": created_via,
                "project": command.project,
                "admin_id": admin_id,
                "network_id": network_id,
                "title": watch_title,
                "is_reply": bool(expected_payload.get("is_reply")),
            }
        )
        watch_insert_meta.append(
            {
                "channel_id": int(channel_id),
                "target": target,
                "source_url": source_url,
                "title_label": title_label,
            }
        )

    if watch_insert_rows:
        created_watch_ids: list[int] = []
        try:
            created_watch_ids = watch_posts_db.bulk_create_watches(watch_insert_rows)
            if len(created_watch_ids) != len(watch_insert_rows):
                raise RuntimeError(
                    f"bulk_create_size_mismatch created={len(created_watch_ids)} expected={len(watch_insert_rows)}"
                )
        except Exception as error:
            log.warning(
                "watch_batch_trace bulk_create_failed trace_id=%s reason=%s:%s",
                trace_id,
                error.__class__.__name__,
                error,
                exc_info=True,
            )
            # Fallback to per-row create to preserve behavior in case of bulk edge failures.
            for row, meta in zip(watch_insert_rows, watch_insert_meta):
                channel_id = int(meta["channel_id"])
                try:
                    watch_id = watch_posts_db.create_watch(
                        channel_id=row.get("channel_id"),
                        group_id=row.get("group_id"),
                        template_id=row.get("template_id"),
                        expected_text_hash=row.get("expected_text_hash"),
                        expected_text_norm_len=row.get("expected_text_norm_len"),
                        expected_links_json=row.get("expected_links_json"),
                        expected_media_fingerprint=row.get("expected_media_fingerprint"),
                        time_window_start=row.get("time_window_start"),
                        time_window_end=row.get("time_window_end"),
                        source_url=row.get("source_url"),
                        created_by=row.get("created_by"),
                        created_via=row.get("created_via"),
                        project=row.get("project"),
                        admin_id=row.get("admin_id"),
                        network_id=row.get("network_id"),
                        title=row.get("title"),
                        is_reply=bool(row.get("is_reply")),
                    )
                    _safe_emit_watch_event(
                        int(watch_id),
                        "created",
                        {
                            "trace_id": trace_id,
                            "network_id": network_id,
                            "admin_id": admin_id,
                            "project": command.project,
                            "channel_id": channel_id,
                            "group_id": group_id,
                            "created_via": command.created_via,
                            "time_window_end": command.time_window_end,
                        },
                    )
                    log.info(
                        "watch_batch_trace created trace_id=%s watch_id=%s channel_id=%s group_id=%s fallback=single",
                        trace_id,
                        watch_id,
                        channel_id,
                        group_id,
                    )
                    result.created.append(
                        WatchCreatedItem(
                            channel_id=channel_id,
                            watch_id=int(watch_id),
                            link=str(meta.get("source_url") or ""),
                            title=str(meta.get("title_label") or meta.get("target") or channel_id),
                        )
                    )
                except TypeError as single_error:
                    result.failed.append(
                        WatchFailedItem(
                            channel_id=channel_id,
                            target=str(meta.get("target") or channel_id),
                            reason=f"TypeError: {single_error}",
                        )
                    )
                except Exception as single_error:
                    result.failed.append(
                        WatchFailedItem(
                            channel_id=channel_id,
                            target=str(meta.get("target") or channel_id),
                            reason=f"{single_error.__class__.__name__}: {single_error}",
                        )
                    )
        else:
            events_batch: list[tuple[int, str, str, Optional[str]]] = []
            for watch_id, meta in zip(created_watch_ids, watch_insert_meta):
                channel_id = int(meta["channel_id"])
                event_payload = {
                    "trace_id": trace_id,
                    "network_id": network_id,
                    "admin_id": admin_id,
                    "project": command.project,
                    "channel_id": channel_id,
                    "group_id": group_id,
                    "created_via": command.created_via,
                    "time_window_end": command.time_window_end,
                }
                events_batch.append((int(watch_id), "created", json.dumps(event_payload, ensure_ascii=False), None))
                log.info(
                    "watch_batch_trace created trace_id=%s watch_id=%s channel_id=%s group_id=%s",
                    trace_id,
                    watch_id,
                    channel_id,
                    group_id,
                )
                result.created.append(
                    WatchCreatedItem(
                        channel_id=channel_id,
                        watch_id=int(watch_id),
                        link=str(meta.get("source_url") or ""),
                        title=str(meta.get("title_label") or meta.get("target") or channel_id),
                    )
                )

            try:
                watch_events_db.insert_watch_events_batch(events_batch)
            except Exception:
                log.warning("watch_batch_trace bulk_events_failed trace_id=%s", trace_id, exc_info=True)
                for watch_id, event_type, payload_json, _ in events_batch:
                    try:
                        _safe_emit_watch_event(int(watch_id), str(event_type), json.loads(payload_json))
                    except Exception:
                        pass

    if result.created:
        result.status = "ok"
    elif result.skipped and not result.failed:
        result.status = "skipped"
        result.error = result.error or "idempotent_all_duplicates"
    else:
        result.status = "error"
        if not result.error:
            if result.failed:
                first_reason = str(result.failed[0].reason or "").strip()
                result.error = f"create_failed_all:{first_reason}" if first_reason else "create_failed_all"
            else:
                result.error = "create_failed_unknown"
    log.info(
        "watch_batch_trace finish trace_id=%s status=%s created=%s skipped=%s failed=%s group_id=%s error=%s",
        trace_id,
        result.status,
        result.created_count,
        result.skipped_count,
        result.failed_count,
        result.group_id,
        result.error,
    )
    return result
