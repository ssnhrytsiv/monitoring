import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import models as m
from app.DAL import network_channels_operations as nc_db


@pytest.fixture()
def db_session(tmp_path):
    db_path = tmp_path / "net_channels.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    m.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    try:
        yield sess
    finally:
        sess.close()


def test_get_network_for_channel(db_session):
    # prepare network and channel mapping
    net = m.Network(name="net1", admin_id=11)
    db_session.add(net)
    db_session.commit()
    db_session.add(m.NetworkChannel(channel_id=123, network_id=net.id))
    db_session.commit()

    result = nc_db.get_network_for_channel(db_session, 123)
    assert result is not None
    assert result.network_id == net.id
    assert result.admin_id == 11

    # non-existing channel
    assert nc_db.get_network_for_channel(db_session, 999) is None
