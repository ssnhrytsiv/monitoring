import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import models as m
from app.DAL import channels_operations as ch_db
from app.DAL.channels_operations import (
    ChannelRecord,
    RecentChannel,
    RecentLink,
)
from app.DAL.schemas import LinkRecord
from app.DAL.schemas.channel import ChannelOwner


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    db_path = tmp_path / "channels.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    m.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, autoflush=False, autocommit=False)
    sess = Session()
    try:
        yield sess
    finally:
        sess.close()


def test_upsert_channel_overwrite_rules(db_session):
    ch_db.upsert_channel(db_session, channel_id=1, username="u1", title="t1", owner_admin_id=None)
    ch_db.upsert_channel(db_session, channel_id=1, username="u2", title=None, owner_admin_id=5)
    row = db_session.query(m.Channel).filter(m.Channel.channel_id == 1).one()
    # username/title не перетираються, owner_admin_id заповнюється один раз
    assert row.username == "u1"
    assert row.title == "t1"
    assert row.owner_admin_id == 5


def test_upsert_channel_full_keeps_existing(db_session):
    ch_db.upsert_channel_full(db_session, channel_id=2, username="uA", title="tA", owner_admin_id=7)
    ch_db.upsert_channel_full(db_session, channel_id=2, username="uB", title="tB", owner_admin_id=8, last_status="ok")
    row = db_session.query(m.Channel).filter(m.Channel.channel_id == 2).one()
    assert row.username == "uA"
    assert row.title == "tA"
    assert row.owner_admin_id == 7
    assert row.last_status == "ok"


def test_get_channel_by_username(db_session):
    ch_db.upsert_channel(db_session, channel_id=10, username="demo_user", title=None, owner_admin_id=None)
    cid_by_username = ch_db.get_channel_id_by_username(db_session, "Demo_User")
    assert cid_by_username == 10


def test_add_link_and_find_channel(db_session):
    ch_db.upsert_channel(db_session, channel_id=20, username="chan", title="Chan", owner_admin_id=None)
    ch_db.add_link(
        db_session,
        channel_id=20,
        raw_url="https://t.me/+abc",
        kind="invite",
        batch_msg_id=1,
    )
    link = db_session.query(m.Link).one()
    assert link.url_norm == "https://t.me/+abc"

    found = ch_db.find_channel_by_link(db_session, "https://t.me/+abc")
    assert isinstance(found, LinkRecord)
    assert found.channel_id == 20
    assert found.title == "Chan"


def test_links_by_channel_ids(db_session):
    ch_db.upsert_channel(db_session, channel_id=30, username="user1", title=None, owner_admin_id=None)
    result = ch_db.get_links_by_channel_ids(db_session, [30])
    assert result[30] == "https://t.me/user1"


def test_get_owners_by_channel_ids(db_session):
    admin = m.Admin(display="Alice", username="alice")
    db_session.add(admin)
    db_session.commit()
    ch_db.upsert_channel(db_session, channel_id=40, username=None, title=None, owner_admin_id=admin.id)
    ch_db.upsert_channel(db_session, channel_id=41, username=None, title=None, owner_admin_id=None)

    owners = ch_db.get_owners_by_channel_ids(db_session, [40, 41])
    assert all(isinstance(o, ChannelOwner) for o in owners)
    owners_map = {o.channel_id: o.owner_label for o in owners}
    assert owners_map[40] == "Alice"
    assert 41 not in owners_map


def test_get_channel_owner_info(db_session):
    admin = m.Admin(display="Bob", username="bob")
    db_session.add(admin)
    db_session.commit()
    ch_db.upsert_channel(db_session, channel_id=50, username=None, title=None, owner_admin_id=admin.id)
    info = ch_db.get_channel_owner_info(db_session, 50)
    assert isinstance(info, ChannelOwner)
    assert info.owner_admin_id == admin.id
    assert info.owner_display == "Bob"


def test_get_channel_title_and_owner(db_session):
    admin = m.Admin(display="Carol", username="carol")
    db_session.add(admin)
    db_session.commit()
    ch_db.upsert_channel(db_session, channel_id=60, username=None, title="Title60", owner_admin_id=admin.id)
    res = ch_db.get_channel_title_and_owner(db_session, 60)
    assert isinstance(res, ChannelOwner)
    assert res.title == "Title60"
    assert res.owner_label == "Carol"


def test_recent_links_and_channels(db_session):
    # Links
    ch_db.add_link(db_session, channel_id=None, raw_url="https://t.me/+zzz", kind="invite", batch_msg_id=None)
    links = ch_db.recent_links(db_session, limit=1)
    assert links and isinstance(links[0], RecentLink)
    assert links[0].url_norm == "https://t.me/+zzz"

    # Channels
    admin = m.Admin(display="Dora", username="dora")
    db_session.add(admin)
    db_session.commit()
    ch_db.upsert_channel_full(db_session, channel_id=70, username="uuu", title="T", owner_admin_id=admin.id, last_status="ok")
    channels = ch_db.recent_channels(db_session, limit=1)
    assert channels and isinstance(channels[0], RecentChannel)
    assert channels[0].owner_label == "Dora"

    search = ch_db.search_channels_by_username(db_session, "uu")
    assert search and search[0].channel_id == 70


def test_find_channel_full_record(db_session):
    ch_db.upsert_channel_full(db_session, channel_id=80, username="u80", title="T80", owner_admin_id=None, last_status=None)
    rec = ch_db.find_channel(db_session, 80)
    assert isinstance(rec, ChannelRecord)
    assert rec.username == "u80"


def test_get_channel_id_by_url_norm_and_raw(db_session):
    ch_db.upsert_channel(db_session, channel_id=90, username="u90", title="T90", owner_admin_id=None)
    ch_db.add_link(
        db_session,
        channel_id=90,
        raw_url="https://t.me/u90",
        kind="public",
        batch_msg_id=None,
    )
    cid_norm = ch_db.get_channel_id_by_url(db_session, "https://t.me/u90")
    assert cid_norm == 90
