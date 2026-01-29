import os
import sys
import asyncio
import types
from types import SimpleNamespace
from contextlib import contextmanager

import pytest

# Тестовий модуль працює без встановленого пакета, додаємо корінь репо у шлях
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Заглушки для розриву циклічних імпортів admin_bot.*
sys.modules.setdefault("app.admin_bot.bot.keyboards", types.SimpleNamespace(main_menu_kb=None))
sys.modules.setdefault("app.admin_bot.bot.handlers.admins", types.SimpleNamespace(router=None))
sys.modules.setdefault("app.admin_bot.bot.handlers", types.SimpleNamespace(admins=None))
sys.modules.setdefault("app.admin_bot.services.subscription.subscription_menu", types.SimpleNamespace(split_text_for_telegram=lambda *a, **k: ""))
sys.modules.setdefault("app.admin_bot.services.subscription.subscription_report", types.SimpleNamespace(answer_with_retry=lambda *a, **k: None))

from app.admin_bot.services.subscription import subscription_worker as sw


class DummyProgress:
    def __init__(self, *_, **__):
        self.duplicates = 0
        self.already = 0

    async def start(self):
        return None

    async def update(self, *_args, **_kwargs):
        return None

    async def finish(self):
        return None


class DummyMsg:
    async def answer(self, *_args, **_kwargs):
        return None


@contextmanager
def dummy_session():
    class DummyDB:
        def commit(self):  # pragma: no cover - no real DB work
            return None

        def rollback(self):  # pragma: no cover
            return None

        def close(self):  # pragma: no cover
            return None

    db = DummyDB()
    yield db


def _common_monkeypatch(monkeypatch):
    # Shared no-op patches for heavy dependencies
    monkeypatch.setattr(sw, "Progress", DummyProgress)
    monkeypatch.setattr(sw, "session_scope", dummy_session)
    monkeypatch.setattr(sw.lc_db, "get_link_cache_record", lambda _key: None)
    monkeypatch.setattr(sw.lc_db, "update_link_cache_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sw.mem_db, "any_final_for_channel", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sw.mem_db, "get_any_session_for_channel", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sw.mem_db, "invite_check_last_session", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sw.mem_db, "upsert_membership", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sw.req_ops, "note_requested", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sw.req_ops, "note_requested_invite", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sw.svc_networks, "move_orphans_to_primary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sw.cho, "get_admin_for_channel", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sw.admin_ops, "get_admin_by_display", lambda *_a, **_k: None, raising=False)
    monkeypatch.setattr(sw.admin_ops, "get_admin_by_id", lambda *_a, **_k: None, raising=False)
    monkeypatch.setattr(sw, "_add_link", lambda *_, **__: None)
    monkeypatch.setattr(sw, "mark_flood", lambda *_a, **_k: None)
    monkeypatch.setattr(sw, "mark_limit", lambda *_a, **_k: None)
    monkeypatch.setattr(sw, "bump_cooldown", lambda *_a, **_k: None)


def test_slow_path_upserts_when_valid(monkeypatch):
    calls_upsert = []
    calls_mark_failed = []

    _common_monkeypatch(monkeypatch)

    monkeypatch.setattr(
        sw.link_queue,
        "fetch_batch_due",
        lambda _batch_id, limit=50: [SimpleNamespace(id=1, url="https://t.me/demo", tries=0, origin_msg=None, owner_admin_id=None)],
    )
    monkeypatch.setattr(sw.link_queue, "mark_processing", lambda *_a, **_k: None)
    monkeypatch.setattr(sw.link_queue, "mark_done", lambda *_a, **_k: None)
    monkeypatch.setattr(sw.link_queue, "mark_failed", lambda *_a, **_k: calls_mark_failed.append(_a))

    class Slot(SimpleNamespace):
        pass

    slot = Slot(client="c1", busy=False)
    async def fake_slot(preferred_session=None):
        return slot

    monkeypatch.setattr(sw, "get_ready_slot", fake_slot)

    monkeypatch.setattr(sw, "session_name", lambda client: "sess1")

    async def fake_join(_client, _url):
        return "joined", "Demo", "public", 123, None

    monkeypatch.setattr(sw, "ensure_join", fake_join)

    monkeypatch.setattr(
        sw.admin_ops,
        "get_or_create_admin_entity",
        lambda _db, tg_id=None, username=None, display=None: SimpleNamespace(id=42, username=username or "owner42"),
    )
    monkeypatch.setattr(sw.admin_ops, "attach_channel", lambda *_a, **_k: {"status": "ok"}, raising=False)
    monkeypatch.setattr(sw.admin_ops, "get_admin_by_id", lambda *_a, **_k: None)

    monkeypatch.setattr(
        sw,
        "upsert_channel_full",
        lambda _db, **kwargs: calls_upsert.append((kwargs["channel_id"], kwargs["owner_admin_id"], kwargs.get("order_index"))),
    )

    asyncio.run(
        sw.process_batch(
            batch_id="batchX",
            chat_id=1,
            reply_msg=DummyMsg(),
            admin_id=42,
            admin_display="disp",
            admin_username="user",
            admin_tg_id=999,
        )
    )

    assert calls_upsert == [(123, 42, 1)]
    assert calls_mark_failed == []


