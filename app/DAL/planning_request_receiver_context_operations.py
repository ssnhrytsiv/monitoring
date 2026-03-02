from __future__ import annotations

import json
import logging
import time

from sqlalchemy import select

from app.admin_bot.db import models as shared_models
from app.db.session import SessionLocal
from app.planning_bot.models import (
    PlanningRequestReceiverContextCreateModel,
    PlanningRequestReceiverContextUpdateModel,
    PlanningRequestReceiverContextViewModel,
)

log = logging.getLogger("dal.planning_request_receiver_contexts")


def _now_epoch_seconds() -> int:
    return int(time.time())


def _serialize_order_links_to_json(order_links_values: list[dict[str, object]]) -> str:
    return json.dumps(order_links_values, ensure_ascii=False)


def _receiver_context_row_to_validation_payload(
    planning_request_receiver_context_row: shared_models.PlanningRequestReceiverContext,
) -> dict[str, object]:
    receiver_context_payload = {
        database_column.name: getattr(planning_request_receiver_context_row, database_column.name)
        for database_column in shared_models.PlanningRequestReceiverContext.__table__.columns
    }
    receiver_context_payload["order_links"] = receiver_context_payload.pop("order_links_json", "[]")
    return receiver_context_payload


def _to_view_model(
    planning_request_receiver_context_row: shared_models.PlanningRequestReceiverContext,
) -> PlanningRequestReceiverContextViewModel:
    receiver_context_payload = _receiver_context_row_to_validation_payload(
        planning_request_receiver_context_row
    )
    return PlanningRequestReceiverContextViewModel.model_validate(receiver_context_payload)


def create_or_update_planning_request_receiver_context(
    planning_request_receiver_context_create_model: PlanningRequestReceiverContextCreateModel,
) -> PlanningRequestReceiverContextViewModel:
    database_session = SessionLocal()
    try:
        receiver_context_values = planning_request_receiver_context_create_model.model_dump(mode="json")
        order_links_values = receiver_context_values.pop("order_links", [])
        receiver_context_values["order_links_json"] = _serialize_order_links_to_json(order_links_values)
        receiver_context_values["is_added_to_schedule"] = (
            1 if receiver_context_values.get("is_added_to_schedule") else 0
        )

        existing_receiver_context_row = database_session.execute(
            select(shared_models.PlanningRequestReceiverContext).where(
                shared_models.PlanningRequestReceiverContext.receiver_chat_id
                == int(planning_request_receiver_context_create_model.receiver_chat_id),
                shared_models.PlanningRequestReceiverContext.order_message_id
                == int(planning_request_receiver_context_create_model.order_message_id),
            )
        ).scalar_one_or_none()

        current_epoch_seconds = _now_epoch_seconds()
        if existing_receiver_context_row is None:
            receiver_context_values["created_at"] = current_epoch_seconds
            receiver_context_values["updated_at"] = current_epoch_seconds
            planning_request_receiver_context_row = shared_models.PlanningRequestReceiverContext(
                **receiver_context_values
            )
            database_session.add(planning_request_receiver_context_row)
        else:
            for field_name, field_value in receiver_context_values.items():
                setattr(existing_receiver_context_row, field_name, field_value)
            existing_receiver_context_row.updated_at = current_epoch_seconds
            planning_request_receiver_context_row = existing_receiver_context_row

        database_session.commit()
        database_session.refresh(planning_request_receiver_context_row)
        return _to_view_model(planning_request_receiver_context_row)
    except Exception:
        database_session.rollback()
        log.exception("create_or_update_planning_request_receiver_context failed")
        raise
    finally:
        database_session.close()


def get_planning_request_receiver_context_by_message(
    receiver_chat_id: int,
    order_message_id: int,
) -> PlanningRequestReceiverContextViewModel | None:
    database_session = SessionLocal()
    try:
        planning_request_receiver_context_row = database_session.execute(
            select(shared_models.PlanningRequestReceiverContext).where(
                shared_models.PlanningRequestReceiverContext.receiver_chat_id == int(receiver_chat_id),
                shared_models.PlanningRequestReceiverContext.order_message_id == int(order_message_id),
            )
        ).scalar_one_or_none()
        if planning_request_receiver_context_row is None:
            return None
        return _to_view_model(planning_request_receiver_context_row)
    finally:
        database_session.close()


def list_planning_request_receiver_contexts_by_planning_request_id(
    planning_request_id: int,
) -> list[PlanningRequestReceiverContextViewModel]:
    database_session = SessionLocal()
    try:
        planning_request_receiver_context_rows = list(
            database_session.execute(
                select(shared_models.PlanningRequestReceiverContext).where(
                    shared_models.PlanningRequestReceiverContext.planning_request_id
                    == int(planning_request_id)
                )
            ).scalars().all()
        )
        return [
            _to_view_model(planning_request_receiver_context_row)
            for planning_request_receiver_context_row in planning_request_receiver_context_rows
        ]
    finally:
        database_session.close()


