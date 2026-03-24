import asyncio
import json
import os
import sys
from types import SimpleNamespace


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.plugins import posts_watch_listener as listener


class _FakeMessage:
    def __init__(self, views: int):
        self.views = views


class _FakeClient:
    def __init__(self, fallback_message):
        self._fallback_message = fallback_message

    async def get_messages(self, entity, ids):
        if entity == 1801542020:
            return None
        if entity == "resolved-entity":
            return self._fallback_message
        raise AssertionError(f"unexpected entity={entity!r} ids={ids!r}")

    async def get_entity(self, source_url):
        if source_url != "https://t.me/test_channel":
            raise AssertionError(f"unexpected source_url={source_url!r}")
        return "resolved-entity"


class _RerouteClient:
    def __init__(
        self,
        name: str,
        *,
        direct_error: bool = False,
        direct_message=None,
        fallback_message=None,
        fallback_error: Exception | None = None,
    ):
        self.name = name
        self.direct_error = direct_error
        self.direct_message = direct_message
        self.fallback_message = fallback_message
        self.fallback_error = fallback_error
        self.entity_calls = []

    async def get_messages(self, entity, ids):
        if entity == 1801542020:
            if self.direct_error:
                raise RuntimeError(f"access lost for {self.name}")
            return self.direct_message
        if entity == f"resolved-entity:{self.name}":
            if self.fallback_error is not None:
                raise self.fallback_error
            return self.fallback_message
        raise AssertionError(
            f"unexpected entity={entity!r} ids={ids!r} client={self.name!r}"
        )

    async def get_entity(self, source_url):
        if source_url != "https://t.me/test_channel":
            raise AssertionError(
                f"unexpected source_url={source_url!r} client={self.name!r}"
            )
        self.entity_calls.append(source_url)
        return f"resolved-entity:{self.name}"


def _run_worker_once(monkeypatch, fake_client, *, fallback_enabled=False):
    monkeypatch.setattr(listener.config, "WATCH_VIEWS_ENABLED", True)
    monkeypatch.setattr(listener.config, "WATCH_VIEWS_SOURCE_FALLBACK_ENABLED", fallback_enabled)
    monkeypatch.setattr(listener.config, "WATCH_VIEWS_MAX_MATCH_AGE_HOURS", 0)
    monkeypatch.setattr(listener, "COVERAGE_POLL_TICK_SEC", 0)
    monkeypatch.setattr(listener, "iter_ready_pool_clients", lambda: [SimpleNamespace(client=fake_client)])
    monkeypatch.setattr(listener, "session_name", lambda cli: "tg_session_11")
    monkeypatch.setattr(listener, "find_slot_by_session_name", lambda _name: None)
    monkeypatch.setattr(listener.watch_posts_db, "get_watch_source_url", lambda wid: "https://t.me/test_channel")
    monkeypatch.setattr(listener, "_trace", lambda *args, **kwargs: None)

    tick_state = {"calls": 0}

    def _list_due_coverage():
        tick_state["calls"] += 1
        if tick_state["calls"] == 1:
            return [(8116, 1801542020, 31428, "tg_session_11")]
        raise asyncio.CancelledError

    monkeypatch.setattr(listener.watch_proc_db, "list_due_coverage", _list_due_coverage)

    async def _noop_sleep(_seconds):
        return None

    monkeypatch.setattr(listener.asyncio, "sleep", _noop_sleep)
    asyncio.run(listener._views_worker())


def _run_worker_once_with_slots(
    monkeypatch,
    slots,
    *,
    due_rows,
    source_url,
    source_session,
    fallback_enabled=False,
    max_match_age_hours=0,
    matched_at_text="2026-03-23 00:00:00",
):
    monkeypatch.setattr(listener.config, "WATCH_VIEWS_ENABLED", True)
    monkeypatch.setattr(listener.config, "WATCH_VIEWS_SOURCE_FALLBACK_ENABLED", fallback_enabled)
    monkeypatch.setattr(listener.config, "WATCH_VIEWS_MAX_MATCH_AGE_HOURS", max_match_age_hours)
    monkeypatch.setattr(listener, "COVERAGE_POLL_TICK_SEC", 0)
    monkeypatch.setattr(listener, "iter_ready_pool_clients", lambda: slots)
    monkeypatch.setattr(listener, "session_name", lambda cli: cli.name)
    monkeypatch.setattr(
        listener,
        "find_slot_by_session_name",
        lambda name: next((slot for slot in slots if getattr(slot.client, "name", None) == name), None),
    )
    monkeypatch.setattr(listener.watch_posts_db, "get_watch_source_url", lambda wid: source_url)
    monkeypatch.setattr(listener.watch_posts_db, "get_watch_info", lambda wid: {"matched_at": matched_at_text})
    monkeypatch.setattr(listener.watch_proc_db, "get_session_for_source_url", lambda url: source_session)
    monkeypatch.setattr(listener, "_trace", lambda *args, **kwargs: None)

    tick_state = {"calls": 0}

    def _list_due_coverage():
        tick_state["calls"] += 1
        if tick_state["calls"] == 1:
            return list(due_rows)
        raise asyncio.CancelledError

    monkeypatch.setattr(listener.watch_proc_db, "list_due_coverage", _list_due_coverage)

    async def _noop_sleep(_seconds):
        return None

    monkeypatch.setattr(listener.asyncio, "sleep", _noop_sleep)
    asyncio.run(listener._views_worker())


