from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import func, select, union

from app.admin_bot.db import models as models
from app.db.session import SessionLocal
from app.utils.link_parser import sanitize_link

log = logging.getLogger(__name__)

CHANNEL_AUDIT_STATUS_SUBSCRIBED = "subscribed"
CHANNEL_AUDIT_STATUS_MISSING = "missing"
CHANNEL_AUDIT_STATUS_UNKNOWN = "unknown"


def _normalize_channel_identifier_set(channel_identifier_list: Sequence[int]) -> Set[int]:
    normalized_channel_identifier_set: Set[int] = set()
    for channel_identifier in channel_identifier_list or []:
        if channel_identifier is None:
            continue
        try:
            normalized_channel_identifier_set.add(int(channel_identifier))
        except Exception:
            continue
    return normalized_channel_identifier_set


def _build_admin_channel_scope_subquery(admin_identifier: int):
    admin_channel_select_statement = (
        select(models.AdminChannel.channel_id.label("channel_id"))
        .where(models.AdminChannel.admin_id == int(admin_identifier))
    )
    network_channel_select_statement = (
        select(models.NetworkChannel.channel_id.label("channel_id"))
        .join(models.Network, models.Network.id == models.NetworkChannel.network_id)
        .where(models.Network.admin_id == int(admin_identifier))
    )
    return union(admin_channel_select_statement, network_channel_select_statement).subquery()


def _build_all_admin_channel_scope_subquery():
    admin_channel_select_statement = select(
        models.AdminChannel.channel_id.label("channel_id")
    )
    network_channel_select_statement = (
        select(models.NetworkChannel.channel_id.label("channel_id"))
        .join(models.Network, models.Network.id == models.NetworkChannel.network_id)
        .where(models.Network.admin_id.isnot(None))
    )
    return union(admin_channel_select_statement, network_channel_select_statement).subquery()


def refresh_channel_subscription_audit_snapshot(
    subscribed_channel_identifier_list: Sequence[int],
    failed_session_name_list: Optional[Sequence[str]] = None,
    audit_reason: str = "periodic",
) -> None:
    normalized_subscribed_channel_identifier_set = _normalize_channel_identifier_set(subscribed_channel_identifier_list)
    normalized_failed_session_name_list = sorted(
        {str(session_name).strip() for session_name in (failed_session_name_list or []) if str(session_name).strip()}
    )
    checked_at_timestamp = int(time.time())
    database_session = SessionLocal()
    try:
        tracked_channel_identifier_set: Set[int] = {
            int(channel_identifier)
            for channel_identifier in database_session.execute(
                select(models.Channel.channel_id).where(models.Channel.channel_id.isnot(None))
            ).scalars().all()
            if channel_identifier is not None
        }
        subscribed_tracked_channel_identifier_set = (
            normalized_subscribed_channel_identifier_set & tracked_channel_identifier_set
        )
        existing_audit_row_by_channel_identifier: Dict[int, models.ChannelSubscriptionAudit] = {}
        if tracked_channel_identifier_set:
            for existing_audit_row in (
                database_session.query(models.ChannelSubscriptionAudit)
                .filter(models.ChannelSubscriptionAudit.channel_id.in_(list(tracked_channel_identifier_set)))
                .all()
            ):
                existing_audit_row_by_channel_identifier[int(existing_audit_row.channel_id)] = existing_audit_row

        for tracked_channel_identifier in tracked_channel_identifier_set:
            existing_audit_row = existing_audit_row_by_channel_identifier.get(tracked_channel_identifier)
            audit_status = CHANNEL_AUDIT_STATUS_SUBSCRIBED
            missing_detected_at_timestamp = None
            status_details = None

            if tracked_channel_identifier in subscribed_tracked_channel_identifier_set:
                audit_status = CHANNEL_AUDIT_STATUS_SUBSCRIBED
            elif normalized_failed_session_name_list:
                audit_status = CHANNEL_AUDIT_STATUS_UNKNOWN
                status_details = (
                    f"audit_reason={audit_reason}; "
                    f"scan_failed_sessions={','.join(normalized_failed_session_name_list)}"
                )
                if (
                    existing_audit_row
                    and existing_audit_row.audit_status == CHANNEL_AUDIT_STATUS_MISSING
                    and existing_audit_row.missing_detected_at is not None
                ):
                    missing_detected_at_timestamp = int(existing_audit_row.missing_detected_at)
            else:
                audit_status = CHANNEL_AUDIT_STATUS_MISSING
                status_details = f"audit_reason={audit_reason}"
                if (
                    existing_audit_row
                    and existing_audit_row.audit_status == CHANNEL_AUDIT_STATUS_MISSING
                    and existing_audit_row.missing_detected_at is not None
                ):
                    missing_detected_at_timestamp = int(existing_audit_row.missing_detected_at)
                else:
                    missing_detected_at_timestamp = checked_at_timestamp

            if existing_audit_row:
                existing_audit_row.audit_status = audit_status
                existing_audit_row.checked_at = checked_at_timestamp
                existing_audit_row.missing_detected_at = missing_detected_at_timestamp
                existing_audit_row.status_details = status_details
            else:
                database_session.add(
                    models.ChannelSubscriptionAudit(
                        channel_id=tracked_channel_identifier,
                        audit_status=audit_status,
                        checked_at=checked_at_timestamp,
                        missing_detected_at=missing_detected_at_timestamp,
                        status_details=status_details,
                    )
                )

        if tracked_channel_identifier_set:
            (
                database_session.query(models.ChannelSubscriptionAudit)
                .filter(
                    models.ChannelSubscriptionAudit.channel_id.notin_(
                        list(tracked_channel_identifier_set)
                    )
                )
                .delete(synchronize_session=False)
            )
        else:
            database_session.query(models.ChannelSubscriptionAudit).delete(
                synchronize_session=False
            )
        database_session.commit()
    except Exception:
        database_session.rollback()
        raise
    finally:
        database_session.close()


