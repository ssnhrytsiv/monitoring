import os
import tempfile
import time
import json

from app.db.session import Base, engine, SessionLocal
from app.DAL import session_scope
from app.db import models as m
from app.DAL import watch_posts_operations as wp_db
from app.DAL import watch_events_operations as we_db


def _ensure_temp_db():
    if not os.environ.get("SQLALCHEMY_DATABASE_URL"):
        fd, path = tempfile.mkstemp(prefix="watch_posts_test", suffix=".sqlite3")
        os.close(fd)
        os.environ["SQLALCHEMY_DATABASE_URL"] = f"sqlite:///{path}"


def _reset_db():
    _ensure_temp_db()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_create_watch_and_get():
    _reset_db()
    with session_scope() as db:
        wid = wp_db.create_watch(db, channel_id=101, template_id=10, source_url="https://t.me/+abc")
        data = wp_db.get_watch_by_id(db, wid)
    assert data is not None
    _, tpl, status, tw_end, created_by, ch_id, src = data
    assert tpl == 10
    assert status == "pending"
    assert ch_id == 101
    assert src == "https://t.me/+abc"


def test_update_status_and_time_window():
    _reset_db()
    with session_scope() as db:
        wid = wp_db.create_watch(db, channel_id=202, time_window_end="2026-01-01 10:00")
        ok = wp_db.set_watch_status_pending_db(db, wid)
        assert ok is True
        ok = wp_db.update_watch_time_window(db, wid, "2026-01-01 09:00", "2026-01-01 10:30")
        assert ok is True
        _, _, status, tw_end, _, _, _ = wp_db.get_watch_by_id(db, wid)
    assert status == "pending"
    assert str(tw_end).startswith("2026-01-01 10:30")


def test_group_leader_and_load_group_items():
    _reset_db()
    with session_scope() as db:
        wid1 = wp_db.create_watch(db, channel_id=1, template_id=55, time_window_end="2026-01-02 12:00", created_by=5)
        wid2 = wp_db.create_watch(db, channel_id=2, template_id=55, time_window_end="2026-01-02 12:00", created_by=5)
        leader = wp_db.get_group_leader_for_watch(db, wid2)
        tpl, tw_key, created_by, ch = wp_db.get_group_leader_key(db, wid2)
        items = wp_db.load_group_items(db, template_id=55, tw_key="2026-01-02 12:00", created_by=5)
    assert leader == wid1
    assert tpl == 55 and tw_key.startswith("2026-01-02 12") and created_by == 5
    ids = {i[0] for i in items}
    assert wid1 in ids and wid2 in ids


def test_watch_events_insert_and_mark_sent():
    _reset_db()
    with session_scope() as db:
        wid = wp_db.create_watch(db, channel_id=303)
    payload = json.dumps({"watch_id": wid})
    with session_scope() as db:
        we_db.insert_watch_event(db, wid, "matched", payload)
    with session_scope() as db:
        events = we_db.fetch_unsent_events(db)
    assert len(events) == 1
    ev_id, ev_wid, ev_type, ev_payload, created_at = events[0]
    assert ev_wid == wid and ev_type == "matched" and ev_payload == payload
    with session_scope() as db:
        we_db.mark_event_sent(db, ev_id, sent_to=999)
    # після відправки не повинні вертатись
    with session_scope() as db:
        assert we_db.fetch_unsent_events(db) == []


def test_cancel_watch_and_active_filter():
    _reset_db()
    with session_scope() as db:
        wid_keep = wp_db.create_watch(db, channel_id=401)
        wid_cancel = wp_db.create_watch(db, channel_id=402)
        db.query(m.WatchPost).filter(m.WatchPost.id == wid_cancel).update({"status": "cancelled"})
        db.commit()
        items = wp_db.list_active_watches(db, user_id=0)
    ids = {i[0] for i in items}
    assert wid_keep in ids
    assert wid_cancel not in ids


def _force_status(wid: int, status: str):
    with SessionLocal() as db:
        db.query(m.WatchPost).filter(m.WatchPost.id == wid).update({"status": status})
        db.commit()


def test_list_active_watches_filters_statuses():
    _reset_db()
    with session_scope() as db:
        wid_pending = wp_db.create_watch(db, channel_id=501)
        wid_matched = wp_db.create_watch(db, channel_id=502)
        wid_expired = wp_db.create_watch(db, channel_id=503)
    _force_status(wid_matched, "matched")
    _force_status(wid_expired, "expired")

    with session_scope() as db:
        items_default = wp_db.list_active_watches(db, user_id=0)
    ids_default = {i[0] for i in items_default}
    assert wid_pending in ids_default
    assert wid_matched in ids_default
    assert wid_expired not in ids_default

    with session_scope() as db:
        items_matched = wp_db.list_active_watches(db, user_id=0, statuses=["matched"])
    ids_matched = {i[0] for i in items_matched}
    assert ids_matched == {wid_matched}


def test_get_watch_links_or_template_links():
    _reset_db()
    # створюємо шаблон з лінками
    with SessionLocal() as db:
        tpl = m.PostTemplate(
            title="tpl",
            text="sample",
            mode="html",
            threshold=0.9,
            created_at=int(time.time()),
            links=json.dumps(["https://t.me/+abc", "https://t.me/+abc", "https://t.me/+def"]),
        )
        db.add(tpl)
        db.commit()
        tpl_id = tpl.id
    with session_scope() as db:
        wid = wp_db.create_watch(db, channel_id=601, template_id=tpl_id)
        links = wp_db.get_watch_links_or_template_links(db, wid)
    assert links == ["https://t.me/+abc", "https://t.me/+def"]
