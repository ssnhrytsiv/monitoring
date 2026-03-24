from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from sqlalchemy import func, select, union

from app.DAL.channel_subscription_audit_models import (
    ChannelSubscriptionAuditDetailsModel,
    ChannelSubscriptionAuditReasonEnum,
    ChannelSubscriptionAuditStatusEnum,
    parse_channel_subscription_audit_details,
)
from app.admin_bot.db import models as models
from app.db.session import SessionLocal
from app.utils.link_parser import sanitize_link

log = logging.getLogger(__name__)

CHANNEL_AUDIT_STATUS_SUBSCRIBED = ChannelSubscriptionAuditStatusEnum.SUBSCRIBED.value
CHANNEL_AUDIT_STATUS_MISSING = ChannelSubscriptionAuditStatusEnum.MISSING.value
CHANNEL_AUDIT_STATUS_UNKNOWN = ChannelSubscriptionAuditStatusEnum.UNKNOWN.value


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


def _normalize_session_name(session_name: str | None) -> str | None:
    normalized_session_name = str(session_name or "").strip()
    if not normalized_session_name:
        return None
    if normalized_session_name.endswith(".session"):
        normalized_session_name = normalized_session_name[:-8].strip()
    return normalized_session_name or None


def _normalize_failed_session_name_list(
    failed_session_name_list: Optional[Sequence[str]],
) -> List[str]:
    normalized_failed_session_name_set: Set[str] = set()
    for session_name in failed_session_name_list or []:
        normalized_session_name = _normalize_session_name(session_name)
        if not normalized_session_name:
            continue
        normalized_failed_session_name_set.add(normalized_session_name)
    return sorted(normalized_failed_session_name_set)


def _normalize_present_session_name_list(
    present_session_name_list: Optional[Sequence[str]],
) -> List[str]:
    normalized_present_session_name_set: Set[str] = set()
    for session_name in present_session_name_list or []:
        normalized_session_name = _normalize_session_name(session_name)
        if not normalized_session_name:
            continue
        normalized_present_session_name_set.add(normalized_session_name)
    return sorted(normalized_present_session_name_set)


def _normalize_session_channel_identifier_map(
    session_channel_identifier_map: Optional[Mapping[str, Sequence[int]]],
) -> Dict[str, Set[int]]:
    normalized_session_channel_identifier_map: Dict[str, Set[int]] = {}
    for session_name, channel_identifier_list in (session_channel_identifier_map or {}).items():
        normalized_session_name = _normalize_session_name(session_name)
        if not normalized_session_name:
            continue
        normalized_session_channel_identifier_map[normalized_session_name] = (
            _normalize_channel_identifier_set(channel_identifier_list)
        )
    return normalized_session_channel_identifier_map


def _build_present_session_name_list_by_channel_identifier(
    session_channel_identifier_map: Mapping[str, Set[int]],
) -> Dict[int, List[str]]:
    present_session_name_list_by_channel_identifier: Dict[int, Set[str]] = {}
    for session_name, channel_identifier_set in session_channel_identifier_map.items():
        for channel_identifier in channel_identifier_set:
            present_session_name_list_by_channel_identifier.setdefault(
                int(channel_identifier), set()
            ).add(session_name)
    return {
        channel_identifier: sorted(session_name_set)
        for channel_identifier, session_name_set in present_session_name_list_by_channel_identifier.items()
    }


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


def _build_audit_details_text(
    *,
    audit_reason: str,
    status_reason: ChannelSubscriptionAuditReasonEnum,
    expected_session_name: str | None,
    present_session_name_list: Sequence[str],
    failed_session_name_list: Sequence[str],
    assignment_row: models.ChannelSessionAssignment | None,
) -> str:
    details_model = ChannelSubscriptionAuditDetailsModel(
        audit_reason=audit_reason,
        status_reason=status_reason,
        expected_session=expected_session_name,
        present_sessions=list(present_session_name_list or []),
        failed_sessions=list(failed_session_name_list or []),
        admin_id=int(assignment_row.admin_id) if assignment_row and assignment_row.admin_id is not None else None,
        assignment_source=str(assignment_row.assignment_source or "").strip() if assignment_row else None,
        assignment_updated_at=int(assignment_row.updated_at) if assignment_row and assignment_row.updated_at is not None else None,
    )
    return details_model.model_dump_json()


