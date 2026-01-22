import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import models as m
from app.DAL import channels_operations as ch_db
from app.DAL import link_queue_operations as lq_db
from app.DAL import membership_operations as mem_db
from app.DAL import invite_cache_operations as ic_db


@pytest.fixture()
def db_session(tmp_path):
    db_path = tmp_path / "dao.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    m.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    try:
        yield sess
    finally:
        sess.close()


def test_find_channel_by_link(db_session):
    ch_db.upsert_channel(db_session, channel_id=501, username="testchn", title="Test", owner_admin_id=None)
    ch_db.add_link(
        db_session,
        channel_id=501,
        raw_url="https://t.me/+abcd",
        kind="invite",
        batch_msg_id=None,
    )
    found = ch_db.find_channel_by_link(db_session, "https://t.me/+abcd")
    assert found and found.channel_id == 501 and found.title == "Test"


def test_link_queue_flow(db_session):
    added = lq_db.enqueue(
        db_session,
        ["https://t.me/+x1", "https://t.me/+x2"],
        batch_id="batchA",
        origin_msg=222,
        delay_sec=0,
        owner_admin_id=7,
        adopt_existing=False,
        reset_next_try=True,
    )
    assert added == 2

    due = lq_db.fetch_batch_due(db_session, "batchA", limit=10)
    assert len(due) == 2
    item_id = due[0].id

    lq_db.mark_processing(db_session, item_id)
    row = db_session.query(m.LinkQueue).filter(m.LinkQueue.id == item_id).one()
    assert row.state == "processing"

    lq_db.mark_failed(db_session, item_id, "err", backoff_sec=1, max_retries=1)
    row = db_session.query(m.LinkQueue).filter(m.LinkQueue.id == item_id).one()
    assert row.state == "failed"
    assert row.last_error == "err"

    lq_db.mark_done(db_session, due[1].id)
    row = db_session.query(m.LinkQueue).filter(m.LinkQueue.id == due[1].id).one()
    assert row.state == "done"


def test_link_queue_adopt_existing(db_session):
    lq_db.enqueue(db_session, ["https://t.me/+dup"], batch_id="b1", origin_msg=None, delay_sec=0, owner_admin_id=None)
    # second enqueue same url with adopt_existing should update existing row, not create new
    added = lq_db.enqueue(
        db_session,
        ["https://t.me/+dup"],
        batch_id="b2",
        origin_msg=2,
        delay_sec=0,
        owner_admin_id=5,
        adopt_existing=True,
        reset_next_try=False,
    )
    assert added == 1
    rows = db_session.query(m.LinkQueue).order_by(m.LinkQueue.id.asc()).all()
    assert len(rows) == 2  # duplicates allowed (no UNIQUE), latest row carries new owner info
    latest = rows[-1]
    assert latest.batch_id == "b2"
    assert latest.owner_admin_id == 5


def test_delete_by_owner_username(db_session):
    lq_db.enqueue(db_session, ["https://t.me/+del"], batch_id=None, origin_msg=None, delay_sec=0, owner_admin_id=5)
    lq_db.enqueue(db_session, ["https://t.me/+keep"], batch_id=None, origin_msg=None, delay_sec=0, owner_admin_id=1)
    deleted = lq_db.delete_by_owner(db_session, owner_admin_id=5)
    assert deleted == 1
    remaining = lq_db.fetch_due(db_session, limit=10)
    assert len(remaining) == 1
    assert remaining[0].url == "https://t.me/+keep"


def test_membership_upsert(db_session):
    mem_db.upsert_membership(db_session, account="acc1", channel_id=77, status="joined")
    row = db_session.query(m.Membership).filter(m.Membership.channel_id == 77, m.Membership.account == "acc1").one()
    assert row.status == "joined"
    mem_db.upsert_membership(db_session, account="acc1", channel_id=77, status="left")
    row = db_session.query(m.Membership).filter(m.Membership.channel_id == 77, m.Membership.account == "acc1").one()
    assert row.status == "left"


def test_invite_cache_upsert_and_get(db_session):
    ic_db.invite_cache_upsert(db_session, "https://t.me/+AAA111", channel_id=10, title="Chan", status="queued", session="sess1")
    res = ic_db.invite_cache_get(db_session, "AAA111")
    assert res is not None
    assert res.channel_id == 10
    assert res.title == "Chan"
    assert res.status == "queued"
    assert res.session == "sess1"

    # update existing entry
    ic_db.invite_cache_upsert(db_session, "AAA111", status="joined", session="sess2", last_error="ok")
    res2 = ic_db.invite_cache_get(db_session, "https://t.me/+AAA111")
    assert res2 is not None
    assert res2.status == "joined"
    assert res2.session == "sess2"
    assert res2.last_error == "ok"


def test_invite_cache_map_and_status_helpers(db_session):
    ic_db.map_invite_set(db_session, "https://t.me/+BBB222", channel_id=20, title="Bbb")
    map_rec = ic_db.map_invite_get(db_session, "BBB222")
    assert map_rec
    cid, title = map_rec
    assert cid == 20
    assert title == "Bbb"

    ic_db.invite_cache_status_put(db_session, "BBB222", "queued")
    assert ic_db.invite_cache_status_get(db_session, "https://t.me/+BBB222") == "queued"


def test_invite_status_delete_filtered(db_session):
    ic_db.invite_cache_upsert(db_session, "h1", status="queued")
    ic_db.invite_cache_upsert(db_session, "h2", status="failed")
    ic_db.invite_cache_upsert(db_session, "h3", status="failed")

    deleted = ic_db.invite_cache_status_delete(db_session, ["h1", "h2", "h3"], statuses=["failed"])
    assert deleted == 2
    # h1 should remain
    rec_h1 = ic_db.invite_cache_get(db_session, "h1")
    assert rec_h1 and rec_h1.status == "queued"
    assert ic_db.invite_cache_get(db_session, "h2") is None
    assert ic_db.invite_cache_get(db_session, "h3") is None