def test_slow_path_skips_upsert_on_invalid_cid(monkeypatch):
    calls_upsert = []
    calls_mark_failed = []

    _common_monkeypatch(monkeypatch)

    monkeypatch.setattr(
        sw.link_queue,
        "fetch_batch_due",
        lambda _batch_id, limit=50: [SimpleNamespace(id=2, url="https://t.me/bad", tries=0, origin_msg=None, owner_admin_id=None)],
    )
    monkeypatch.setattr(sw.link_queue, "mark_processing", lambda *_a, **_k: None)
    monkeypatch.setattr(sw.link_queue, "mark_done", lambda *_a, **_k: None)

    def record_failed(item_id, error, backoff_sec, max_retries=5):
        calls_mark_failed.append((item_id, error, backoff_sec, max_retries))

    monkeypatch.setattr(sw.link_queue, "mark_failed", record_failed)

    class Slot(SimpleNamespace):
        pass

    slot = Slot(client="c1", busy=False)
    async def fake_slot(preferred_session=None):
        return slot

    monkeypatch.setattr(sw, "get_ready_slot", fake_slot)

    monkeypatch.setattr(sw, "session_name", lambda client: "sess1")

    async def fake_join(_client, _url):
        return "joined", "Bad", "public", 0, None  # cid <= 0 triggers guard

    monkeypatch.setattr(sw, "ensure_join", fake_join)

    monkeypatch.setattr(
        sw.admin_ops,
        "get_or_create_admin_entity",
        lambda _db, tg_id=None, username=None, display=None: SimpleNamespace(id=55, username=username or "owner55"),
    )
    monkeypatch.setattr(sw.admin_ops, "attach_channel", lambda *_a, **_k: {"status": "ok"}, raising=False)
    monkeypatch.setattr(
        sw,
        "upsert_channel_full",
        lambda _db, **kwargs: calls_upsert.append((kwargs["channel_id"], kwargs["owner_admin_id"])),
    )

    asyncio.run(
        sw.process_batch(
            batch_id="batchBad",
            chat_id=1,
            reply_msg=DummyMsg(),
            admin_id=55,
            admin_display="disp",
            admin_username="user",
            admin_tg_id=999,
        )
    )

    assert calls_upsert == []
    assert calls_mark_failed and calls_mark_failed[0][1] == "invalid_cid"


