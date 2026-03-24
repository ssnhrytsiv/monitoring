from __future__ import annotations

import logging
from typing import Dict

from app.DAL import SessionLocal
from app.DAL.membership_operations import MembershipDAO
from app.services import account_pool

log = logging.getLogger("services.channel_session_cleanup")


def _normalize_session_name(session_name_value: str | None) -> str:
    normalized_session_name = str(session_name_value or "").strip()
    if normalized_session_name.endswith(".session"):
        normalized_session_name = normalized_session_name[:-8].strip()
    return normalized_session_name


async def enforce_single_session_per_channel(
    *,
    channel_id: int | None,
    keep_session_name: str | None,
    reason: str,
    observed_session_name_list: list[str] | None = None,
) -> Dict[str, int]:
    cleanup_stats = {
        "checked": 0,
        "left": 0,
        "skipped": 0,
        "errors": 0,
        "deleted": 0,
        "stale_db_only": 0,
    }
    if channel_id is None or not keep_session_name:
        return cleanup_stats

    normalized_keep_session_name = _normalize_session_name(keep_session_name)
    if not normalized_keep_session_name:
        return cleanup_stats

    membership_account_value_list: list[str] = []
    database_session = SessionLocal()
    try:
        membership_account_value_list = MembershipDAO(
            database_session
        ).list_membership_accounts_for_channel(int(channel_id))
    finally:
        database_session.close()

    candidate_membership_account_value_list = list(membership_account_value_list)
    for observed_session_name in observed_session_name_list or []:
        observed_session_name = str(observed_session_name or "").strip()
        if not observed_session_name:
            continue
        candidate_membership_account_value_list.append(observed_session_name)

    stale_membership_account_value_list: list[str] = []
    seen_stale_session_name_set: set[str] = set()
    for membership_account_value in candidate_membership_account_value_list:
        normalized_membership_account_value = _normalize_session_name(
            membership_account_value
        )
        if (
            not normalized_membership_account_value
            or normalized_membership_account_value == normalized_keep_session_name
            or normalized_membership_account_value in seen_stale_session_name_set
        ):
            continue
        seen_stale_session_name_set.add(normalized_membership_account_value)
        stale_membership_account_value_list.append(membership_account_value)

    for stale_membership_account_value in stale_membership_account_value_list:
        cleanup_stats["checked"] += 1
        normalized_stale_session_name = _normalize_session_name(
            stale_membership_account_value
        )
        should_delete_membership = False
        leave_result = None
        try:
            leave_result = await account_pool.leave_channels(
                normalized_stale_session_name,
                [int(channel_id)],
            )
        except Exception:
            cleanup_stats["errors"] += 1
            log.exception(
                "channel_session_cleanup.leave_failed cid=%s stale=%s keep=%s reason=%s",
                channel_id,
                normalized_stale_session_name,
                normalized_keep_session_name,
                reason,
            )
            continue

        cleanup_stats["left"] += int(leave_result.get("left", 0) or 0)
        cleanup_stats["skipped"] += int(leave_result.get("skipped", 0) or 0)
        cleanup_stats["errors"] += int(leave_result.get("errors", 0) or 0)

        if str(leave_result.get("reason") or "").strip() == "session_not_in_pool":
            should_delete_membership = True
            cleanup_stats["stale_db_only"] += 1
        elif int(leave_result.get("errors", 0) or 0) == 0:
            should_delete_membership = True

        if not should_delete_membership:
            log.warning(
                "channel_session_cleanup.leave_incomplete cid=%s stale=%s keep=%s reason=%s leave_result=%s",
                channel_id,
                normalized_stale_session_name,
                normalized_keep_session_name,
                reason,
                leave_result,
            )
            continue

        delete_session = SessionLocal()
        try:
            deleted_row_count = MembershipDAO(delete_session).delete_membership(
                stale_membership_account_value,
                int(channel_id),
            )
            cleanup_stats["deleted"] += int(deleted_row_count or 0)
        finally:
            delete_session.close()

    if cleanup_stats["deleted"] > 0 or cleanup_stats["left"] > 0:
        log.info(
            "channel_session_cleanup.done cid=%s keep=%s reason=%s stats=%s",
            channel_id,
            normalized_keep_session_name,
            reason,
            cleanup_stats,
        )
    return cleanup_stats
