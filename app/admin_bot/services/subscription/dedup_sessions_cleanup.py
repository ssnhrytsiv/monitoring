from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Dict, List, Sequence

from telethon.tl import types as tl_types

from app.DAL import SessionLocal
from app.DAL import channel_session_assignment_operations as assignment_ops
from app.DAL import channel_subscription_audit_operations as audit_ops
from app.DAL.membership_operations import MembershipDAO
from app.services import account_pool
from app.services.account_pool import iter_pool_clients
from app.services.channel_session_cleanup import enforce_single_session_per_channel

log = logging.getLogger("admin_bot.services.subscription.dedup_sessions_cleanup")


@dataclass(frozen=True)
class DuplicateCleanupPlanItem:
    channel_id: int
    title: str
    observed_session_name_list: List[str]
    keep_session_name: str
    keep_reason: str
    assigned_session_name: str | None = None

    @property
    def leave_session_name_list(self) -> List[str]:
        return [
            session_name
            for session_name in self.observed_session_name_list
            if session_name != self.keep_session_name
        ]


@dataclass(frozen=True)
class DuplicateCleanupScanResult:
    plan_item_list: List[DuplicateCleanupPlanItem]
    error_text_list: List[str]


@dataclass(frozen=True)
class DuplicateCleanupExecutionItem:
    channel_id: int
    title: str
    keep_session_name: str
    keep_reason: str
    observed_session_name_list: List[str]
    cleanup_stats: Dict[str, int]


def _normalize_session_name(session_name_value: str | None) -> str:
    normalized_session_name = str(session_name_value or "").strip()
    if normalized_session_name.endswith(".session"):
        normalized_session_name = normalized_session_name[:-8].strip()
    return normalized_session_name


def _choose_keep_session_name(
    *,
    channel_id: int,
    observed_session_name_list: Sequence[str],
    membership_db: MembershipDAO,
    database_session,
) -> tuple[str, str, str | None]:
    normalized_observed_session_name_list = [
        _normalize_session_name(session_name)
        for session_name in (observed_session_name_list or [])
        if _normalize_session_name(session_name)
    ]
    observed_session_name_set = set(normalized_observed_session_name_list)

    assignment_row = assignment_ops.get_channel_session_assignment(
        int(channel_id),
        database_session=database_session,
    )
    assigned_session_name = _normalize_session_name(
        assignment_row.session_name if assignment_row else None
    )
    if assigned_session_name and assigned_session_name in observed_session_name_set:
        return assigned_session_name, "assignment", assigned_session_name

    membership_session_name = _normalize_session_name(
        membership_db.get_session_by_channel(int(channel_id))
    )
    if membership_session_name and membership_session_name in observed_session_name_set:
        return membership_session_name, "membership_fallback", assigned_session_name

    keep_session_name = sorted(observed_session_name_set)[-1]
    return keep_session_name, "sorted_fallback", assigned_session_name


async def collect_duplicate_cleanup_scan_result() -> DuplicateCleanupScanResult:
    session_channel_title_map_by_session_name: dict[str, dict[int, str]] = {}
    error_text_list: list[str] = []

    async def _collect_for_slot(slot) -> dict[int, str]:
        channel_title_map_by_channel_id: dict[int, str] = {}
        try:
            async for dialog in slot.client.iter_dialogs():
                entity = dialog.entity
                if isinstance(entity, tl_types.Channel):
                    channel_id = int(entity.id)
                    title = getattr(entity, "title", "") or dialog.name or ""
                    channel_title_map_by_channel_id[channel_id] = title
        except Exception as exception:
            error_text_list.append(f"{slot.name}: {exception}")
        return channel_title_map_by_channel_id

    for slot in iter_pool_clients():
        channel_title_map_by_channel_id = await _collect_for_slot(slot)
        session_channel_title_map_by_session_name[slot.name] = (
            channel_title_map_by_channel_id
        )

    observed_session_name_title_tuple_list_by_channel_id: dict[
        int, list[tuple[str, str]]
    ] = {}
    for session_name, channel_title_map_by_channel_id in (
        session_channel_title_map_by_session_name.items()
    ):
        for channel_id, title in channel_title_map_by_channel_id.items():
            observed_session_name_title_tuple_list_by_channel_id.setdefault(
                int(channel_id), []
            ).append((session_name, title))

    plan_item_list: list[DuplicateCleanupPlanItem] = []
    database_session = SessionLocal()
    try:
        membership_db = MembershipDAO(database_session)
        for (
            channel_id,
            observed_session_name_title_tuple_list,
        ) in observed_session_name_title_tuple_list_by_channel_id.items():
            if len(observed_session_name_title_tuple_list) <= 1:
                continue

            observed_session_name_list = sorted(
                {
                    _normalize_session_name(session_name)
                    for session_name, _title in observed_session_name_title_tuple_list
                    if _normalize_session_name(session_name)
                }
            )
            if len(observed_session_name_list) <= 1:
                continue

            keep_session_name, keep_reason, assigned_session_name = (
                _choose_keep_session_name(
                    channel_id=int(channel_id),
                    observed_session_name_list=observed_session_name_list,
                    membership_db=membership_db,
                    database_session=database_session,
                )
            )
            title = next(
                (
                    str(title or "").strip()
                    for _session_name, title in observed_session_name_title_tuple_list
                    if str(title or "").strip()
                ),
                "",
            )
            plan_item_list.append(
                DuplicateCleanupPlanItem(
                    channel_id=int(channel_id),
                    title=title,
                    observed_session_name_list=observed_session_name_list,
                    keep_session_name=keep_session_name,
                    keep_reason=keep_reason,
                    assigned_session_name=assigned_session_name,
                )
            )
    finally:
        database_session.close()

    plan_item_list.sort(key=lambda item: (item.title or "", item.channel_id))
    return DuplicateCleanupScanResult(
        plan_item_list=plan_item_list,
        error_text_list=error_text_list,
    )


