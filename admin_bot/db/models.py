from __future__ import annotations

from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Text,
    UniqueConstraint,
    Float,
    delete,
    select,
)
import time
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session, relationship, foreign
from sqlalchemy.sql import text

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

    # Двосторонній зв'язок не налаштований через відсутність явних FK у схемі.


class Membership(Base):
    __tablename__ = "membership"
    __table_args__ = (
        UniqueConstraint("channel_id", "account", name="pk_membership"),
    )

    channel_id = Column(Integer, primary_key=True)
    account = Column(String, primary_key=True)
    status = Column(String, nullable=False)
    ts = Column(Integer, nullable=False)


def upsert_membership(db: Session, channel_id: int, account: str, status: str) -> None:
    """Зберігає статус підписки для пари (channel_id, account)."""
    now = int(time.time())
    row = (
        db.query(Membership)
        .filter(
            Membership.channel_id == channel_id,
            Membership.account == account,
        )
        .one_or_none()
    )
    if row:
        row.status = status
        row.ts = now
    else:
        db.add(Membership(channel_id=channel_id, account=account, status=status, ts=now))
    db.commit()


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
    tg_id = Column(BigInteger, unique=True, index=True, nullable=True)
    username = Column(String)
    display = Column(String)
    is_new = Column(Integer, default=0)
    cpm = Column(Float)
    price = Column(Float)
    subscribers = Column(Integer)

    channels = relationship(
        "AdminChannel",
        primaryjoin="Admin.id==foreign(AdminChannel.admin_id)",
        lazy="selectin",
        viewonly=True,
    )


class AdminChannel(Base):
    __tablename__ = "admin_channels"
    __table_args__ = (
        UniqueConstraint("admin_id", "channel_id", name="uq_admin_channel"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_id = Column(Integer, nullable=False)
    channel_id = Column(Integer, nullable=False)


class Network(Base):
    __tablename__ = "networks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_id = Column(Integer, nullable=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    created_at = Column(Integer)
    updated_at = Column(Integer)
    subscribers = Column(Integer)
    price_negotiated = Column(Float)
    cpm_negotiated = Column(Float)
    actual_price = Column(Float)
    actual_cpm = Column(Float)
    actual_views = Column(Integer)


class NetworkChannel(Base):
    __tablename__ = "network_channels"
    __table_args__ = (
        UniqueConstraint("network_id", "channel_id", name="uq_network_channel"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    network_id = Column(Integer, nullable=False)
    channel_id = Column(Integer, nullable=False)
    price = Column(Float)
    currency = Column(String)
    cpm = Column(Float)  # задається вручну
    expected_views = Column(Integer)  # очікувані перегляди
    actual_views = Column(Integer)  # фактичні середні перегляди
    avg_views_30d = Column(Integer)  # середні перегляди за 30 днів
    last_views = Column(Integer)  # перегляди останнього поста
    theme = Column(String)  # тематика/теги
    note = Column(Text)
    created_at = Column(Integer)
    updated_at = Column(Integer)


# ------------------ Helper-функції видалення ------------------ #


def delete_admin_channels_by_admin(db: Session, admin_id: int) -> int:
    return db.execute(delete(AdminChannel).where(AdminChannel.admin_id == admin_id)).rowcount or 0


def delete_network_channels_by_networks(db: Session, net_ids: List[int]) -> int:
    if not net_ids:
        return 0
    return db.execute(delete(NetworkChannel).where(NetworkChannel.network_id.in_(net_ids))).rowcount or 0


def delete_networks_by_admin(db: Session, admin_id: int) -> Tuple[int, List[int]]:
    net_ids = list(db.execute(select(Network.id).where(Network.admin_id == admin_id)).scalars().all())
    if net_ids:
        db.execute(delete(Network).where(Network.id.in_(net_ids)))
    return len(net_ids), net_ids


def delete_admin_by_id(db: Session, admin_id: int) -> int:
    return db.execute(delete(Admin).where(Admin.id == admin_id)).rowcount or 0


def delete_memberships_by_channels(db: Session, chan_ids: List[int]) -> int:
    if not chan_ids:
        return 0
    return db.execute(delete(Membership).where(Membership.channel_id.in_(chan_ids))).rowcount or 0


def delete_membership_status_by_channels(db: Session, chan_ids: List[int]) -> int:
    if not chan_ids:
        return 0
    try:
        placeholders = ",".join([str(cid) for cid in chan_ids])
        return db.execute(text(f"DELETE FROM membership_status WHERE channel_id IN ({placeholders})")).rowcount or 0
    except Exception:
        return 0


def delete_invite_status_by_hashes(db: Session, hashes: List[str]) -> int:
    if not hashes:
        return 0
    return db.execute(delete(InviteStatus).where(InviteStatus.invite_hash.in_(hashes))).rowcount or 0


def delete_invite_map_by_channels(db: Session, chan_ids: List[int]) -> int:
    if not chan_ids:
        return 0
    return db.execute(delete(InviteMap).where(InviteMap.channel_id.in_(chan_ids))).rowcount or 0


def delete_owner_conflict_by_channels(db: Session, chan_ids: List[int]) -> int:
    if not chan_ids:
        return 0
    return db.execute(delete(OwnerConflict).where(OwnerConflict.channel_id.in_(chan_ids))).rowcount or 0


def delete_links_by_channels(db: Session, chan_ids: List[int]) -> int:
    if not chan_ids:
        return 0
    return db.execute(delete(Link).where(Link.channel_id.in_(chan_ids))).rowcount or 0


def delete_channels_by_ids(db: Session, chan_ids: List[int]) -> int:
    if not chan_ids:
        return 0
    return db.execute(delete(Channel).where(Channel.channel_id.in_(chan_ids))).rowcount or 0


def delete_invite_owners_and_links_no_channel(
    db: Session, owner_disp: Optional[str], owner_user: Optional[str]
) -> Tuple[int, int]:
    where_raw = []
    params_raw = {}
    if owner_disp:
        where_raw.append("owner_display = :od")
        params_raw["od"] = owner_disp
    if owner_user:
        where_raw.append("owner_username = :ou")
        params_raw["ou"] = owner_user
    if not where_raw:
        return 0, 0
    where_expr = " OR ".join(where_raw)
    invite_owners_deleted = db.execute(
        text(f"DELETE FROM invite_owners WHERE {where_expr}"),
        params_raw,
    ).rowcount or 0
    links_no_channel_deleted = db.execute(
        text(f"DELETE FROM links WHERE channel_id IS NULL AND ({where_expr})"),
        params_raw,
    ).rowcount or 0
    return invite_owners_deleted, links_no_channel_deleted
