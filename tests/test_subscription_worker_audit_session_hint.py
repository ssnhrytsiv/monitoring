import os
import sys
import types
from types import SimpleNamespace


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Заглушки для розриву циклічних імпортів admin_bot.*
sys.modules.setdefault("app.admin_bot.bot.keyboards", types.SimpleNamespace(main_menu_kb=None))
sys.modules.setdefault("app.admin_bot.bot.handlers.admins", types.SimpleNamespace(router=None))
sys.modules.setdefault("app.admin_bot.bot.handlers", types.SimpleNamespace(admins=None))
sys.modules.setdefault(
    "app.admin_bot.services.subscription.subscription_menu",
    types.SimpleNamespace(
        split_text_for_telegram=lambda *a, **k: "",
        make_report_kb=lambda *a, **k: None,
    ),
)
sys.modules.setdefault(
    "app.admin_bot.services.subscription.subscription_report",
    types.SimpleNamespace(answer_with_retry=lambda *a, **k: None),
)

from app.admin_bot.services.subscription import subscription_worker as sw


def test_effective_session_hint_prefers_assignment(monkeypatch):
    monkeypatch.setattr(
        sw.assignment_ops,
        "get_assigned_session_for_channel",
        lambda _cid: "tg_session_11",
    )
    monkeypatch.setattr(sw, "_should_bypass_positive_cache", lambda _cid: True)

    membership_db = SimpleNamespace(get_session_by_channel=lambda _cid: "tg_session_10")

    assert sw._get_effective_session_hint(123456, membership_db) == "tg_session_11"


def test_effective_session_hint_ignores_stale_membership_when_audit_marks_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        sw.assignment_ops,
        "get_assigned_session_for_channel",
        lambda _cid: None,
    )
    monkeypatch.setattr(sw, "_should_bypass_positive_cache", lambda _cid: True)

    membership_db = SimpleNamespace(get_session_by_channel=lambda _cid: "tg_session_10")

    assert sw._get_effective_session_hint(123456, membership_db) is None


def test_resolve_success_session_binding_repairs_missing_channel_with_new_session(
    monkeypatch,
):
    monkeypatch.setattr(
        sw.audit_ops,
        "should_bypass_positive_channel_cache",
        lambda _cid: True,
    )
    monkeypatch.setattr(
        sw.assignment_ops,
        "get_assigned_session_for_channel",
        lambda _cid: "tg_session_10",
    )
    membership_db = SimpleNamespace(
        get_session_by_channel=lambda _cid: "tg_session_10",
    )

    skip_membership, audit_present_session_name = sw._resolve_success_session_binding(
        channel_id=123456,
        base_status="already",
        current_session_name="tg_session_11",
        membership_db=membership_db,
    )

    assert skip_membership is False
    assert audit_present_session_name == "tg_session_11"


def test_resolve_success_session_binding_keeps_existing_session_when_channel_not_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        sw.audit_ops,
        "should_bypass_positive_channel_cache",
        lambda _cid: False,
    )
    monkeypatch.setattr(
        sw.assignment_ops,
        "get_assigned_session_for_channel",
        lambda _cid: "tg_session_10",
    )

    membership_db = SimpleNamespace(
        delete_membership=lambda *_args, **_kwargs: 0,
        get_session_by_channel=lambda _cid: "tg_session_10",
    )

    skip_membership, audit_present_session_name = sw._resolve_success_session_binding(
        channel_id=123456,
        base_status="already",
        current_session_name="tg_session_11",
        membership_db=membership_db,
    )

    assert skip_membership is True
    assert audit_present_session_name == "tg_session_10"


def test_resolve_repair_preferred_session_prefers_assignment_for_missing(monkeypatch):
    monkeypatch.setattr(sw, "_should_bypass_positive_cache", lambda _cid: True)
    monkeypatch.setattr(
        sw.assignment_ops,
        "get_assigned_session_for_channel",
        lambda _cid: "tg_session_11",
    )

    assert (
        sw._resolve_repair_preferred_session(123456, "tg_session_6")
        == "tg_session_11"
    )


def test_resolve_repair_preferred_session_keeps_existing_preference_when_not_missing(
    monkeypatch,
):
    monkeypatch.setattr(sw, "_should_bypass_positive_cache", lambda _cid: False)
    monkeypatch.setattr(
        sw.assignment_ops,
        "get_assigned_session_for_channel",
        lambda _cid: "tg_session_11",
    )

    assert (
        sw._resolve_repair_preferred_session(123456, "tg_session_6")
        == "tg_session_6"
    )


def test_should_use_url_cache_status_ignores_duplicate(monkeypatch):
    monkeypatch.setattr(sw, "_should_bypass_positive_cache", lambda _cid: False)

    assert (
        sw._should_use_url_cache_status(
            status_norm="duplicate",
            channel_id=123456,
        )
        is False
    )


def test_should_use_url_cache_status_bypasses_positive_cache_for_missing(monkeypatch):
    monkeypatch.setattr(sw, "_should_bypass_positive_cache", lambda _cid: True)

    assert (
        sw._should_use_url_cache_status(
            status_norm="already",
            channel_id=123456,
        )
        is False
    )
