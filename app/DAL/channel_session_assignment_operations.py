from __future__ import annotations

import time
from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.DAL.channel_session_assignment_models import (
    ChannelSessionAssignmentUpsertModel,
    ChannelSessionAssignmentViewModel,
)
from app.admin_bot.db import models as db_models
from app.db.session import SessionLocal


def _now_ts() -> int:
    return int(time.time())


def _close_if_needed(database_session: Session, should_close_session: bool) -> None:
    if should_close_session:
        database_session.close()


def get_channel_session_assignment(
    channel_id: int,
    *,
    database_session: Session | None = None,
) -> ChannelSessionAssignmentViewModel | None:
    should_close_session = database_session is None
    database_session = database_session or SessionLocal()
    try:
        assignment_row = (
            database_session.query(db_models.ChannelSessionAssignment)
            .filter(db_models.ChannelSessionAssignment.channel_id == int(channel_id))
            .one_or_none()
        )
        if assignment_row is None:
            return None
        return ChannelSessionAssignmentViewModel.model_validate(assignment_row)
    finally:
        _close_if_needed(database_session, should_close_session)


def get_assigned_session_for_channel(
    channel_id: int,
    *,
    database_session: Session | None = None,
) -> Optional[str]:
    assignment_view_model = get_channel_session_assignment(
        channel_id,
        database_session=database_session,
    )
    if assignment_view_model is None:
        return None
    return assignment_view_model.session_name


def upsert_channel_session_assignment(
    *,
    channel_id: int,
    session_name: str,
    admin_id: int | None = None,
    assignment_source: str | None = None,
    mark_session_ok: bool = True,
    database_session: Session | None = None,
) -> ChannelSessionAssignmentViewModel:
    normalized_assignment_payload = ChannelSessionAssignmentUpsertModel(
        channel_id=channel_id,
        session_name=session_name,
        admin_id=admin_id,
        assignment_source=assignment_source,
    )
    should_close_session = database_session is None
    database_session = database_session or SessionLocal()
    current_timestamp = _now_ts()
    try:
        assignment_row = (
            database_session.query(db_models.ChannelSessionAssignment)
            .filter(
                db_models.ChannelSessionAssignment.channel_id
                == normalized_assignment_payload.channel_id
            )
            .one_or_none()
        )
        if assignment_row is None:
            assignment_row = db_models.ChannelSessionAssignment(
                channel_id=normalized_assignment_payload.channel_id,
                session_name=normalized_assignment_payload.session_name,
                admin_id=normalized_assignment_payload.admin_id,
                assigned_at=current_timestamp,
                updated_at=current_timestamp,
                last_ok_at=current_timestamp if mark_session_ok else None,
                last_repair_at=None,
                assignment_source=normalized_assignment_payload.assignment_source,
            )
            database_session.add(assignment_row)
        else:
            assignment_row.session_name = normalized_assignment_payload.session_name
            assignment_row.admin_id = normalized_assignment_payload.admin_id
            assignment_row.assignment_source = (
                normalized_assignment_payload.assignment_source
            )
            assignment_row.updated_at = current_timestamp
            if mark_session_ok:
                assignment_row.last_ok_at = current_timestamp

        if should_close_session:
            database_session.commit()
            database_session.refresh(assignment_row)
        else:
            database_session.flush()

        return ChannelSessionAssignmentViewModel.model_validate(assignment_row)
    except Exception:
        if should_close_session:
            database_session.rollback()
        raise
    finally:
        _close_if_needed(database_session, should_close_session)


def touch_channel_session_assignment_repaired(
    channel_id: int,
    *,
    database_session: Session | None = None,
) -> ChannelSessionAssignmentViewModel | None:
    should_close_session = database_session is None
    database_session = database_session or SessionLocal()
    current_timestamp = _now_ts()
    try:
        assignment_row = (
            database_session.query(db_models.ChannelSessionAssignment)
            .filter(db_models.ChannelSessionAssignment.channel_id == int(channel_id))
            .one_or_none()
        )
        if assignment_row is None:
            return None

        assignment_row.updated_at = current_timestamp
        assignment_row.last_repair_at = current_timestamp

        if should_close_session:
            database_session.commit()
            database_session.refresh(assignment_row)
        else:
            database_session.flush()

        return ChannelSessionAssignmentViewModel.model_validate(assignment_row)
    except Exception:
        if should_close_session:
            database_session.rollback()
        raise
    finally:
        _close_if_needed(database_session, should_close_session)


def delete_channel_session_assignments_by_channels(
    channel_identifier_list: Sequence[int],
    *,
    database_session: Session | None = None,
) -> int:
    normalized_channel_identifier_list = [
        int(channel_identifier)
        for channel_identifier in (channel_identifier_list or [])
        if channel_identifier is not None
    ]
    if not normalized_channel_identifier_list:
        return 0

    should_close_session = database_session is None
    database_session = database_session or SessionLocal()
    try:
        deleted_row_count = (
            database_session.query(db_models.ChannelSessionAssignment)
            .filter(
                db_models.ChannelSessionAssignment.channel_id.in_(
                    normalized_channel_identifier_list
                )
            )
            .delete(synchronize_session=False)
            or 0
        )
        if should_close_session:
            database_session.commit()
        else:
            database_session.flush()
        return int(deleted_row_count)
    except Exception:
        if should_close_session:
            database_session.rollback()
        raise
    finally:
        _close_if_needed(database_session, should_close_session)