def get_latest_planning_request_receiver_context_by_receiver_and_administrator(
    receiver_chat_id: int,
    administrator_name: str,
) -> PlanningRequestReceiverContextViewModel | None:
    database_session = SessionLocal()
    try:
        planning_request_receiver_context_row = database_session.execute(
            select(shared_models.PlanningRequestReceiverContext)
            .where(
                shared_models.PlanningRequestReceiverContext.receiver_chat_id == int(receiver_chat_id),
                shared_models.PlanningRequestReceiverContext.administrator_name == str(administrator_name),
            )
            .order_by(
                shared_models.PlanningRequestReceiverContext.updated_at.desc(),
                shared_models.PlanningRequestReceiverContext.id.desc(),
            )
            .limit(1)
        ).scalar_one_or_none()
        if planning_request_receiver_context_row is None:
            return None
        return _to_view_model(planning_request_receiver_context_row)
    finally:
        database_session.close()


def list_planning_request_receiver_contexts_by_receiver_chat_id(
    receiver_chat_id: int,
    limit: int = 100,
) -> list[PlanningRequestReceiverContextViewModel]:
    database_session = SessionLocal()
    try:
        safe_limit = max(1, min(int(limit), 1000))
        planning_request_receiver_context_rows = list(
            database_session.execute(
                select(shared_models.PlanningRequestReceiverContext)
                .where(shared_models.PlanningRequestReceiverContext.receiver_chat_id == int(receiver_chat_id))
                .order_by(
                    shared_models.PlanningRequestReceiverContext.updated_at.desc(),
                    shared_models.PlanningRequestReceiverContext.id.desc(),
                )
                .limit(safe_limit)
            ).scalars().all()
        )
        return [
            _to_view_model(planning_request_receiver_context_row)
            for planning_request_receiver_context_row in planning_request_receiver_context_rows
        ]
    finally:
        database_session.close()


def update_planning_request_receiver_context_by_message(
    receiver_chat_id: int,
    order_message_id: int,
    planning_request_receiver_context_update_model: PlanningRequestReceiverContextUpdateModel,
) -> PlanningRequestReceiverContextViewModel | None:
    database_session = SessionLocal()
    try:
        planning_request_receiver_context_row = database_session.execute(
            select(shared_models.PlanningRequestReceiverContext).where(
                shared_models.PlanningRequestReceiverContext.receiver_chat_id == int(receiver_chat_id),
                shared_models.PlanningRequestReceiverContext.order_message_id == int(order_message_id),
            )
        ).scalar_one_or_none()
        if planning_request_receiver_context_row is None:
            return None

        receiver_context_update_values = planning_request_receiver_context_update_model.model_dump(
            exclude_unset=True,
            mode="json",
        )
        if not receiver_context_update_values:
            return _to_view_model(planning_request_receiver_context_row)

        if "order_links" in receiver_context_update_values:
            order_links_values = receiver_context_update_values.pop("order_links")
            receiver_context_update_values["order_links_json"] = _serialize_order_links_to_json(
                order_links_values or []
            )
        if "is_added_to_schedule" in receiver_context_update_values:
            receiver_context_update_values["is_added_to_schedule"] = (
                1 if receiver_context_update_values["is_added_to_schedule"] else 0
            )

        for field_name, field_value in receiver_context_update_values.items():
            setattr(planning_request_receiver_context_row, field_name, field_value)
        planning_request_receiver_context_row.updated_at = _now_epoch_seconds()

        database_session.commit()
        database_session.refresh(planning_request_receiver_context_row)
        return _to_view_model(planning_request_receiver_context_row)
    except Exception:
        database_session.rollback()
        log.exception(
            "update_planning_request_receiver_context_by_message failed: receiver_chat_id=%s order_message_id=%s",
            receiver_chat_id,
            order_message_id,
        )
        raise
    finally:
        database_session.close()


def delete_planning_request_receiver_context_by_message(
    receiver_chat_id: int,
    order_message_id: int,
) -> bool:
    database_session = SessionLocal()
    try:
        planning_request_receiver_context_row = database_session.execute(
            select(shared_models.PlanningRequestReceiverContext).where(
                shared_models.PlanningRequestReceiverContext.receiver_chat_id == int(receiver_chat_id),
                shared_models.PlanningRequestReceiverContext.order_message_id == int(order_message_id),
            )
        ).scalar_one_or_none()
        if planning_request_receiver_context_row is None:
            return False

        database_session.delete(planning_request_receiver_context_row)
        database_session.commit()
        return True
    except Exception:
        database_session.rollback()
        log.exception(
            "delete_planning_request_receiver_context_by_message failed: receiver_chat_id=%s order_message_id=%s",
            receiver_chat_id,
            order_message_id,
        )
        raise
    finally:
        database_session.close()


def delete_planning_request_receiver_contexts_by_planning_request_id(
    planning_request_id: int,
) -> int:
    database_session = SessionLocal()
    try:
        planning_request_receiver_context_rows = list(
            database_session.execute(
                select(shared_models.PlanningRequestReceiverContext).where(
                    shared_models.PlanningRequestReceiverContext.planning_request_id
                    == int(planning_request_id)
                )
            ).scalars().all()
        )
        if not planning_request_receiver_context_rows:
            return 0

        deleted_rows_count = 0
        for planning_request_receiver_context_row in planning_request_receiver_context_rows:
            database_session.delete(planning_request_receiver_context_row)
            deleted_rows_count += 1
        database_session.commit()
        return deleted_rows_count
    except Exception:
        database_session.rollback()
        log.exception(
            "delete_planning_request_receiver_contexts_by_planning_request_id failed: planning_request_id=%s",
            planning_request_id,
        )
        raise
    finally:
        database_session.close()