def count_missing_channels_for_admin(admin_identifier: int) -> int:
    database_session = SessionLocal()
    try:
        admin_channel_scope_subquery = _build_admin_channel_scope_subquery(admin_identifier)
        missing_channel_count = (
            database_session.execute(
                select(func.count())
                .select_from(models.ChannelSubscriptionAudit)
                .join(
                    admin_channel_scope_subquery,
                    admin_channel_scope_subquery.c.channel_id
                    == models.ChannelSubscriptionAudit.channel_id,
                )
                .where(
                    models.ChannelSubscriptionAudit.audit_status
                    == CHANNEL_AUDIT_STATUS_MISSING
                )
            ).scalar()
            or 0
        )
        return int(missing_channel_count)
    except Exception as error:
        log.warning(
            "count_missing_channels_for_admin failed for admin_identifier=%s: %s",
            admin_identifier,
            error,
        )
        return 0
    finally:
        database_session.close()


def count_missing_channels_for_all_admins() -> int:
    database_session = SessionLocal()
    try:
        all_admin_channel_scope_subquery = _build_all_admin_channel_scope_subquery()
        total_missing_channel_count = (
            database_session.execute(
                select(func.count())
                .select_from(models.ChannelSubscriptionAudit)
                .join(
                    all_admin_channel_scope_subquery,
                    all_admin_channel_scope_subquery.c.channel_id
                    == models.ChannelSubscriptionAudit.channel_id,
                )
                .where(
                    models.ChannelSubscriptionAudit.audit_status
                    == CHANNEL_AUDIT_STATUS_MISSING
                )
            ).scalar()
            or 0
        )
        return int(total_missing_channel_count)
    except Exception as error:
        log.warning("count_missing_channels_for_all_admins failed: %s", error)
        return 0
    finally:
        database_session.close()