def _resolve_missing_detected_at(
    *,
    existing_audit_row: models.ChannelSubscriptionAudit | None,
    audit_status: str,
    checked_at_timestamp: int,
) -> int | None:
    if audit_status == CHANNEL_AUDIT_STATUS_MISSING:
        if (
            existing_audit_row
            and existing_audit_row.audit_status == CHANNEL_AUDIT_STATUS_MISSING
            and existing_audit_row.missing_detected_at is not None
        ):
            return int(existing_audit_row.missing_detected_at)
        return checked_at_timestamp

    if (
        audit_status == CHANNEL_AUDIT_STATUS_UNKNOWN
        and existing_audit_row
        and existing_audit_row.audit_status == CHANNEL_AUDIT_STATUS_MISSING
        and existing_audit_row.missing_detected_at is not None
    ):
        return int(existing_audit_row.missing_detected_at)

    return None


def _resolve_assignment_aware_audit_state(
    *,
    assignment_row: models.ChannelSessionAssignment | None,
    present_session_name_list: Sequence[str],
    failed_session_name_set: Set[str],
) -> Tuple[str, ChannelSubscriptionAuditReasonEnum, str | None]:
    expected_session_name = _normalize_session_name(
        assignment_row.session_name if assignment_row else None
    )
    normalized_present_session_name_list = [
        normalized_session_name
        for normalized_session_name in (
            _normalize_session_name(session_name)
            for session_name in (present_session_name_list or [])
        )
        if normalized_session_name
    ]

    if expected_session_name:
        if expected_session_name in failed_session_name_set:
            return (
                CHANNEL_AUDIT_STATUS_UNKNOWN,
                ChannelSubscriptionAuditReasonEnum.EXPECTED_SESSION_SCAN_FAILED,
                expected_session_name,
            )
        if expected_session_name in normalized_present_session_name_list:
            if len(normalized_present_session_name_list) > 1:
                return (
                    CHANNEL_AUDIT_STATUS_SUBSCRIBED,
                    ChannelSubscriptionAuditReasonEnum.EXPECTED_SESSION_PRESENT_WITH_DUPLICATES,
                    expected_session_name,
                )
            return (
                CHANNEL_AUDIT_STATUS_SUBSCRIBED,
                ChannelSubscriptionAuditReasonEnum.EXPECTED_SESSION_PRESENT,
                expected_session_name,
            )
        if normalized_present_session_name_list:
            return (
                CHANNEL_AUDIT_STATUS_MISSING,
                ChannelSubscriptionAuditReasonEnum.EXPECTED_SESSION_MISSING_PRESENT_ELSEWHERE,
                expected_session_name,
            )
        return (
            CHANNEL_AUDIT_STATUS_MISSING,
            ChannelSubscriptionAuditReasonEnum.EXPECTED_SESSION_MISSING_EVERYWHERE,
            expected_session_name,
        )

    if normalized_present_session_name_list:
        return (
            CHANNEL_AUDIT_STATUS_SUBSCRIBED,
            ChannelSubscriptionAuditReasonEnum.UNASSIGNED_PRESENT_IN_POOL,
            None,
        )
    if failed_session_name_set:
        return (
            CHANNEL_AUDIT_STATUS_UNKNOWN,
            ChannelSubscriptionAuditReasonEnum.UNASSIGNED_SCAN_INCOMPLETE,
            None,
        )
    return (
        CHANNEL_AUDIT_STATUS_MISSING,
        ChannelSubscriptionAuditReasonEnum.UNASSIGNED_MISSING_IN_POOL,
        None,
    )


def get_channel_subscription_audit_details(
    channel_id: int,
    *,
    database_session=None,
) -> ChannelSubscriptionAuditDetailsModel | None:
    if channel_id is None:
        return None
    should_close_session = database_session is None
    database_session = database_session or SessionLocal()
    try:
        audit_row = (
            database_session.query(models.ChannelSubscriptionAudit.status_details)
            .filter(models.ChannelSubscriptionAudit.channel_id == int(channel_id))
            .limit(1)
            .one_or_none()
        )
        if not audit_row:
            return None
        return parse_channel_subscription_audit_details(audit_row[0])
    finally:
        if should_close_session:
            database_session.close()


