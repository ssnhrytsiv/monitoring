import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import models as m
from app.DAL import channels_operations as ch_db
from app.DAL import link_queue_operations as lq_db


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
    )
    link = db_session.query(m.Link).one()
    assert link.url_norm == "https://t.me/+abc"

    ch_db.add_link(
        db_session,
        channel_id=None,
        raw_url="https://t.me/username",
        kind=None,
        batch_msg_id=None,
    )
    links = db_session.query(m.Link).order_by(m.Link.id).all()
    assert links[1].url_norm == "https://t.me/username"


def test_link_queue_owner_fields(db_session):
    added = lq_db.enqueue(
        db_session,
        ["https://t.me/+a", "https://t.me/+b"],
        batch_id="b123",
        origin_msg=456,
        delay_sec=0,
        owner_admin_id=9,
        adopt_existing=False,
        reset_next_try=True,
    )
    assert added == 2
    items = lq_db.fetch_due(db_session, limit=10)
    assert len(items) == 2
    first = items[0]
    assert first.owner_admin_id == 9

    deleted = lq_db.delete_by_owner(db_session, owner_admin_id=9)
    assert deleted == 2
    assert lq_db.fetch_due(db_session, limit=10) == []