def test_worker_handles_none_status_and_continues(monkeypatch):
    calls_upsert = []
    calls_mark_failed = []
    calls_done = []

    _common_monkeypatch(monkeypatch)

    monkeypatch.setattr(
        sw.link_queue,
        "fetch_batch_due",
        lambda _batch_id, limit=50: [
            SimpleNamespace(id=1, url="https://t.me/bad_invite", tries=0, origin_msg=None, owner_admin_id=None),
            SimpleNamespace(id=2, url="https://t.me/good", tries=0, origin_msg=None, owner_admin_id=None),
        ],
    )
    monkeypatch.setattr(sw.link_queue, "mark_processing", lambda *_a, **_k: None)
    monkeypatch.setattr(sw.link_queue, "mark_done", lambda *a, **k: calls_done.append(a))

    def record_failed(item_id, error, backoff_sec, max_retries=5):
        calls_mark_failed.append((item_id, error))

    monkeypatch.setattr(sw.link_queue, "mark_failed", record_failed)

    class Slot(SimpleNamespace):
        pass

    slot = Slot(client="c1", busy=False)

    async def fake_slot(preferred_session=None):
        return slot

    monkeypatch.setattr(sw, "get_ready_slot", fake_slot)
    monkeypatch.setattr(sw, "session_name", lambda client: "sess1")

    responses = [
        (None, "Bad", "invite", None, "hash1"),
        ("joined", "Good", "public", 321, None),
    ]

    async def fake_join(_client, _url):
        return responses.pop(0)

    monkeypatch.setattr(sw, "ensure_join", fake_join)

    monkeypatch.setattr(
        sw,
        "upsert_channel_full",
        lambda _db, **kwargs: calls_upsert.append((kwargs["channel_id"], kwargs["owner_admin_id"], kwargs.get("order_index"))),
    )
    monkeypatch.setattr(sw.admin_ops, "get_or_create_admin_entity", lambda *_a, **_k: SimpleNamespace(id=77, username="owner77"))
    monkeypatch.setattr(sw.admin_ops, "attach_channel", lambda *_a, **_k: {"status": "ok"}, raising=False)

    asyncio.run(
        sw.process_batch(
            batch_id="batchMixed",
            chat_id=1,
            reply_msg=DummyMsg(),
            admin_id=77,
            admin_display="disp",
            admin_username="user",
            admin_tg_id=999,
        )
    )

    # First item should fail with unknown (None status), second should succeed and upsert
    assert calls_mark_failed and calls_mark_failed[0][0] == 1
    assert calls_upsert == [(321, 77, 2)]


def test_per_item_owner_used(monkeypatch):
    calls_upsert = []
    _common_monkeypatch(monkeypatch)

    monkeypatch.setattr(
        sw.link_queue,
        "fetch_batch_due",
        lambda _batch_id, limit=50: [
            SimpleNamespace(id=1, url="https://t.me/one", tries=0, origin_msg=None, owner_admin_id=1),
            SimpleNamespace(id=2, url="https://t.me/two", tries=0, origin_msg=None, owner_admin_id=2),
        ],
    )
    monkeypatch.setattr(sw.link_queue, "mark_processing", lambda *_a, **_k: None)
    monkeypatch.setattr(sw.link_queue, "mark_done", lambda *_a, **_k: None)
    monkeypatch.setattr(sw.link_queue, "mark_failed", lambda *_a, **_k: None)

    class Slot(SimpleNamespace):
        pass

    slot = Slot(client="c1", busy=False)

    async def fake_slot(preferred_session=None):
        return slot

    monkeypatch.setattr(sw, "get_ready_slot", fake_slot)
    monkeypatch.setattr(sw, "session_name", lambda client: "sess1")

    responses = [
        ("joined", "One", "public", 101, None),
        ("joined", "Two", "public", 202, None),
    ]

    async def fake_join(_client, _url):
        return responses.pop(0)

    monkeypatch.setattr(sw, "ensure_join", fake_join)
    monkeypatch.setattr(
        sw,
        "upsert_channel_full",
        lambda _db, **kwargs: calls_upsert.append((kwargs["channel_id"], kwargs["owner_admin_id"])),
    )

    asyncio.run(
        sw.process_batch(
            batch_id="batchOwners",
            chat_id=1,
            reply_msg=DummyMsg(),
            admin_id=None,
            admin_display="disp",
            admin_username="user",
            admin_tg_id=999,
        )
    )

    assert calls_upsert == [(101, 1), (202, 2)]