def list_missing_channels_for_admin(
    admin_identifier: int,
    page_number: int = 0,
    page_size: int = 20,
) -> Tuple[List[Dict[str, Any]], int]:
    safe_page_number = max(0, int(page_number))
    safe_page_size = max(1, int(page_size))
    database_session = SessionLocal()
    try:
        admin_channel_scope_subquery = _build_admin_channel_scope_subquery(admin_identifier)

        total_missing_channel_count = (
            database_session.execute(
                select(func.count())
                .select_from(models.ChannelSubscriptionAudit)
                .join(
                    admin_channel_scope_subquery,
                    admin_channel_scope_subquery.c.channel_id
                    == models.ChannelSubscriptionAudit.channel_id,
                )
                .where(
                    models.ChannelSubscriptionAudit.audit_status
                    == CHANNEL_AUDIT_STATUS_MISSING
                )
            ).scalar()
            or 0
        )

        invite_hash_subquery = (
            select(models.InviteMap.invite_hash)
            .where(
                models.InviteMap.channel_id
                == models.ChannelSubscriptionAudit.channel_id
            )
            .limit(1)
            .scalar_subquery()
        )
        raw_url_subquery = (
            select(models.Link.raw_url)
            .where(
                models.Link.channel_id
                == models.ChannelSubscriptionAudit.channel_id,
                models.Link.raw_url.isnot(None),
            )
            .order_by(models.Link.id.desc())
            .limit(1)
            .scalar_subquery()
        )

        missing_channel_row_list = database_session.execute(
            select(
                models.ChannelSubscriptionAudit.channel_id,
                models.ChannelSubscriptionAudit.audit_status,
                models.ChannelSubscriptionAudit.checked_at,
                models.ChannelSubscriptionAudit.missing_detected_at,
                models.Channel.title,
                models.Channel.username,
                invite_hash_subquery.label("invite_hash"),
                raw_url_subquery.label("raw_url"),
            )
            .select_from(models.ChannelSubscriptionAudit)
            .join(
                admin_channel_scope_subquery,
                admin_channel_scope_subquery.c.channel_id
                == models.ChannelSubscriptionAudit.channel_id,
            )
            .outerjoin(
                models.Channel,
                models.Channel.channel_id
                == models.ChannelSubscriptionAudit.channel_id,
            )
            .where(
                models.ChannelSubscriptionAudit.audit_status
                == CHANNEL_AUDIT_STATUS_MISSING
            )
            .order_by(
                models.ChannelSubscriptionAudit.missing_detected_at.desc().nullslast(),
                models.ChannelSubscriptionAudit.checked_at.desc(),
                models.ChannelSubscriptionAudit.channel_id.desc(),
            )
            .offset(safe_page_number * safe_page_size)
            .limit(safe_page_size)
        ).all()

        missing_channel_record_list: List[Dict[str, Any]] = []
        for missing_channel_row in missing_channel_row_list:
            channel_identifier = int(missing_channel_row.channel_id)
            channel_title = str(missing_channel_row.title or "").strip()
            channel_username = str(missing_channel_row.username or "").strip()
            invite_hash = str(missing_channel_row.invite_hash or "").strip()
            raw_url = str(missing_channel_row.raw_url or "").strip()

            channel_label = channel_title
            if not channel_label and channel_username:
                channel_label = f"@{channel_username.lstrip('@')}"
            if not channel_label:
                channel_label = str(channel_identifier)

            channel_url = None
            if channel_username:
                channel_url = f"https://t.me/{channel_username.lstrip('@')}"
            elif invite_hash:
                channel_url = f"https://t.me/+{invite_hash}"
            elif raw_url:
                try:
                    channel_url = sanitize_link(raw_url) or raw_url
                except Exception:
                    channel_url = raw_url

            missing_channel_record_list.append(
                {
                    "channel_id": channel_identifier,
                    "channel_label": channel_label,
                    "channel_url": channel_url,
                    "audit_status": str(missing_channel_row.audit_status or ""),
                    "checked_at": int(missing_channel_row.checked_at or 0),
                    "missing_detected_at": int(
                        missing_channel_row.missing_detected_at
                    )
                    if missing_channel_row.missing_detected_at is not None
                    else None,
                }
            )

        return missing_channel_record_list, int(total_missing_channel_count)
    except Exception as error:
        log.warning(
            "list_missing_channels_for_admin failed for admin_identifier=%s: %s",
            admin_identifier,
            error,
        )
        return [], 0
    finally:
        database_session.close()


