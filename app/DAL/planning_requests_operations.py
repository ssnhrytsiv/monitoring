from __future__ import annotations

import json
import logging
import time

from sqlalchemy import select

from app.admin_bot.db import models as shared_models
from app.db.session import SessionLocal
from app.planning_bot.models import (
    PlanningRequestCreateModel,
    PlanningRequestUpdateModel,
    PlanningRequestViewModel,
)

log = logging.getLogger("dal.planning_requests")


def _now_epoch_seconds() -> int:
    return int(time.time())


def _serialize_links_to_json(links_values: list[str]) -> str:
    return json.dumps(links_values, ensure_ascii=False)


def _planning_request_row_to_validation_payload(
    planning_request_row: shared_models.PlanningRequest,
) -> dict[str, object]:
    planning_request_payload = {
        database_column.name: getattr(planning_request_row, database_column.name)
        for database_column in shared_models.PlanningRequest.__table__.columns
    }
    planning_request_payload["links"] = planning_request_payload.pop("links_json", "[]")
    return planning_request_payload


def _to_view_model(
    planning_request_row: shared_models.PlanningRequest,
) -> PlanningRequestViewModel:
    planning_request_payload = _planning_request_row_to_validation_payload(planning_request_row)
    return PlanningRequestViewModel.model_validate(planning_request_payload)


def create_planning_request(
    planning_request_create_model: PlanningRequestCreateModel,
) -> PlanningRequestViewModel:
    database_session = SessionLocal()
    try:
        current_epoch_seconds = _now_epoch_seconds()
        planning_request_database_values = planning_request_create_model.model_dump(mode="json")
        links_values = planning_request_database_values.pop("links", [])
        planning_request_database_values["links_json"] = _serialize_links_to_json(links_values)
        planning_request_database_values["created_at"] = current_epoch_seconds
        planning_request_database_values["updated_at"] = current_epoch_seconds

        planning_request_row = shared_models.PlanningRequest(**planning_request_database_values)
        database_session.add(planning_request_row)
        database_session.commit()
        database_session.refresh(planning_request_row)
        return _to_view_model(planning_request_row)
    except Exception:
        database_session.rollback()
        log.exception("create_planning_request failed")
        raise
    finally:
        database_session.close()


def get_planning_request_by_id(
    planning_request_id: int,
) -> PlanningRequestViewModel | None:
    database_session = SessionLocal()
    try:
        planning_request_row = database_session.get(
            shared_models.PlanningRequest,
            int(planning_request_id),
        )
        if planning_request_row is None:
            return None
        return _to_view_model(planning_request_row)
    finally:
        database_session.close()


def list_planning_requests(
    limit: int = 100,
    offset: int = 0,
) -> list[PlanningRequestViewModel]:
    database_session = SessionLocal()
    try:
        safe_limit = max(1, min(int(limit), 1000))
        safe_offset = max(0, int(offset))
        planning_request_rows = list(
            database_session.execute(
                select(shared_models.PlanningRequest)
                .order_by(
                    shared_models.PlanningRequest.created_at.desc(),
                    shared_models.PlanningRequest.id.desc(),
                )
                .limit(safe_limit)
                .offset(safe_offset)
            ).scalars().all()
        )
        return [_to_view_model(planning_request_row) for planning_request_row in planning_request_rows]
    finally:
        database_session.close()


def update_planning_request(
    planning_request_id: int,
    planning_request_update_model: PlanningRequestUpdateModel,
) -> PlanningRequestViewModel | None:
    database_session = SessionLocal()
    try:
        planning_request_row = database_session.get(
            shared_models.PlanningRequest,
            int(planning_request_id),
        )
        if planning_request_row is None:
            return None

        planning_request_update_values = planning_request_update_model.model_dump(
            exclude_unset=True,
            mode="json",
        )
        if not planning_request_update_values:
            return _to_view_model(planning_request_row)

        if "links" in planning_request_update_values:
            links_values = planning_request_update_values.pop("links")
            planning_request_update_values["links_json"] = _serialize_links_to_json(links_values or [])

        for field_name, field_value in planning_request_update_values.items():
            setattr(planning_request_row, field_name, field_value)

        planning_request_row.updated_at = _now_epoch_seconds()
        database_session.commit()
        database_session.refresh(planning_request_row)
        return _to_view_model(planning_request_row)
    except Exception:
        database_session.rollback()
        log.exception("update_planning_request failed: planning_request_id=%s", planning_request_id)
        raise
    finally:
        database_session.close()


def delete_planning_request_by_id(planning_request_id: int) -> bool:
    database_session = SessionLocal()
    try:
        planning_request_row = database_session.get(
            shared_models.PlanningRequest,
            int(planning_request_id),
        )
        if planning_request_row is None:
            return False
        database_session.delete(planning_request_row)
        database_session.commit()
        return True
    except Exception:
        database_session.rollback()
        log.exception("delete_planning_request_by_id failed: planning_request_id=%s", planning_request_id)
        raise
    finally:
        database_session.close()