def test_views_worker_recovers_nil_message_via_source_url(monkeypatch):
    fake_client = _FakeClient(fallback_message=_FakeMessage(views=321))
    done_calls = []
    access_lost_calls = []
    inserted_events = []

    monkeypatch.setattr(listener.watch_proc_db, "mark_done_views", lambda watch_id, views: done_calls.append((watch_id, views)))
    monkeypatch.setattr(listener.watch_proc_db, "mark_views_access_lost", lambda watch_id: access_lost_calls.append(watch_id) or True)
    monkeypatch.setattr(
        listener.watch_events_db,
        "insert_watch_event",
        lambda watch_id, event_type, payload: inserted_events.append((watch_id, event_type, json.loads(payload))),
    )

    _run_worker_once(monkeypatch, fake_client, fallback_enabled=True)

    assert done_calls == [(8116, 321)]
    assert access_lost_calls == []
    assert len(inserted_events) == 1
    assert inserted_events[0][1] == "views"
    assert inserted_events[0][2]["views"] == 321


def test_views_worker_marks_access_lost_when_nil_message_persists(monkeypatch):
    fake_client = _FakeClient(fallback_message=None)
    done_calls = []
    access_lost_calls = []
    inserted_events = []

    monkeypatch.setattr(listener.watch_proc_db, "mark_done_views", lambda watch_id, views: done_calls.append((watch_id, views)))
    monkeypatch.setattr(listener.watch_proc_db, "mark_views_access_lost", lambda watch_id: access_lost_calls.append(watch_id) or True)
    monkeypatch.setattr(
        listener.watch_events_db,
        "insert_watch_event",
        lambda watch_id, event_type, payload: inserted_events.append((watch_id, event_type, json.loads(payload))),
    )

    _run_worker_once(monkeypatch, fake_client, fallback_enabled=True)

    assert done_calls == []
    assert access_lost_calls == [8116]
    assert len(inserted_events) == 1
    assert inserted_events[0][1] == "views_access_lost"
    assert inserted_events[0][2]["status"] == "message_not_found"
    assert inserted_events[0][2]["source_url"] == "https://t.me/test_channel"


def test_views_worker_reroutes_to_current_source_session_when_matched_session_is_stale(
    monkeypatch,
):
    stale_client = _RerouteClient("tg_session_11", direct_error=True)
    current_client = _RerouteClient(
        "tg_session_12",
        fallback_message=_FakeMessage(views=777),
    )
    done_calls = []
    access_lost_calls = []
    inserted_events = []

    monkeypatch.setattr(
        listener.watch_proc_db,
        "mark_done_views",
        lambda watch_id, views: done_calls.append((watch_id, views)),
    )
    monkeypatch.setattr(
        listener.watch_proc_db,
        "mark_views_access_lost",
        lambda watch_id: access_lost_calls.append(watch_id) or True,
    )
    monkeypatch.setattr(
        listener.watch_events_db,
        "insert_watch_event",
        lambda watch_id, event_type, payload: inserted_events.append(
            (watch_id, event_type, json.loads(payload))
        ),
    )

    _run_worker_once_with_slots(
        monkeypatch,
        [
            SimpleNamespace(client=stale_client),
            SimpleNamespace(client=current_client),
        ],
        due_rows=[(8116, 1801542020, 31428, "tg_session_11")],
        source_url="https://t.me/test_channel",
        source_session="tg_session_12",
        fallback_enabled=True,
    )

    assert done_calls == [(8116, 777)]
    assert access_lost_calls == []
    assert len(inserted_events) == 1
    assert inserted_events[0][1] == "views"
    assert inserted_events[0][2]["views"] == 777
    assert stale_client.entity_calls == []
    assert current_client.entity_calls == ["https://t.me/test_channel"]


