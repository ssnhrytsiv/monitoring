import asyncio
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.admin_bot.db import models
from app.admin_bot.db.session import Base
from app.services import channel_session_cleanup as cleanup


def _build_test_session_factory():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _seed_membership_rows(session_factory):
    with session_factory() as database_session:
        database_session.add(
            models.Membership(
                channel_id=123456,
                account="tg_session_11",
                status="already",
                ts=20,
            )
        )
        database_session.add(
            models.Membership(
                channel_id=123456,
                account="tg_session_10",
                status="already",
                ts=10,
            )
        )
        database_session.commit()


def test_enforce_single_session_per_channel_deletes_stale_membership_after_leave(
    monkeypatch,
):
    session_factory = _build_test_session_factory()
    _seed_membership_rows(session_factory)
    monkeypatch.setattr(cleanup, "SessionLocal", session_factory)

    async def _fake_leave_channels(session_name, channel_ids):
        assert session_name == "tg_session_10"
        assert channel_ids == [123456]
        return {
            "session": session_name,
            "left": 1,
            "skipped": 0,
            "errors": 0,
        }

    monkeypatch.setattr(cleanup.account_pool, "leave_channels", _fake_leave_channels)

    cleanup_stats = asyncio.run(
        cleanup.enforce_single_session_per_channel(
            channel_id=123456,
            keep_session_name="tg_session_11",
            reason="test_cleanup",
        )
    )

    assert cleanup_stats["checked"] == 1
    assert cleanup_stats["left"] == 1
    assert cleanup_stats["deleted"] == 1

    with session_factory() as database_session:
        remaining_accounts = [
            row.account
            for row in database_session.query(models.Membership)
            .filter(models.Membership.channel_id == 123456)
            .order_by(models.Membership.account.asc())
            .all()
        ]

    assert remaining_accounts == ["tg_session_11"]


def test_enforce_single_session_per_channel_keeps_stale_membership_when_leave_fails(
    monkeypatch,
):
    session_factory = _build_test_session_factory()
    _seed_membership_rows(session_factory)
    monkeypatch.setattr(cleanup, "SessionLocal", session_factory)

    async def _fake_leave_channels(session_name, channel_ids):
        assert session_name == "tg_session_10"
        assert channel_ids == [123456]
        return {
            "session": session_name,
            "left": 0,
            "skipped": 0,
            "errors": 1,
        }

    monkeypatch.setattr(cleanup.account_pool, "leave_channels", _fake_leave_channels)

    cleanup_stats = asyncio.run(
        cleanup.enforce_single_session_per_channel(
            channel_id=123456,
            keep_session_name="tg_session_11",
            reason="test_cleanup",
        )
    )

    assert cleanup_stats["checked"] == 1
    assert cleanup_stats["errors"] == 1
    assert cleanup_stats["deleted"] == 0

    with session_factory() as database_session:
        remaining_accounts = [
            row.account
            for row in database_session.query(models.Membership)
            .filter(models.Membership.channel_id == 123456)
            .order_by(models.Membership.account.asc())
            .all()
        ]

    assert remaining_accounts == ["tg_session_10", "tg_session_11"]


def test_enforce_single_session_per_channel_uses_observed_sessions_not_only_membership(
    monkeypatch,
):
    session_factory = _build_test_session_factory()
    with session_factory() as database_session:
        database_session.add(
            models.Membership(
                channel_id=123456,
                account="tg_session_11",
                status="already",
                ts=20,
            )
        )
        database_session.commit()

    monkeypatch.setattr(cleanup, "SessionLocal", session_factory)

    seen_leave_calls = []

    async def _fake_leave_channels(session_name, channel_ids):
        seen_leave_calls.append((session_name, list(channel_ids)))
        return {
            "session": session_name,
            "left": 1,
            "skipped": 0,
            "errors": 0,
        }

    monkeypatch.setattr(cleanup.account_pool, "leave_channels", _fake_leave_channels)

    cleanup_stats = asyncio.run(
        cleanup.enforce_single_session_per_channel(
            channel_id=123456,
            keep_session_name="tg_session_11",
            reason="test_cleanup",
            observed_session_name_list=["tg_session_11", "tg_session_10"],
        )
    )

    assert cleanup_stats["checked"] == 1
    assert cleanup_stats["left"] == 1
    assert cleanup_stats["deleted"] == 0
    assert seen_leave_calls == [("tg_session_10", [123456])]
