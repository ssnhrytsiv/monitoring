import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.DAL import channel_subscription_audit_operations as audit_ops
from app.DAL.channel_subscription_audit_models import (
    ChannelSubscriptionAuditReasonEnum,
    parse_channel_subscription_audit_details,
)
from app.admin_bot.db import models
from app.admin_bot.db.session import Base


def _build_test_session_factory():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def test_targeted_refresh_marks_channel_subscribed_when_expected_session_present(
    monkeypatch,
):
    session_factory = _build_test_session_factory()
    monkeypatch.setattr(audit_ops, "SessionLocal", session_factory)
    monkeypatch.setattr(audit_ops.time, "time", lambda: 500)

    with session_factory() as database_session:
        database_session.add(
            models.ChannelSubscriptionAudit(
                channel_id=123456,
                audit_status=audit_ops.CHANNEL_AUDIT_STATUS_MISSING,
                checked_at=100,
                missing_detected_at=90,
                status_details="{}",
            )
        )
        database_session.add(
            models.ChannelSessionAssignment(
                channel_id=123456,
                session_name="tg_session_11",
                admin_id=5,
                assigned_at=1,
                updated_at=2,
                last_ok_at=2,
                last_repair_at=None,
                assignment_source="seed",
            )
        )
        database_session.commit()

    refreshed_status = audit_ops.refresh_channel_subscription_audit_for_channel(
        123456,
        present_session_name_list=["tg_session_11"],
        audit_reason="subscription_worker:ensure_join:public",
    )

    assert refreshed_status == audit_ops.CHANNEL_AUDIT_STATUS_SUBSCRIBED

    with session_factory() as database_session:
        audit_row = (
            database_session.query(models.ChannelSubscriptionAudit)
            .filter(models.ChannelSubscriptionAudit.channel_id == 123456)
            .one()
        )

    assert audit_row.audit_status == audit_ops.CHANNEL_AUDIT_STATUS_SUBSCRIBED
    assert audit_row.checked_at == 500
    assert audit_row.missing_detected_at is None

    details = parse_channel_subscription_audit_details(audit_row.status_details)
    assert details is not None
    assert details.audit_reason == "subscription_worker:ensure_join:public"
    assert details.status_reason == ChannelSubscriptionAuditReasonEnum.EXPECTED_SESSION_PRESENT
    assert details.expected_session == "tg_session_11"
    assert details.present_sessions == ["tg_session_11"]
    assert details.admin_id == 5
    assert details.assignment_source == "seed"


def test_targeted_refresh_keeps_missing_when_only_other_session_is_present(monkeypatch):
    session_factory = _build_test_session_factory()
    monkeypatch.setattr(audit_ops, "SessionLocal", session_factory)
    monkeypatch.setattr(audit_ops.time, "time", lambda: 500)

    with session_factory() as database_session:
        database_session.add(
            models.ChannelSubscriptionAudit(
                channel_id=123456,
                audit_status=audit_ops.CHANNEL_AUDIT_STATUS_MISSING,
                checked_at=100,
                missing_detected_at=90,
                status_details="{}",
            )
        )
        database_session.add(
            models.ChannelSessionAssignment(
                channel_id=123456,
                session_name="tg_session_11",
                admin_id=5,
                assigned_at=1,
                updated_at=2,
                last_ok_at=2,
                last_repair_at=None,
                assignment_source="seed",
            )
        )
        database_session.commit()

    refreshed_status = audit_ops.refresh_channel_subscription_audit_for_channel(
        123456,
        present_session_name_list=["tg_session_10"],
        audit_reason="subscription_worker:ensure_join:public",
    )

    assert refreshed_status == audit_ops.CHANNEL_AUDIT_STATUS_MISSING

    with session_factory() as database_session:
        audit_row = (
            database_session.query(models.ChannelSubscriptionAudit)
            .filter(models.ChannelSubscriptionAudit.channel_id == 123456)
            .one()
        )

    assert audit_row.audit_status == audit_ops.CHANNEL_AUDIT_STATUS_MISSING
    assert audit_row.checked_at == 500
    assert audit_row.missing_detected_at == 90

    details = parse_channel_subscription_audit_details(audit_row.status_details)
    assert details is not None
    assert (
        details.status_reason
        == ChannelSubscriptionAuditReasonEnum.EXPECTED_SESSION_MISSING_PRESENT_ELSEWHERE
    )
    assert details.expected_session == "tg_session_11"
    assert details.present_sessions == ["tg_session_10"]
