from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import case, func, select

from app.admin_bot.db import models as models
from app.db.session import SessionLocal
from app.utils.link_parser import sanitize_link


def _normalize_administrator_name(administrator_name: str | None) -> str:
    normalized_administrator_name = " ".join(str(administrator_name or "").split()).strip()
    if not normalized_administrator_name or normalized_administrator_name == "—":
        return ""
    return normalized_administrator_name


def _normalize_name_for_similarity(administrator_name: str | None) -> str:
    normalized_administrator_name = _normalize_administrator_name(administrator_name)
    if not normalized_administrator_name:
        return ""
    normalized_administrator_name = normalized_administrator_name.casefold().replace("ё", "е")
    allowed_character_list: list[str] = []
    for character_value in normalized_administrator_name:
        if character_value.isalnum() or character_value.isspace():
            allowed_character_list.append(character_value)
    return " ".join("".join(allowed_character_list).split())


def _damerau_levenshtein_distance_with_cutoff(
    source_text: str,
    target_text: str,
    maximum_distance: int,
) -> int:
    if source_text == target_text:
        return 0

    source_text_length = len(source_text)
    target_text_length = len(target_text)
    if source_text_length == 0:
        return target_text_length
    if target_text_length == 0:
        return source_text_length
    if abs(source_text_length - target_text_length) > maximum_distance:
        return maximum_distance + 1

    distance_matrix: list[list[int]] = [
        [0] * (target_text_length + 1)
        for _ in range(source_text_length + 1)
    ]
    for source_index in range(source_text_length + 1):
        distance_matrix[source_index][0] = source_index
    for target_index in range(target_text_length + 1):
        distance_matrix[0][target_index] = target_index

    for source_index in range(1, source_text_length + 1):
        current_row_minimum_distance = maximum_distance + 1
        for target_index in range(1, target_text_length + 1):
            substitution_cost = 0 if source_text[source_index - 1] == target_text[target_index - 1] else 1
            deletion_distance = distance_matrix[source_index - 1][target_index] + 1
            insertion_distance = distance_matrix[source_index][target_index - 1] + 1
            substitution_distance = (
                distance_matrix[source_index - 1][target_index - 1] + substitution_cost
            )
            current_distance = min(
                deletion_distance,
                insertion_distance,
                substitution_distance,
            )
            if (
                source_index > 1
                and target_index > 1
                and source_text[source_index - 1] == target_text[target_index - 2]
                and source_text[source_index - 2] == target_text[target_index - 1]
            ):
                current_distance = min(
                    current_distance,
                    distance_matrix[source_index - 2][target_index - 2] + 1,
                )

            distance_matrix[source_index][target_index] = current_distance
            if current_distance < current_row_minimum_distance:
                current_row_minimum_distance = current_distance
        if current_row_minimum_distance > maximum_distance:
            return maximum_distance + 1

    return distance_matrix[source_text_length][target_text_length]


