import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import models as m
from app.DAL import channels_operations as ch_db
from app.DAL import link_queue_operations as lq_db
from app.DAL import invite_owners_operations as io_db
from app.utils.link_parser import extract_links_from_html


@pytest.fixture()
def db_session(tmp_path):
    db_path = tmp_path / "test.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    m.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    try:
        yield sess
    finally:
        sess.close()


def test_upsert_channel_no_display(db_session):
    ch_id = 1001
    ch_db.upsert_channel(db_session, channel_id=ch_id, username="demo", title="Demo", owner_admin_id=1)
    row = db_session.query(m.Channel).filter(m.Channel.channel_id == ch_id).one()
    assert row.owner_admin_id == 1

    # second upsert should not overwrite admin_id or username
    ch_db.upsert_channel(db_session, channel_id=ch_id, username="demo2", title=None, owner_admin_id=None)
    row = db_session.query(m.Channel).filter(m.Channel.channel_id == ch_id).one()
    assert row.username == "demo"
    assert row.owner_admin_id == 1


def test_add_link_respects_owner_admin(db_session):
    lq_db.enqueue(
        db_session,
        ["https://t.me/+abc"],
        batch_id="b1",
        origin_chat=1,
        origin_msg=1,
        owner_admin_id=2,
        owner_username=None,
    )
    row = db_session.query(m.LinkQueue).one()
    assert row.owner_admin_id == 2
    assert row.owner_username is None


def test_invite_owner_storage(db_session):
    h = "hash123"
    io_db.set_invite_owner(db_session, h, owner_admin_id=5, owner_username="user5")
    rec = io_db.get_invite_owner(db_session, h)
    assert rec
    assert rec.owner_admin_id == 5
    assert rec.owner_username == "user5"


def test_extract_links_various():
    html = """
    Text before <a href="https://t.me/+INV123">invite</a>
    @botname and https://t.me/botname?start=1
    tg://resolve?domain=demo
    """
    links = extract_links_from_html(html)
    assert "https://t.me/+INV123" in links
    assert "https://t.me/botname?start=1" in links or "https://t.me/botname" in links
    assert any(link.startswith("tg://resolve?domain=demo") or link.endswith("demo") for link in links)


def test_enqueue_wrapper(db_session):
    count = lq_db.enqueue(
        db_session,
        ["https://t.me/+abc", "@demo_bot"],
        batch_id="b2",
        origin_chat=1,
        origin_msg=2,
        owner_admin_id=3,
        owner_username="demo",
        adopt_existing=True,
        reset_next_try=True,
    )
    assert count == 2
    rows = db_session.query(m.LinkQueue).order_by(m.LinkQueue.id.asc()).all()
    assert [r.url for r in rows] == ["https://t.me/+abc", "@demo_bot"]
    assert all(r.owner_admin_id == 3 for r in rows)
    assert all(r.owner_username == "demo" for r in rows)
