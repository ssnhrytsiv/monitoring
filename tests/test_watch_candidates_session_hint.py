import os
import sys
from contextlib import contextmanager


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.DAL import watch_candidates_operations as wc


@contextmanager
def _dummy_session():
    yield object()


def _candidate(*, channel_id=123456, candidate_id=77):
    return {
        "watch_id": 11,
        "id": candidate_id,
        "channel_id": channel_id,
        "message_id": 55,
        "text_hash": "hash-1",
        "created_at": None,
        "status": "pending_candidate",
    }


def test_accept_watch_candidate_prefers_assignment_session(monkeypatch):
    candidate = _candidate()
    matched_sessions = []

    monkeypatch.setattr(wc, "get_watch_candidate", lambda _cid: candidate)
    monkeypatch.setattr(wc, "list_candidates_by_hash", lambda *_a, **_k: [candidate])
    monkeypatch.setattr(wc, "SessionLocal", _dummy_session)
    monkeypatch.setattr(
        wc.assignment_ops,
        "get_assigned_session_for_channel",
        lambda _cid, database_session=None: "tg_session_11",
    )
    monkeypatch.setattr(
        wc.audit_ops,
        "should_bypass_positive_channel_cache",
        lambda _cid, database_session=None: True,
    )
    monkeypatch.setattr(
        wc.mem_db,
        "get_any_session_for_channel",
        lambda _db, _cid: "tg_session_10",
    )
    monkeypatch.setattr(
        wc,
        "process_mark_matched",
        lambda _wid, _mid, _cov, matched_session=None: matched_sessions.append(
            matched_session
        ),
    )
    monkeypatch.setattr(wc, "insert_watch_event", lambda *_a, **_k: None)
    monkeypatch.setattr(wc, "set_watch_candidate_status", lambda *_a, **_k: None)

    assert wc.accept_watch_candidate(candidate["id"]) is True
    assert matched_sessions == ["tg_session_11"]


def test_accept_watch_candidate_ignores_stale_membership_when_audit_marks_missing(
    monkeypatch,
):
    candidate = _candidate()
    matched_sessions = []

    monkeypatch.setattr(wc, "get_watch_candidate", lambda _cid: candidate)
    monkeypatch.setattr(wc, "list_candidates_by_hash", lambda *_a, **_k: [candidate])
    monkeypatch.setattr(wc, "SessionLocal", _dummy_session)
    monkeypatch.setattr(
        wc.assignment_ops,
        "get_assigned_session_for_channel",
        lambda _cid, database_session=None: None,
    )
    monkeypatch.setattr(
        wc.audit_ops,
        "should_bypass_positive_channel_cache",
        lambda _cid, database_session=None: True,
    )
    monkeypatch.setattr(
        wc.mem_db,
        "get_any_session_for_channel",
        lambda _db, _cid: "tg_session_10",
    )
    monkeypatch.setattr(
        wc,
        "process_mark_matched",
        lambda _wid, _mid, _cov, matched_session=None: matched_sessions.append(
            matched_session
        ),
    )
    monkeypatch.setattr(wc, "insert_watch_event", lambda *_a, **_k: None)
    monkeypatch.setattr(wc, "set_watch_candidate_status", lambda *_a, **_k: None)

    assert wc.accept_watch_candidate(candidate["id"]) is True
    assert matched_sessions == [None]
