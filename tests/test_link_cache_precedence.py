import os
import sys
import types

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.DAL import link_cache_operations as lc_db
from app.DAL.schemas import LinkCachePatch


class DummyRow:
    def __init__(self, status, channel_id=None, account="", title=None, last_error=None, join_time=None):
        self.status = status
        self.channel_id = channel_id
        self.account = account
        self.title = title
        self.last_error = last_error
        self.join_time = join_time


def test_owner_conflict_not_overwritten(monkeypatch):
    """Owner_conflict is no longer stored in cache; overwrite behaves like regular upsert."""
    store = {}

    def session_scope():
        class DummySession:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, exc_type, exc_val, exc_tb):
                return False

            def commit(self_inner):
                return None

            def query(self_inner, model):
                class Q:
                    def filter(self, expr):
                        class R:
                            def one_or_none(_):
                                return store.get(expr.right.value)
                        return R()
                return Q()

            def add(self_inner, obj):
                store[obj.url_norm] = obj

        return DummySession()

    monkeypatch.setattr(lc_db, "session_scope", session_scope)
    monkeypatch.setattr(lc_db, "_now_ts", lambda: 999)

    # seed with joined
    store["u2"] = DummyRow(status="joined", channel_id=10, account="sessX", title="Old")

    lc_db.update_link_cache_status(
        LinkCachePatch(url_norm="u2", kind="invite", status="already", account="sessY", channel_id=20, title="New")
    )

    rec = store["u2"]
    assert rec.status == "already"
    assert rec.channel_id == 20
    assert rec.account == "sessY"
    assert rec.title == "New"
    assert rec.join_time == 999
