from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from types import SimpleNamespace


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import account_pool
from app.utils.time_utils import MOSCOW_TZ


def test_next_subscription_audit_run_same_day_before_target_time(monkeypatch) -> None:
    monkeypatch.setattr(account_pool, "SUBSCRIPTION_AUDIT_DAILY_HOUR_MSK", 4)
    monkeypatch.setattr(account_pool, "SUBSCRIPTION_AUDIT_DAILY_MINUTE_MSK", 0)

    now_value = datetime(2026, 3, 22, 3, 15, 0, tzinfo=MOSCOW_TZ)

    next_run = account_pool._get_next_subscription_audit_run_at_msk(now_value)

    assert next_run == datetime(2026, 3, 22, 4, 0, 0, tzinfo=MOSCOW_TZ)
    assert account_pool._get_seconds_until_next_subscription_audit_run(now_value) == 45 * 60


def test_next_subscription_audit_run_next_day_when_target_time_reached(monkeypatch) -> None:
    monkeypatch.setattr(account_pool, "SUBSCRIPTION_AUDIT_DAILY_HOUR_MSK", 4)
    monkeypatch.setattr(account_pool, "SUBSCRIPTION_AUDIT_DAILY_MINUTE_MSK", 0)

    now_value = datetime(2026, 3, 22, 4, 0, 0, tzinfo=MOSCOW_TZ)

    next_run = account_pool._get_next_subscription_audit_run_at_msk(now_value)

    assert next_run == datetime(2026, 3, 23, 4, 0, 0, tzinfo=MOSCOW_TZ)
    assert account_pool._get_seconds_until_next_subscription_audit_run(now_value) == 24 * 60 * 60


def test_start_pool_skips_startup_audit_when_disabled(monkeypatch) -> None:
    startup_audit_reason_list: list[str] = []
    scheduled_task_name_list: list[str] = []

    async def fake_ensure_connected(slot) -> None:
        slot.human_display = "test"

    async def fake_check_pool_limits(reason: str = "periodic") -> None:
        startup_audit_reason_list.append(reason)

    def fake_create_task(coroutine):
        coroutine_code = getattr(coroutine, "cr_code", None)
        scheduled_task_name_list.append(
            coroutine_code.co_name if coroutine_code is not None else "unknown"
        )
        coroutine.close()
        return SimpleNamespace(cancel=lambda: None)

    monkeypatch.setattr(account_pool, "POOL_SESSIONS", ["tg_session_10"])
    monkeypatch.setattr(account_pool, "API_ID", 1)
    monkeypatch.setattr(account_pool, "API_HASH", "hash")
    monkeypatch.setattr(account_pool, "SUBSCRIPTION_AUDIT_REFRESH_ON_STARTUP", False)
    monkeypatch.setattr(account_pool, "_POOL", [])
    monkeypatch.setattr(account_pool, "_limits_checker_task", None)
    monkeypatch.setattr(account_pool, "_health_checker_task", None)
    monkeypatch.setattr(account_pool, "TelegramClient", lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr(account_pool, "_ensure_connected", fake_ensure_connected)
    monkeypatch.setattr(account_pool, "_check_pool_limits", fake_check_pool_limits)
    monkeypatch.setattr(account_pool.asyncio, "create_task", fake_create_task)

    asyncio.run(account_pool.start_pool())

    assert startup_audit_reason_list == []
    assert scheduled_task_name_list == ["_limits_checker_loop", "_health_checker_loop"]


def test_start_pool_runs_startup_audit_when_enabled(monkeypatch) -> None:
    startup_audit_reason_list: list[str] = []

    async def fake_ensure_connected(slot) -> None:
        slot.human_display = "test"

    async def fake_check_pool_limits(reason: str = "periodic") -> None:
        startup_audit_reason_list.append(reason)

    def fake_create_task(coroutine):
        coroutine.close()
        return SimpleNamespace(cancel=lambda: None)

    monkeypatch.setattr(account_pool, "POOL_SESSIONS", ["tg_session_10"])
    monkeypatch.setattr(account_pool, "API_ID", 1)
    monkeypatch.setattr(account_pool, "API_HASH", "hash")
    monkeypatch.setattr(account_pool, "SUBSCRIPTION_AUDIT_REFRESH_ON_STARTUP", True)
    monkeypatch.setattr(account_pool, "_POOL", [])
    monkeypatch.setattr(account_pool, "_limits_checker_task", None)
    monkeypatch.setattr(account_pool, "_health_checker_task", None)
    monkeypatch.setattr(account_pool, "TelegramClient", lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr(account_pool, "_ensure_connected", fake_ensure_connected)
    monkeypatch.setattr(account_pool, "_check_pool_limits", fake_check_pool_limits)
    monkeypatch.setattr(account_pool.asyncio, "create_task", fake_create_task)

    asyncio.run(account_pool.start_pool())

    assert startup_audit_reason_list == ["startup"]