async def execute_duplicate_cleanup_plan(
    plan_item_list: Sequence[DuplicateCleanupPlanItem],
) -> List[DuplicateCleanupExecutionItem]:
    execution_item_list: list[DuplicateCleanupExecutionItem] = []

    for plan_item in plan_item_list or []:
        database_session = SessionLocal()
        try:
            membership_db = MembershipDAO(database_session)
            membership_db.upsert_membership(
                plan_item.keep_session_name,
                int(plan_item.channel_id),
                "already",
            )

            existing_assignment = assignment_ops.get_channel_session_assignment(
                int(plan_item.channel_id),
                database_session=database_session,
            )
            assignment_ops.upsert_channel_session_assignment(
                channel_id=int(plan_item.channel_id),
                session_name=plan_item.keep_session_name,
                admin_id=(existing_assignment.admin_id if existing_assignment else None),
                assignment_source="admin_bot:dedup_sessions",
                database_session=database_session,
            )
            database_session.commit()
        except Exception:
            database_session.rollback()
            raise
        finally:
            database_session.close()

        cleanup_stats = await enforce_single_session_per_channel(
            channel_id=int(plan_item.channel_id),
            keep_session_name=plan_item.keep_session_name,
            reason="admin_bot:dedup_sessions",
            observed_session_name_list=plan_item.observed_session_name_list,
        )

        present_session_name_list = (
            [plan_item.keep_session_name]
            if int(cleanup_stats.get("errors", 0) or 0) == 0
            else plan_item.observed_session_name_list
        )
        try:
            audit_ops.refresh_channel_subscription_audit_for_channel(
                int(plan_item.channel_id),
                present_session_name_list=present_session_name_list,
                audit_reason="admin_bot:dedup_sessions",
            )
        except Exception:
            log.exception(
                "dedup_sessions.audit_refresh_failed cid=%s keep=%s observed=%s",
                plan_item.channel_id,
                plan_item.keep_session_name,
                plan_item.observed_session_name_list,
            )

        execution_item_list.append(
            DuplicateCleanupExecutionItem(
                channel_id=plan_item.channel_id,
                title=plan_item.title,
                keep_session_name=plan_item.keep_session_name,
                keep_reason=plan_item.keep_reason,
                observed_session_name_list=plan_item.observed_session_name_list,
                cleanup_stats=cleanup_stats,
            )
        )

    return execution_item_list


def render_keep_reason(keep_reason: str) -> str:
    mapping = {
        "assignment": "assignment",
        "membership_fallback": "membership",
        "sorted_fallback": "fallback",
    }
    return mapping.get(str(keep_reason or "").strip(), "fallback")


def session_display_list(session_name_list: Sequence[str]) -> str:
    normalized_session_name_list = [
        _normalize_session_name(session_name)
        for session_name in (session_name_list or [])
        if _normalize_session_name(session_name)
    ]
    return ", ".join(
        account_pool.session_display(session_name)
        for session_name in normalized_session_name_list
    )
