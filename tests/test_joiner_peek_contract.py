import os
import sys
import asyncio
from types import SimpleNamespace
from contextlib import contextmanager

import pytest

# Ensure repository root on path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import joiner as j


class DummyClient:
    async def __call__(self, request):
        request_type_name = type(request).__name__
        if request_type_name == "CheckChatInviteRequest":
            return SimpleNamespace(chat=SimpleNamespace(id=123, title="PeekTitle"))
        return SimpleNamespace(chats=[SimpleNamespace(id=123, title="PeekTitle")])


def test_invite_peek_returns_joined_not_none(monkeypatch):
    # Make all external effects no-op
    monkeypatch.setattr(j, "throttle_invite_peek", lambda: asyncio.sleep(0))
    monkeypatch.setattr(j, "throttle_invite", lambda: asyncio.sleep(0))
    monkeypatch.setattr(j, "session_name", lambda client: "sess-test")
    monkeypatch.setattr(j.mem_db, "any_final_for_channel", lambda db, cid: None)
    monkeypatch.setattr(j, "_find_channel", lambda cid: None)
    @contextmanager
    def dummy_db():
        yield SimpleNamespace()
    monkeypatch.setattr(j, "_db", dummy_db)

    client = DummyClient()
    url = "https://t.me/+abcdEFGH12345678"

    status, title, kind, cid, invite_hash = asyncio.run(j.ensure_join(client, url))

    assert status == "joined"
    assert title == "PeekTitle"
    assert cid == 123
    assert kind == "invite"
