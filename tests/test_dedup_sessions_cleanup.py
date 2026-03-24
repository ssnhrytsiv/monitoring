import asyncio
import importlib.util
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.admin_bot.db import models
from app.admin_bot.db.session import Base

_MODULE_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "app",
        "admin_bot",
        "services",
        "subscription",
        "dedup_sessions_cleanup.py",
    )
)
_SPEC = importlib.util.spec_from_file_location(
    "dedup_sessions_cleanup_test_module",
    _MODULE_PATH,
)
dedup_cleanup = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
sys.modules[_SPEC.name] = dedup_cleanup
_SPEC.loader.exec_module(dedup_cleanup)


def _build_test_session_factory():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def test_choose_keep_session_name_prefers_assignment(monkeypatch):
    session_factory = _build_test_session_factory()

    with session_factory() as database_session:
        database_session.add(
            models.ChannelSessionAssignment(
                channel_id=123456,
                session_name="tg_session_10",
                admin_id=7,
                assigned_at=1,
                updated_at=1,
                last_ok_at=1,
                last_repair_at=None,
                assignment_source="seed",
            )
        )
        database_session.add(
            models.Membership(
                channel_id=123456,
                account="tg_session_11",
                status="already",
                ts=20,
            )
        )
        database_session.commit()

        keep_session_name, keep_reason, assigned_session_name = (
            dedup_cleanup._choose_keep_session_name(
                channel_id=123456,
                observed_session_name_list=["tg_session_11", "tg_session_10"],
                membership_db=dedup_cleanup.MembershipDAO(database_session),
                database_session=database_session,
            )
        )

    assert keep_session_name == "tg_session_10"
    assert keep_reason == "assignment"
    assert assigned_session_name == "tg_session_10"


def test_execute_duplicate_cleanup_plan_updates_assignment_and_audit(monkeypatch):
    session_factory = _build_test_session_factory()
    monkeypatch.setattr(dedup_cleanup, "SessionLocal", session_factory)

    cleanup_calls = []
    audit_calls = []

    async def _fake_enforce_single_session_per_channel(
        *,
        channel_id,
        keep_session_name,
        reason,
        observed_session_name_list=None,
    ):
        cleanup_calls.append(
            {
                "channel_id": channel_id,
                "keep_session_name": keep_session_name,
                "reason": reason,
                "observed_session_name_list": list(observed_session_name_list or []),
            }
        )
        return {"checked": 1, "left": 1, "skipped": 0, "errors": 0, "deleted": 1}

    monkeypatch.setattr(
        dedup_cleanup,
        "enforce_single_session_per_channel",
        _fake_enforce_single_session_per_channel,
    )
    monkeypatch.setattr(
        dedup_cleanup.audit_ops,
        "refresh_channel_subscription_audit_for_channel",
        lambda channel_id, present_session_name_list=None, audit_reason="targeted": audit_calls.append(
            {
                "channel_id": channel_id,
                "present_session_name_list": list(present_session_name_list or []),
                "audit_reason": audit_reason,
            }
        ),
    )

    plan_item = dedup_cleanup.DuplicateCleanupPlanItem(
        channel_id=123456,
        title="Test channel",
        observed_session_name_list=["tg_session_11", "tg_session_10"],
        keep_session_name="tg_session_11",
        keep_reason="assignment",
        assigned_session_name="tg_session_11",
    )

    execution_item_list = asyncio.run(
        dedup_cleanup.execute_duplicate_cleanup_plan([plan_item])
    )

    assert len(execution_item_list) == 1
    assert cleanup_calls == [
        {
            "channel_id": 123456,
            "keep_session_name": "tg_session_11",
            "reason": "admin_bot:dedup_sessions",
            "observed_session_name_list": ["tg_session_11", "tg_session_10"],
        }
    ]
    assert audit_calls == [
        {
            "channel_id": 123456,
            "present_session_name_list": ["tg_session_11"],
            "audit_reason": "admin_bot:dedup_sessions",
        }
    ]

    with session_factory() as database_session:
        membership_row = (
            database_session.query(models.Membership)
            .filter(
                models.Membership.channel_id == 123456,
                models.Membership.account == "tg_session_11",
            )
            .one()
        )
        assignment_row = (
            database_session.query(models.ChannelSessionAssignment)
            .filter(models.ChannelSessionAssignment.channel_id == 123456)
            .one()
        )

    assert membership_row.status == "already"
    assert assignment_row.session_name == "tg_session_11"
    assert assignment_row.assignment_source == "admin_bot:dedup_sessions"