def should_bypass_positive_channel_cache(
    channel_id: int,
    *,
    database_session=None,
) -> bool:
    """
    Якщо audit уже зафіксував MISSING для каналу, старі cache-джерела типу
    membership/url_cache/invite_map не можна вважати authoritative для
    позитивних short-circuit статусів (`already`, `joined`, історичний `requested`).
    """
    if channel_id is None:
        return False
    should_close_session = database_session is None
    database_session = database_session or SessionLocal()
    try:
        audit_row = (
            database_session.query(models.ChannelSubscriptionAudit.audit_status)
            .filter(models.ChannelSubscriptionAudit.channel_id == int(channel_id))
            .limit(1)
            .one_or_none()
        )
        if not audit_row:
            return False
        return str(audit_row[0] or "").strip() == CHANNEL_AUDIT_STATUS_MISSING
    finally:
        if should_close_session:
            database_session.close()


def refresh_channel_subscription_audit_snapshot(
    subscribed_channel_identifier_list: Sequence[int],
    failed_session_name_list: Optional[Sequence[str]] = None,
    audit_reason: str = "periodic",
) -> None:
    normalized_subscribed_channel_identifier_set = _normalize_channel_identifier_set(
        subscribed_channel_identifier_list
    )
    normalized_failed_session_name_list = _normalize_failed_session_name_list(
        failed_session_name_list
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
        existing_audit_row_by_channel_identifier: Dict[
            int, models.ChannelSubscriptionAudit
        ] = {}
        if tracked_channel_identifier_set:
            for existing_audit_row in (
                database_session.query(models.ChannelSubscriptionAudit)
                .filter(
                    models.ChannelSubscriptionAudit.channel_id.in_(
                        list(tracked_channel_identifier_set)
                    )
                )
                .all()
            ):
                existing_audit_row_by_channel_identifier[
                    int(existing_audit_row.channel_id)
                ] = existing_audit_row

        failed_session_name_set = set(normalized_failed_session_name_list)
        for tracked_channel_identifier in tracked_channel_identifier_set:
            existing_audit_row = existing_audit_row_by_channel_identifier.get(
                tracked_channel_identifier
            )
            present_session_name_list: List[str] = []
            if tracked_channel_identifier in normalized_subscribed_channel_identifier_set:
                audit_status = CHANNEL_AUDIT_STATUS_SUBSCRIBED
                status_reason = ChannelSubscriptionAuditReasonEnum.UNASSIGNED_PRESENT_IN_POOL
            elif failed_session_name_set:
                audit_status = CHANNEL_AUDIT_STATUS_UNKNOWN
                status_reason = ChannelSubscriptionAuditReasonEnum.UNASSIGNED_SCAN_INCOMPLETE
            else:
                audit_status = CHANNEL_AUDIT_STATUS_MISSING
                status_reason = ChannelSubscriptionAuditReasonEnum.UNASSIGNED_MISSING_IN_POOL

            missing_detected_at_timestamp = _resolve_missing_detected_at(
                existing_audit_row=existing_audit_row,
                audit_status=audit_status,
                checked_at_timestamp=checked_at_timestamp,
            )
            status_details = _build_audit_details_text(
                audit_reason=audit_reason,
                status_reason=status_reason,
                expected_session_name=None,
                present_session_name_list=present_session_name_list,
                failed_session_name_list=normalized_failed_session_name_list,
                assignment_row=None,
            )

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


def refresh_channel_subscription_audit_snapshot_from_session_map(
    session_channel_identifier_map: Mapping[str, Sequence[int]],
    failed_session_name_list: Optional[Sequence[str]] = None,
    audit_reason: str = "periodic",
) -> None:
    normalized_session_channel_identifier_map = _normalize_session_channel_identifier_map(
        session_channel_identifier_map
    )
    normalized_failed_session_name_list = _normalize_failed_session_name_list(
        failed_session_name_list
    )
    failed_session_name_set = set(normalized_failed_session_name_list)
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
        existing_audit_row_by_channel_identifier: Dict[
            int, models.ChannelSubscriptionAudit
        ] = {}
        assignment_row_by_channel_identifier: Dict[
            int, models.ChannelSessionAssignment
        ] = {}
        if tracked_channel_identifier_set:
            tracked_channel_identifier_list = list(tracked_channel_identifier_set)
            for existing_audit_row in (
                database_session.query(models.ChannelSubscriptionAudit)
                .filter(
                    models.ChannelSubscriptionAudit.channel_id.in_(
                        tracked_channel_identifier_list
                    )
                )
                .all()
            ):
                existing_audit_row_by_channel_identifier[
                    int(existing_audit_row.channel_id)
                ] = existing_audit_row
            for assignment_row in (
                database_session.query(models.ChannelSessionAssignment)
                .filter(
                    models.ChannelSessionAssignment.channel_id.in_(
                        tracked_channel_identifier_list
                    )
                )
                .all()
            ):
                assignment_row_by_channel_identifier[
                    int(assignment_row.channel_id)
                ] = assignment_row

        present_session_name_list_by_channel_identifier = (
            _build_present_session_name_list_by_channel_identifier(
                normalized_session_channel_identifier_map
            )
        )

        for tracked_channel_identifier in tracked_channel_identifier_set:
            existing_audit_row = existing_audit_row_by_channel_identifier.get(
                tracked_channel_identifier
            )
            assignment_row = assignment_row_by_channel_identifier.get(
                tracked_channel_identifier
            )
            present_session_name_list = present_session_name_list_by_channel_identifier.get(
                tracked_channel_identifier,
                [],
            )
            audit_status, status_reason, expected_session_name = (
                _resolve_assignment_aware_audit_state(
                    assignment_row=assignment_row,
                    present_session_name_list=present_session_name_list,
                    failed_session_name_set=failed_session_name_set,
                )
            )
            missing_detected_at_timestamp = _resolve_missing_detected_at(
                existing_audit_row=existing_audit_row,
                audit_status=audit_status,
                checked_at_timestamp=checked_at_timestamp,
            )
            status_details = _build_audit_details_text(
                audit_reason=audit_reason,
                status_reason=status_reason,
                expected_session_name=expected_session_name,
                present_session_name_list=present_session_name_list,
                failed_session_name_list=normalized_failed_session_name_list,
                assignment_row=assignment_row,
            )

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


def refresh_channel_subscription_audit_for_channel(
    channel_id: int,
    *,
    present_session_name_list: Optional[Sequence[str]] = None,
    failed_session_name_list: Optional[Sequence[str]] = None,
    audit_reason: str = "targeted",
) -> str:
    normalized_channel_id = int(channel_id)
    normalized_present_session_name_list = _normalize_present_session_name_list(
        present_session_name_list
    )
    normalized_failed_session_name_list = _normalize_failed_session_name_list(
        failed_session_name_list
    )
    failed_session_name_set = set(normalized_failed_session_name_list)
    checked_at_timestamp = int(time.time())
    database_session = SessionLocal()
    try:
        existing_audit_row = (
            database_session.query(models.ChannelSubscriptionAudit)
            .filter(models.ChannelSubscriptionAudit.channel_id == normalized_channel_id)
            .one_or_none()
        )
        assignment_row = (
            database_session.query(models.ChannelSessionAssignment)
            .filter(models.ChannelSessionAssignment.channel_id == normalized_channel_id)
            .one_or_none()
        )
        audit_status, status_reason, expected_session_name = (
            _resolve_assignment_aware_audit_state(
                assignment_row=assignment_row,
                present_session_name_list=normalized_present_session_name_list,
                failed_session_name_set=failed_session_name_set,
            )
        )
        missing_detected_at_timestamp = _resolve_missing_detected_at(
            existing_audit_row=existing_audit_row,
            audit_status=audit_status,
            checked_at_timestamp=checked_at_timestamp,
        )
        status_details = _build_audit_details_text(
            audit_reason=audit_reason,
            status_reason=status_reason,
            expected_session_name=expected_session_name,
            present_session_name_list=normalized_present_session_name_list,
            failed_session_name_list=normalized_failed_session_name_list,
            assignment_row=assignment_row,
        )

        if existing_audit_row:
            existing_audit_row.audit_status = audit_status
            existing_audit_row.checked_at = checked_at_timestamp
            existing_audit_row.missing_detected_at = missing_detected_at_timestamp
            existing_audit_row.status_details = status_details
        else:
            database_session.add(
                models.ChannelSubscriptionAudit(
                    channel_id=normalized_channel_id,
                    audit_status=audit_status,
                    checked_at=checked_at_timestamp,
                    missing_detected_at=missing_detected_at_timestamp,
                    status_details=status_details,
                )
            )
        database_session.commit()
        return audit_status
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