def test_build_preknown_uses_per_item_owner(monkeypatch):
    updates: list[str] = []

    class CaptureProgress:
        def __init__(self, *_a, **_k):
            self.total = _k.get("total", 0)
            self.duplicates = 0
            self.already = 0
        async def start(self):  # pragma: no cover
            return None
        async def update(self, status, *_args, **_kwargs):
            updates.append(status)
        async def finish(self):  # pragma: no cover
            return None

    _common_monkeypatch(monkeypatch)
    monkeypatch.setattr(sw, "Progress", CaptureProgress)

    monkeypatch.setattr(
        sw.link_queue,
        "fetch_batch_due",
        lambda _batch_id, limit=50: [
            SimpleNamespace(id=1, url="https://t.me/inviteA", tries=0, origin_msg=None, owner_admin_id=1),
            SimpleNamespace(id=2, url="https://t.me/inviteB", tries=0, origin_msg=None, owner_admin_id=2),
        ],
    )
    monkeypatch.setattr(sw.link_queue, "mark_processing", lambda *_a, **_k: None)
    monkeypatch.setattr(sw.link_queue, "mark_done", lambda *_a, **_k: None)
    monkeypatch.setattr(sw.link_queue, "mark_failed", lambda *_a, **_k: None)

    monkeypatch.setattr(sw, "_find_channel_by_link", lambda *_, **__: SimpleNamespace(channel_id=999, title="Chan"))
    monkeypatch.setattr(sw, "_get_channel_id_by_url", lambda *_, **__: None)

    owner_info = SimpleNamespace(admin_id=1, display=None, username="owner1")
    monkeypatch.setattr(sw.cho, "get_admin_for_channel", lambda *_a, **_k: owner_info)
    monkeypatch.setattr(sw.mem_db, "any_final_for_channel", lambda *_a, **_k: "joined")
    monkeypatch.setattr(sw.mem_db, "get_any_session_for_channel", lambda *_a, **_k: None)

    asyncio.run(
        sw.process_batch(
            batch_id="batchPreknownOwners",
            chat_id=1,
            reply_msg=DummyMsg(),
            admin_id=None,
            admin_display="callerDisp",
            admin_username="callerUser",
            admin_tg_id=999,
        )
    )

    # First item owner matches -> already; second item differs -> owner_conflict
    assert updates == ["already", "owner_conflict(existing=@owner1)"]


def test_cache_conflict_uses_owner_display_from_queue(monkeypatch):
    updates: list[str] = []
    created_admins = []

    class CaptureProgress:
        def __init__(self, *_a, **_k):
            self.total = _k.get("total", 0)
            self.duplicates = 0
            self.already = 0
        async def start(self):  # pragma: no cover
            return None
        async def update(self, status, *_args, **_kwargs):
            updates.append(status)
        async def finish(self):  # pragma: no cover
            return None

    _common_monkeypatch(monkeypatch)
    monkeypatch.setattr(sw, "Progress", CaptureProgress)

    # queue item has owner_display but no owner_admin_id
    monkeypatch.setattr(
        sw.link_queue,
        "fetch_batch_due",
        lambda _batch_id, limit=50: [
            SimpleNamespace(id=1, url="https://t.me/+hashConflict", tries=0, origin_msg=None, owner_admin_id=None, owner_display="Антоха Криптон"),
        ],
    )
    monkeypatch.setattr(sw.link_queue, "mark_processing", lambda *_a, **_k: None)
    monkeypatch.setattr(sw.link_queue, "mark_done", lambda *_a, **_k: None)
    monkeypatch.setattr(sw.link_queue, "mark_failed", lambda *_a, **_k: None)

    # LinkCache reports already with cid
    cache_rec = SimpleNamespace(status="already", title="тест3", channel_id=999, account="sessX")
    monkeypatch.setattr(sw.lc_db, "get_link_cache_record", lambda _key: cache_rec)

    owner_info = SimpleNamespace(admin_id=1, display="Марко", username=None)
    monkeypatch.setattr(sw.cho, "get_admin_for_channel", lambda *_a, **_k: owner_info)
    monkeypatch.setattr(sw.mem_db, "any_final_for_channel", lambda *_a, **_k: "already")
    monkeypatch.setattr(sw.mem_db, "get_any_session_for_channel", lambda *_a, **_k: "sessX")

    # guard: no admin creation should happen
    def _forbid_create(*_a, **_k):
        created_admins.append((_a, _k))
        raise AssertionError("Admin should not be created")
    monkeypatch.setattr(sw.admin_ops, "get_or_create_admin_entity", _forbid_create, raising=False)

    asyncio.run(
        sw.process_batch(
            batch_id="batchCacheConflict",
            chat_id=1,
            reply_msg=DummyMsg(),
            admin_id=None,
            admin_display=None,
            admin_username=None,
            admin_tg_id=None,
        )
    )

    assert updates and updates[0].startswith("owner_conflict(existing=Марко)")
    assert not created_admins