def _find_admin_identifier_by_similarity(
    database_session,
    normalized_administrator_name_candidate: str,
    normalized_username_candidate: str,
) -> Optional[int]:
    comparison_candidate_list: list[str] = []
    if normalized_administrator_name_candidate:
        comparison_candidate_list.append(normalized_administrator_name_candidate)
    if (
        normalized_username_candidate
        and normalized_username_candidate not in comparison_candidate_list
    ):
        comparison_candidate_list.append(normalized_username_candidate)
    if not comparison_candidate_list:
        return None

    administrator_identity_rows = database_session.execute(
        select(models.Admin.id, models.Admin.username, models.Admin.display).order_by(
            models.Admin.id.asc()
        )
    ).all()

    best_match_admin_identifier: int | None = None
    best_match_distance: int | None = None
    best_match_is_ambiguous = False
    maximum_allowed_distance = 2

    for administrator_identity_row in administrator_identity_rows:
        normalized_username_from_database = _normalize_name_for_similarity(
            str(administrator_identity_row.username or "").lstrip("@")
        )
        normalized_display_from_database = _normalize_name_for_similarity(
            administrator_identity_row.display
        )

        administrator_name_variant_list: list[str] = []
        if normalized_username_from_database:
            administrator_name_variant_list.append(normalized_username_from_database)
        if (
            normalized_display_from_database
            and normalized_display_from_database not in administrator_name_variant_list
        ):
            administrator_name_variant_list.append(normalized_display_from_database)
            for display_name_part in normalized_display_from_database.split():
                if (
                    len(display_name_part) >= 3
                    and display_name_part not in administrator_name_variant_list
                ):
                    administrator_name_variant_list.append(display_name_part)

        smallest_distance_for_admin: int | None = None
        for comparison_candidate in comparison_candidate_list:
            for administrator_name_variant in administrator_name_variant_list:
                calculated_distance = _damerau_levenshtein_distance_with_cutoff(
                    source_text=comparison_candidate,
                    target_text=administrator_name_variant,
                    maximum_distance=maximum_allowed_distance,
                )
                if calculated_distance > maximum_allowed_distance:
                    continue
                if (
                    smallest_distance_for_admin is None
                    or calculated_distance < smallest_distance_for_admin
                ):
                    smallest_distance_for_admin = calculated_distance

        if smallest_distance_for_admin is None:
            continue
        if (
            best_match_distance is None
            or smallest_distance_for_admin < best_match_distance
        ):
            best_match_admin_identifier = int(administrator_identity_row.id)
            best_match_distance = smallest_distance_for_admin
            best_match_is_ambiguous = False
            continue
        if smallest_distance_for_admin == best_match_distance:
            best_match_is_ambiguous = True

    if best_match_admin_identifier is None:
        return None
    if (
        best_match_is_ambiguous
        and best_match_distance is not None
        and best_match_distance > 1
    ):
        return None
    return best_match_admin_identifier


def resolve_admin_identifier_by_administrator_name(
    administrator_name: str | None,
) -> Optional[int]:
    normalized_administrator_name = _normalize_administrator_name(administrator_name)
    if not normalized_administrator_name:
        return None

    normalized_username_candidate = normalized_administrator_name.lstrip("@").strip()
    normalized_administrator_name_for_similarity = _normalize_name_for_similarity(
        normalized_administrator_name
    )
    normalized_username_candidate_for_similarity = _normalize_name_for_similarity(
        normalized_username_candidate
    )

    database_session = SessionLocal()
    try:
        administrator_identifier_from_exact_display = database_session.execute(
            select(models.Admin.id)
            .where(
                func.lower(func.trim(models.Admin.display))
                == func.lower(normalized_administrator_name)
            )
            .order_by(models.Admin.id.asc())
            .limit(1)
        ).scalar_one_or_none()

        if administrator_identifier_from_exact_display is not None:
            return int(administrator_identifier_from_exact_display)

        if normalized_username_candidate:
            administrator_identifier_from_exact_username = database_session.execute(
                select(models.Admin.id)
                .where(
                    func.lower(func.trim(models.Admin.username)).in_(
                        [
                            normalized_username_candidate.casefold(),
                            f"@{normalized_username_candidate.casefold()}",
                        ]
                    )
                )
                .order_by(models.Admin.id.asc())
                .limit(1)
            ).scalar_one_or_none()
            if administrator_identifier_from_exact_username is not None:
                return int(administrator_identifier_from_exact_username)

        administrator_identifier_by_similarity = _find_admin_identifier_by_similarity(
            database_session=database_session,
            normalized_administrator_name_candidate=normalized_administrator_name_for_similarity,
            normalized_username_candidate=normalized_username_candidate_for_similarity,
        )
        if administrator_identifier_by_similarity is not None:
            return int(administrator_identifier_by_similarity)

        return None
    finally:
        database_session.close()


def list_network_selection_records_for_admin(
    admin_identifier: int,
) -> List[Dict[str, Any]]:
    database_session = SessionLocal()
    try:
        network_selection_rows = database_session.execute(
            select(models.Network.id, models.Network.name)
            .where(models.Network.admin_id == int(admin_identifier))
            .order_by(models.Network.name.asc(), models.Network.id.asc())
        ).all()
        network_selection_record_list: List[Dict[str, Any]] = []
        for network_selection_row in network_selection_rows:
            network_identifier = int(network_selection_row.id)
            network_name = str(network_selection_row.name or "").strip()
            if not network_name:
                network_name = f"Сітка {network_identifier}"
            network_selection_record_list.append(
                {
                    "network_id": network_identifier,
                    "network_name": network_name,
                }
            )
        return network_selection_record_list
    finally:
        database_session.close()


