from __future__ import annotations

import argparse
from collections import defaultdict
from typing import Iterable
import os
import sys
from pathlib import Path

from sqlalchemy import select

BASE_DIR = Path(__file__).resolve().parents[1]
os.chdir(BASE_DIR)
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.DAL.channel_session_assignment_operations import (
    upsert_channel_session_assignment,
)
from app.admin_bot.db import models as m
from app.admin_bot.db.session import SessionLocal

FINAL_PRIORITY = {
    "joined": 1,
    "already": 1,
    "requested": 2,
    "invalid": 3,
    "blocked": 4,
    "too_many": 5,
}


def _normalize_session_name(session_name: str | None) -> str | None:
    normalized_session_name = str(session_name or "").strip()
    if not normalized_session_name:
        return None
    if normalized_session_name.endswith(".session"):
        normalized_session_name = normalized_session_name[:-8].strip()
    return normalized_session_name or None


def _status_priority(status_value: str | None) -> int:
    normalized_status_value = str(status_value or "").strip().lower()
    return FINAL_PRIORITY.get(normalized_status_value, 100)


def _build_admin_id_by_channel_identifier(database_session) -> dict[int, int | None]:
    admin_id_set_by_channel_identifier: dict[int, set[int]] = defaultdict(set)

    for channel_identifier, admin_identifier in database_session.execute(
        select(m.AdminChannel.channel_id, m.AdminChannel.admin_id)
    ).all():
        if channel_identifier is None or admin_identifier is None:
            continue
        admin_id_set_by_channel_identifier[int(channel_identifier)].add(int(admin_identifier))

    for channel_identifier, admin_identifier in database_session.execute(
        select(m.NetworkChannel.channel_id, m.Network.admin_id)
        .join(m.Network, m.Network.id == m.NetworkChannel.network_id)
        .where(m.Network.admin_id.isnot(None))
    ).all():
        if channel_identifier is None or admin_identifier is None:
            continue
        admin_id_set_by_channel_identifier[int(channel_identifier)].add(int(admin_identifier))

    admin_id_by_channel_identifier: dict[int, int | None] = {}
    for channel_identifier, admin_id_set in admin_id_set_by_channel_identifier.items():
        if len(admin_id_set) == 1:
            admin_id_by_channel_identifier[channel_identifier] = next(iter(admin_id_set))
        else:
            admin_id_by_channel_identifier[channel_identifier] = None
    return admin_id_by_channel_identifier


def _iter_selected_channel_identifiers(
    membership_rows: Iterable[m.Membership],
    target_channel_identifier_set: set[int] | None,
) -> dict[int, list[m.Membership]]:
    membership_rows_by_channel_identifier: dict[int, list[m.Membership]] = defaultdict(list)
    for membership_row in membership_rows:
        if membership_row.channel_id is None:
            continue
        channel_identifier = int(membership_row.channel_id)
        if target_channel_identifier_set and channel_identifier not in target_channel_identifier_set:
            continue
        membership_rows_by_channel_identifier[channel_identifier].append(membership_row)
    return membership_rows_by_channel_identifier


def _pick_best_membership_row(membership_row_list: list[m.Membership]) -> m.Membership | None:
    normalized_membership_rows: list[m.Membership] = []
    best_membership_row_by_session_name: dict[str, m.Membership] = {}
    for membership_row in membership_row_list:
        normalized_session_name = _normalize_session_name(membership_row.account)
        if not normalized_session_name:
            continue
        existing_membership_row = best_membership_row_by_session_name.get(normalized_session_name)
        if existing_membership_row is None:
            best_membership_row_by_session_name[normalized_session_name] = membership_row
            continue
        candidate_sort_key = (_status_priority(membership_row.status), -(int(membership_row.ts or 0)))
        existing_sort_key = (_status_priority(existing_membership_row.status), -(int(existing_membership_row.ts or 0)))
        if candidate_sort_key < existing_sort_key:
            best_membership_row_by_session_name[normalized_session_name] = membership_row

    normalized_membership_rows.extend(best_membership_row_by_session_name.values())
    if not normalized_membership_rows:
        return None

    normalized_membership_rows.sort(
        key=lambda membership_row: (
            _status_priority(membership_row.status),
            -(int(membership_row.ts or 0)),
            _normalize_session_name(membership_row.account) or "",
        )
    )
    return normalized_membership_rows[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill channel_session_assignments from membership state")
    parser.add_argument("--channel-id", dest="channel_ids", action="append", type=int, default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    target_channel_identifier_set = {int(channel_id) for channel_id in (args.channel_ids or [])}
    database_session = SessionLocal()
    try:
        membership_row_list = (
            database_session.execute(select(m.Membership).order_by(m.Membership.channel_id.asc(), m.Membership.ts.desc()))
            .scalars()
            .all()
        )
        membership_rows_by_channel_identifier = _iter_selected_channel_identifiers(
            membership_row_list,
            target_channel_identifier_set=target_channel_identifier_set or None,
        )
        existing_assignment_channel_identifier_set = set(
            int(channel_identifier)
            for channel_identifier in database_session.execute(
                select(m.ChannelSessionAssignment.channel_id)
            ).scalars().all()
            if channel_identifier is not None
        )
        admin_id_by_channel_identifier = _build_admin_id_by_channel_identifier(database_session)
    finally:
        database_session.close()

    planned = 0
    updated = 0
    skipped_existing = 0
    skipped_no_membership = 0
    skipped_no_session = 0

    processed_channel_count = 0
    for channel_identifier in sorted(membership_rows_by_channel_identifier.keys()):
        if args.limit and processed_channel_count >= args.limit:
            break
        processed_channel_count += 1

        if channel_identifier in existing_assignment_channel_identifier_set and not args.force:
            skipped_existing += 1
            continue

        best_membership_row = _pick_best_membership_row(
            membership_rows_by_channel_identifier[channel_identifier]
        )
        if best_membership_row is None:
            skipped_no_membership += 1
            continue

        normalized_session_name = _normalize_session_name(best_membership_row.account)
        if not normalized_session_name:
            skipped_no_session += 1
            continue

        planned += 1
        admin_identifier = admin_id_by_channel_identifier.get(channel_identifier)
        print(
            f"[plan] channel_id={channel_identifier} session={normalized_session_name} "
            f"status={best_membership_row.status} ts={best_membership_row.ts} admin_id={admin_identifier}"
        )
        if args.dry_run:
            continue

        upsert_channel_session_assignment(
            channel_id=channel_identifier,
            session_name=normalized_session_name,
            admin_id=admin_identifier,
            assignment_source="backfill_membership",
        )
        updated += 1

    print("----- summary -----")
    print(f"planned={planned}")
    print(f"updated={updated}")
    print(f"skipped_existing={skipped_existing}")
    print(f"skipped_no_membership={skipped_no_membership}")
    print(f"skipped_no_session={skipped_no_session}")
    print(f"dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