def test_views_worker_recovers_invite_watch_via_rerouted_channel_without_entity_resolve(
    monkeypatch,
):
    stale_client = _RerouteClient("tg_session_11", direct_error=True)
    current_client = _RerouteClient(
        "tg_session_12",
        direct_message=_FakeMessage(views=654),
    )
    done_calls = []
    access_lost_calls = []
    inserted_events = []

    monkeypatch.setattr(
        listener.watch_proc_db,
        "mark_done_views",
        lambda watch_id, views: done_calls.append((watch_id, views)),
    )
    monkeypatch.setattr(
        listener.watch_proc_db,
        "mark_views_access_lost",
        lambda watch_id: access_lost_calls.append(watch_id) or True,
    )
    monkeypatch.setattr(
        listener.watch_events_db,
        "insert_watch_event",
        lambda watch_id, event_type, payload: inserted_events.append(
            (watch_id, event_type, json.loads(payload))
        ),
    )

    _run_worker_once_with_slots(
        monkeypatch,
        [
            SimpleNamespace(client=stale_client),
            SimpleNamespace(client=current_client),
        ],
        due_rows=[(8116, 1801542020, 31428, "tg_session_11")],
        source_url="https://t.me/+invite_hash_123",
        source_session="tg_session_12",
        fallback_enabled=True,
    )

    assert done_calls == [(8116, 654)]
    assert access_lost_calls == []
    assert len(inserted_events) == 1
    assert inserted_events[0][1] == "views"
    assert inserted_events[0][2]["views"] == 654
    assert stale_client.entity_calls == []
    assert current_client.entity_calls == []


def test_views_worker_reschedules_retry_on_transient_direct_error(monkeypatch):
    class _TransientClient:
        name = "tg_session_11"

        async def get_messages(self, entity, ids):
            raise ConnectionError("network down")

    done_calls = []
    access_lost_calls = []
    retry_calls = []
    inserted_events = []

    monkeypatch.setattr(listener, "moscow_now", lambda: listener.datetime(2026, 3, 23, 0, 10, 0))
    monkeypatch.setattr(
        listener.watch_proc_db,
        "mark_done_views",
        lambda watch_id, views: done_calls.append((watch_id, views)),
    )
    monkeypatch.setattr(
        listener.watch_proc_db,
        "mark_views_access_lost",
        lambda watch_id: access_lost_calls.append(watch_id) or True,
    )
    monkeypatch.setattr(
        listener.watch_proc_db,
        "reschedule_coverage_check",
        lambda watch_id, next_retry_at: retry_calls.append((watch_id, next_retry_at)) or True,
    )
    monkeypatch.setattr(
        listener.watch_events_db,
        "insert_watch_event",
        lambda watch_id, event_type, payload: inserted_events.append(
            (watch_id, event_type, json.loads(payload))
        ),
    )

    _run_worker_once_with_slots(
        monkeypatch,
        [SimpleNamespace(client=_TransientClient())],
        due_rows=[(8116, 1801542020, 31428, "tg_session_11")],
        source_url=None,
        source_session=None,
    )

    assert done_calls == []
    assert access_lost_calls == []
    assert retry_calls == [(8116, "2026-03-23 00:14:00")]
    assert len(inserted_events) == 1
    assert inserted_events[0][1] == "views_retry_scheduled"
    assert inserted_events[0][2]["error_type"] == "ConnectionError"
    assert inserted_events[0][2]["next_retry_at"] == "2026-03-23 00:14:00"


