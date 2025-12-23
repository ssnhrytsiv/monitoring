from __future__ import annotations

from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from admin_bot.db.session import Base


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(BigInteger, unique=True, index=True)
    username = Column(String)
    title = Column(String)
    owner_display = Column(String)
    owner_username = Column(String)
    last_status = Column(String)
    created_at = Column(String)
    updated_at = Column(String)

    links = relationship(
        "Link",
        primaryjoin="Channel.channel_id==foreign(Link.channel_id)",
        back_populates="channel",
        lazy="selectin",
        viewonly=True,
    )


class Link(Base):
    __tablename__ = "links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(BigInteger, index=True)
    raw_url = Column(Text)
    kind = Column(String)
    batch_msg_id = Column(BigInteger)
    owner_display = Column(String)
    owner_username = Column(String)
    added_at = Column(String)

    channel = relationship(
        "Channel",
        primaryjoin="Link.channel_id==foreign(Channel.channel_id)",
        back_populates="links",
        lazy="joined",
        uselist=False,
        viewonly=True,
    )


class Membership(Base):
    __tablename__ = "membership"
    __table_args__ = (
        UniqueConstraint("channel_id", "account", name="pk_membership"),
    )

    channel_id = Column(Integer, primary_key=True)
    account = Column(String, primary_key=True)
    status = Column(String, nullable=False)
    ts = Column(Integer, nullable=False)


class LinkQueue(Base):
    __tablename__ = "link_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(Text, nullable=False)
    state = Column(String, nullable=False)  # queued | processing | done | failed
    tries = Column(Integer, nullable=False, default=0)
    added_ts = Column(Integer, nullable=False)
    next_try_ts = Column(Integer, nullable=False)
    last_error = Column(Text)
    batch_id = Column(String)
    origin_chat = Column(BigInteger)
    origin_msg = Column(BigInteger)
    owner_display = Column(String)
    owner_username = Column(String)


class InviteMap(Base):
    __tablename__ = "invite_map"

    invite_hash = Column(String, primary_key=True)
    channel_id = Column(Integer)
    title = Column(String)
    updated_at = Column(Integer)


class InviteStatus(Base):
    __tablename__ = "invite_status"

    invite_hash = Column(String, primary_key=True)
    status = Column(String, nullable=False)
    ts = Column(Integer, nullable=False)


class OwnerConflict(Base):
    __tablename__ = "owner_conflicts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner = Column(String, nullable=False)
    channel_id = Column(Integer)
    source_ref = Column(String)
    reason = Column(String, nullable=False)
    created_at = Column(Integer, nullable=False)


# Нові таблиці для admin-bot (не впливають на існуючі схеми)
class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tg_id = Column(BigInteger, unique=True, index=True, nullable=False)
    username = Column(String)
    display = Column(String)

    channels = relationship("AdminChannel", back_populates="admin", cascade="all, delete-orphan")


class AdminChannel(Base):
    __tablename__ = "admin_channels"
    __table_args__ = (
        UniqueConstraint("admin_id", "channel_id", name="uq_admin_channel"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_id = Column(Integer, nullable=False)
    channel_id = Column(Integer, nullable=False)

    admin = relationship("Admin", back_populates="channels")
