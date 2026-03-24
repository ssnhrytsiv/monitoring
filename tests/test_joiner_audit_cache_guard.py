import os
import sys
from contextlib import contextmanager
from types import SimpleNamespace


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import joiner as j


@contextmanager
def _membership_with_status(status_value):
    yield SimpleNamespace(any_final_for_channel=lambda _cid: status_value)


def test_cached_membership_final_is_ignored_when_audit_marks_channel_missing(monkeypatch):
    monkeypatch.setattr(
        j.audit_ops,
        "should_bypass_positive_channel_cache",
        lambda _cid: True,
    )
    monkeypatch.setattr(j, "_membership", lambda: _membership_with_status("joined"))

    assert j._cached_membership_final_for_channel(123456) is None


def test_cached_invalid_status_is_kept_even_when_audit_marks_channel_missing(monkeypatch):
    monkeypatch.setattr(
        j.audit_ops,
        "should_bypass_positive_channel_cache",
        lambda _cid: True,
    )
    monkeypatch.setattr(j, "_membership", lambda: _membership_with_status("invalid"))

    assert j._cached_membership_final_for_channel(123456) == "invalid"


def test_resolve_other_session_prefers_assignment(monkeypatch):
    monkeypatch.setattr(
        j.assignment_ops,
        "get_assigned_session_for_channel",
        lambda _cid, database_session=None: "tg_session_11",
    )
    monkeypatch.setattr(
        j,
        "_should_bypass_positive_channel_cache",
        lambda _cid: False,
    )
    monkeypatch.setattr(
        j.mem_db,
        "get_any_session_for_channel",
        lambda _db, _cid: "tg_session_10",
    )

    assert (
        j._resolve_other_session_for_channel(123456, database_session=object())
        == "tg_session_11"
    )


def test_resolve_other_session_ignores_stale_membership_when_audit_marks_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        j.assignment_ops,
        "get_assigned_session_for_channel",
        lambda _cid, database_session=None: None,
    )
    monkeypatch.setattr(
        j,
        "_should_bypass_positive_channel_cache",
        lambda _cid: True,
    )
    monkeypatch.setattr(
        j.mem_db,
        "get_any_session_for_channel",
        lambda _db, _cid: "tg_session_10",
    )

    assert j._resolve_other_session_for_channel(123456, database_session=object()) is None