def get_network_selection_record_for_admin(
    admin_identifier: int,
    network_identifier: int,
) -> Optional[Dict[str, Any]]:
    database_session = SessionLocal()
    try:
        network_selection_row = database_session.execute(
            select(models.Network.id, models.Network.name)
            .where(
                models.Network.admin_id == int(admin_identifier),
                models.Network.id == int(network_identifier),
            )
            .limit(1)
        ).first()
        if network_selection_row is None:
            return None
        resolved_network_identifier = int(network_selection_row.id)
        resolved_network_name = str(network_selection_row.name or "").strip()
        if not resolved_network_name:
            resolved_network_name = f"Сітка {resolved_network_identifier}"
        return {
            "network_id": resolved_network_identifier,
            "network_name": resolved_network_name,
        }
    finally:
        database_session.close()


def list_network_channel_subscription_audit_record_list(
    network_identifier: int,
) -> List[Dict[str, Any]]:
    database_session = SessionLocal()
    try:
        invite_hash_subquery = (
            select(models.InviteMap.invite_hash)
            .where(models.InviteMap.channel_id == models.NetworkChannel.channel_id)
            .limit(1)
            .scalar_subquery()
        )
        raw_url_subquery = (
            select(models.Link.raw_url)
            .where(
                models.Link.channel_id == models.NetworkChannel.channel_id,
                models.Link.raw_url.isnot(None),
            )
            .order_by(models.Link.id.desc())
            .limit(1)
            .scalar_subquery()
        )

        network_channel_row_list = database_session.execute(
            select(
                models.NetworkChannel.id,
                models.NetworkChannel.channel_id,
                models.NetworkChannel.sort_order,
                models.Channel.title,
                models.Channel.username,
                models.ChannelSubscriptionAudit.audit_status,
                models.ChannelSubscriptionAudit.checked_at,
                models.ChannelSubscriptionAudit.missing_detected_at,
                invite_hash_subquery.label("invite_hash"),
                raw_url_subquery.label("raw_url"),
            )
            .select_from(models.NetworkChannel)
            .outerjoin(
                models.Channel,
                models.Channel.channel_id == models.NetworkChannel.channel_id,
            )
            .outerjoin(
                models.ChannelSubscriptionAudit,
                models.ChannelSubscriptionAudit.channel_id == models.NetworkChannel.channel_id,
            )
            .where(models.NetworkChannel.network_id == int(network_identifier))
            .order_by(
                case(
                    (models.NetworkChannel.sort_order.is_(None), 1),
                    else_=0,
                ),
                models.NetworkChannel.sort_order.asc(),
                models.NetworkChannel.id.asc(),
            )
        ).all()

        network_channel_subscription_audit_record_list: List[Dict[str, Any]] = []
        for network_channel_row in network_channel_row_list:
            channel_identifier = int(network_channel_row.channel_id)
            channel_title = str(network_channel_row.title or "").strip()
            channel_username = str(network_channel_row.username or "").strip()
            invite_hash = str(network_channel_row.invite_hash or "").strip()
            raw_url = str(network_channel_row.raw_url or "").strip()

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

            network_channel_subscription_audit_record_list.append(
                {
                    "network_channel_relation_id": int(network_channel_row.id),
                    "channel_id": channel_identifier,
                    "channel_label": channel_label,
                    "channel_url": channel_url,
                    "audit_status": str(network_channel_row.audit_status or ""),
                    "checked_at": int(network_channel_row.checked_at or 0),
                    "missing_detected_at": int(network_channel_row.missing_detected_at)
                    if network_channel_row.missing_detected_at is not None
                    else None,
                }
            )

        return network_channel_subscription_audit_record_list
    finally:
        database_session.close()