def list_admin_channels_in_service_add_order(
    admin_identifier: int,
    page_number: int = 0,
    page_size: int = 50,
) -> Tuple[List[Dict[str, Any]], int]:
    safe_page_number = max(0, int(page_number))
    safe_page_size = max(1, int(page_size))
    database_session = SessionLocal()
    try:
        total_channel_count = (
            database_session.execute(
                select(func.count())
                .select_from(models.AdminChannel)
                .where(models.AdminChannel.admin_id == int(admin_identifier))
            ).scalar()
            or 0
        )

        invite_hash_subquery = (
            select(models.InviteMap.invite_hash)
            .where(models.InviteMap.channel_id == models.AdminChannel.channel_id)
            .limit(1)
            .scalar_subquery()
        )
        raw_url_subquery = (
            select(models.Link.raw_url)
            .where(
                models.Link.channel_id == models.AdminChannel.channel_id,
                models.Link.raw_url.isnot(None),
            )
            .order_by(models.Link.id.desc())
            .limit(1)
            .scalar_subquery()
        )

        ordered_channel_row_list = database_session.execute(
            select(
                models.AdminChannel.id,
                models.AdminChannel.channel_id,
                models.Channel.title,
                models.Channel.username,
                models.ChannelSubscriptionAudit.audit_status,
                invite_hash_subquery.label("invite_hash"),
                raw_url_subquery.label("raw_url"),
            )
            .select_from(models.AdminChannel)
            .outerjoin(
                models.Channel,
                models.Channel.channel_id == models.AdminChannel.channel_id,
            )
            .outerjoin(
                models.ChannelSubscriptionAudit,
                models.ChannelSubscriptionAudit.channel_id
                == models.AdminChannel.channel_id,
            )
            .where(models.AdminChannel.admin_id == int(admin_identifier))
            .order_by(models.AdminChannel.id.asc())
            .offset(safe_page_number * safe_page_size)
            .limit(safe_page_size)
        ).all()

        ordered_channel_record_list: List[Dict[str, Any]] = []
        for ordered_channel_row in ordered_channel_row_list:
            channel_identifier = int(ordered_channel_row.channel_id)
            channel_title = str(ordered_channel_row.title or "").strip()
            channel_username = str(ordered_channel_row.username or "").strip()
            invite_hash = str(ordered_channel_row.invite_hash or "").strip()
            raw_url = str(ordered_channel_row.raw_url or "").strip()

            channel_label = channel_title
            if not channel_label and channel_username:
                channel_label = f"@{channel_username.lstrip('@')}"
            if not channel_label:
                channel_label = str(channel_identifier)

            channel_url = None
            if channel_username:
                channel_url = f"https://t.me/{channel_username.lstrip('@')}"
            elif invite_hash:
                channel_url = f"https://t.me/+{invite_hash}"
            elif raw_url:
                try:
                    channel_url = sanitize_link(raw_url) or raw_url
                except Exception:
                    channel_url = raw_url

            ordered_channel_record_list.append(
                {
                    "service_add_order_identifier": int(ordered_channel_row.id),
                    "channel_id": channel_identifier,
                    "channel_label": channel_label,
                    "channel_url": channel_url,
                    "audit_status": str(ordered_channel_row.audit_status or ""),
                }
            )

        return ordered_channel_record_list, int(total_channel_count)
    except Exception as error:
        log.warning(
            "list_admin_channels_in_service_add_order failed for admin_identifier=%s: %s",
            admin_identifier,
            error,
        )
        return [], 0
    finally:
        database_session.close()
