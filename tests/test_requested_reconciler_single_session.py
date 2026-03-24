import os
import sys
from types import SimpleNamespace


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import requested_reconciler as reconciler


def test_resolve_single_session_keep_session_prefers_current_after_missing_repair():
    membership_db = SimpleNamespace(get_session_by_channel=lambda _cid: "tg_session_10")

    keep_session_name = reconciler._resolve_single_session_keep_session_name(
        channel_id=123456,
        current_session_name="tg_session_11",
        membership_db=membership_db,
        prefer_current_session=True,
    )

    assert keep_session_name == "tg_session_11"


def test_resolve_single_session_keep_session_prefers_assigned_session_when_channel_is_healthy(
    monkeypatch,
):
    monkeypatch.setattr(
        reconciler.assignment_ops,
        "get_assigned_session_for_channel",
        lambda _cid: "tg_session_10",
    )
    membership_db = SimpleNamespace(get_session_by_channel=lambda _cid: "tg_session_11")

    keep_session_name = reconciler._resolve_single_session_keep_session_name(
        channel_id=123456,
        current_session_name="tg_session_11",
        membership_db=membership_db,
        prefer_current_session=False,
    )

    assert keep_session_name == "tg_session_10"
