import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import models as m
from app.DAL import channels_operations as ch_db
from app.DAL import link_queue_operations as lq_db
from app.DAL import invite_owners_operations as io_db


@pytest.fixture()
def db_session(tmp_path):
    db_path = tmp_path / "test_ext.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    m.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    try:
        yield sess
    finally:
        sess.close()


def test_upsert_channel_full_does_not_override(db_session):
    ch_id = 2001
    ch_db.upsert_channel_full(db_session, channel_id=ch_id, username="u1", title="t1", owner_admin_id=10)
    ch_db.upsert_channel_full(db_session, channel_id=ch_id, username="u2", title=None, owner_admin_id=11)
    row = db_session.query(m.Channel).filter(m.Channel.channel_id == ch_id).one()
    assert row.username == "u1"  # not overwritten
    assert row.title == "t1"
    assert row.owner_admin_id == 10  # first admin kept


def test_add_link_prefers_admin_id(db_session):
    ch_db.add_link(
        db_session,
        channel_id=3001,
        raw_url="https://t.me/+abc",
        kind="invite",
        batch_msg_id=1,
        owner_admin_id=5,
        owner_username="ShouldBeIgnored",
    )
    link = db_session.query(m.Link).one()
    assert link.owner_admin_id == 5
    assert link.owner_username is None

    ch_db.add_link(
        db_session,
        channel_id=None,
        raw_url="https://t.me/username",
        kind=None,
        batch_msg_id=None,
        owner_admin_id=None,
        owner_username="@UserName",
    )
    links = db_session.query(m.Link).order_by(m.Link.id).all()
    assert links[1].owner_admin_id is None
    assert links[1].owner_username == "username"  # normalized


def test_invite_owner_set_and_get(db_session):
    dao = io_db.InviteOwnersDAO(db_session)
    dao.set_invite_owner("hash1", owner_username="owner1", owner_admin_id=None)
    dao.set_invite_owner("hash1", owner_username=None, owner_admin_id=22)
    data = dao.get_invite_owner("hash1")
    assert data.owner_admin_id == 22
    assert data.owner_username is None


def test_link_queue_owner_fields(db_session):
    added = lq_db.enqueue(
        db_session,
        ["https://t.me/+a", "https://t.me/+b"],
        batch_id="b123",
        origin_chat=123,
        origin_msg=456,
        delay_sec=0,
        owner_admin_id=9,
        owner_username="demo",
        adopt_existing=False,
        reset_next_try=True,
    )
    assert added == 2
    items = lq_db.fetch_due(db_session, limit=10)
    assert len(items) == 2
    first = items[0]
    assert first.owner_admin_id == 9
    assert first.owner_username == "demo"

    deleted = lq_db.delete_by_owner(db_session, owner_admin_id=9)
    assert deleted == 2
    assert lq_db.fetch_due(db_session, limit=10) == []