def test_views_worker_reschedules_retry_after_flood_wait(monkeypatch):
    class _FloodClient:
        name = "tg_session_11"

        async def get_messages(self, entity, ids):
            raise listener.FloodWaitError(request=None, capture=280)

    done_calls = []
    access_lost_calls = []
    retry_calls = []
    inserted_events = []

    monkeypatch.setattr(listener, "moscow_now", lambda: listener.datetime(2026, 3, 23, 0, 10, 0))
    monkeypatch.setattr(
        listener.watch_proc_db,
        "mark_done_views",
        lambda watch_id, views: done_calls.append((watch_id, views)),
    )
    monkeypatch.setattr(
        listener.watch_proc_db,
        "mark_views_access_lost",
        lambda watch_id: access_lost_calls.append(watch_id) or True,
    )
    monkeypatch.setattr(
        listener.watch_proc_db,
        "reschedule_coverage_check",
        lambda watch_id, next_retry_at: retry_calls.append((watch_id, next_retry_at)) or True,
    )
    monkeypatch.setattr(
        listener.watch_events_db,
        "insert_watch_event",
        lambda watch_id, event_type, payload: inserted_events.append(
            (watch_id, event_type, json.loads(payload))
        ),
    )

    _run_worker_once_with_slots(
        monkeypatch,
        [SimpleNamespace(client=_FloodClient())],
        due_rows=[(8116, 1801542020, 31428, "tg_session_11")],
        source_url=None,
        source_session=None,
    )

    assert done_calls == []
    assert access_lost_calls == []
    assert retry_calls == [(8116, "2026-03-23 00:15:10")]
    assert len(inserted_events) == 1
    assert inserted_events[0][1] == "views_retry_scheduled"
    assert inserted_events[0][2]["error_type"] == "FloodWaitError"
    assert inserted_events[0][2]["flood_wait_sec"] == 280
    assert inserted_events[0][2]["retry_delay_sec"] == 310
    assert inserted_events[0][2]["next_retry_at"] == "2026-03-23 00:15:10"


def test_views_worker_reschedules_retry_when_fallback_path_has_transient_error(monkeypatch):
    client = _RerouteClient(
        "tg_session_11",
        fallback_error=ConnectionError("temporary transport issue"),
    )
    done_calls = []
    access_lost_calls = []
    retry_calls = []
    inserted_events = []

    monkeypatch.setattr(listener, "moscow_now", lambda: listener.datetime(2026, 3, 23, 0, 10, 0))
    monkeypatch.setattr(
        listener.watch_proc_db,
        "mark_done_views",
        lambda watch_id, views: done_calls.append((watch_id, views)),
    )
    monkeypatch.setattr(
        listener.watch_proc_db,
        "mark_views_access_lost",
        lambda watch_id: access_lost_calls.append(watch_id) or True,
    )
    monkeypatch.setattr(
        listener.watch_proc_db,
        "reschedule_coverage_check",
        lambda watch_id, next_retry_at: retry_calls.append((watch_id, next_retry_at)) or True,
    )
    monkeypatch.setattr(
        listener.watch_events_db,
        "insert_watch_event",
        lambda watch_id, event_type, payload: inserted_events.append(
            (watch_id, event_type, json.loads(payload))
        ),
    )

    _run_worker_once_with_slots(
        monkeypatch,
        [SimpleNamespace(client=client)],
        due_rows=[(8116, 1801542020, 31428, "tg_session_11")],
        source_url="https://t.me/test_channel",
        source_session="tg_session_11",
        fallback_enabled=True,
    )

    assert done_calls == []
    assert access_lost_calls == []
    assert retry_calls == [(8116, "2026-03-23 00:14:00")]
    assert len(inserted_events) == 1
    assert inserted_events[0][1] == "views_retry_scheduled"
    assert inserted_events[0][2]["error_type"] == "ConnectionError"
    assert inserted_events[0][2]["source_url"] == "https://t.me/test_channel"


def test_views_worker_marks_old_matched_watch_without_network_call(monkeypatch):
    class _UnexpectedNetworkClient:
        name = "tg_session_11"

        async def get_messages(self, entity, ids):
            raise AssertionError("network call must be skipped for old matched watch")

    access_lost_calls = []
    inserted_events = []

    monkeypatch.setattr(listener, "moscow_now", lambda: listener.datetime(2026, 3, 24, 12, 0, 0))
    monkeypatch.setattr(
        listener.watch_proc_db,
        "mark_views_access_lost",
        lambda watch_id: access_lost_calls.append(watch_id) or True,
    )
    monkeypatch.setattr(
        listener.watch_events_db,
        "insert_watch_event",
        lambda watch_id, event_type, payload: inserted_events.append(
            (watch_id, event_type, json.loads(payload))
        ),
    )

    _run_worker_once_with_slots(
        monkeypatch,
        [SimpleNamespace(client=_UnexpectedNetworkClient())],
        due_rows=[(8116, 1801542020, 31428, "tg_session_11")],
        source_url="https://t.me/test_channel",
        source_session="tg_session_11",
        max_match_age_hours=24,
        matched_at_text="2026-03-19 20:00:00",
    )

    assert access_lost_calls == [8116]
    assert len(inserted_events) == 1
    assert inserted_events[0][1] == "views_access_lost"
    assert inserted_events[0][2]["status"] == "matched_too_old"
