from __future__ import annotations

import time
from typing import List, Optional, Tuple

from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Text,
    ForeignKey,
    UniqueConstraint,
    Float,
    delete,
    select,
    Index,
    PrimaryKeyConstraint,
)
from sqlalchemy.orm import Session, relationship
from sqlalchemy.sql import text

from app.db.session import Base


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(BigInteger, unique=True, index=True)
    order_index = Column(BigInteger, index=True)
    username = Column(String)
    title = Column(String)
    owner_admin_id = Column(Integer)
    last_status = Column(String)
    updated_at = Column(String)

    links = relationship(
        "Link",
        primaryjoin="Channel.channel_id==foreign(Link.channel_id)",
        lazy="selectin",
        viewonly=True,
    )
    owner_admin = relationship(
        "Admin",
        primaryjoin="foreign(Channel.owner_admin_id)==Admin.id",
        lazy="joined",
        viewonly=True,
    )
    invite_caches = relationship(
        "InviteCache",
        primaryjoin="Channel.channel_id==foreign(InviteCache.channel_id)",
        lazy="selectin",
        viewonly=True,
    )


class Link(Base):
    __tablename__ = "links"
    __table_args__ = (
        UniqueConstraint("url_norm", name="uq_links_url_norm"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(BigInteger, index=True)
    owner_admin_id = Column(Integer)
    raw_url = Column(Text)
    url_norm = Column(Text, index=True)
    kind = Column(String)
    batch_msg_id = Column(BigInteger)
    owner_username = Column(String)
    added_at = Column(String)


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
    __table_args__ = {"sqlite_autoincrement": True}

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
    owner_admin_id = Column(Integer)
    owner_username = Column(String)


class InviteCache(Base):
    __tablename__ = "invite_cache"

    invite_hash = Column(String, primary_key=True)
    channel_id = Column(BigInteger, ForeignKey("channels.channel_id", ondelete="SET NULL"), index=True, nullable=True)
    title = Column(String)
    status = Column(String)
    session = Column(String)
    last_error = Column(Text)


class UrlCache(Base):
    __tablename__ = "url_cache"

    url = Column(Text, primary_key=True)
    status = Column(Text, nullable=False)
    ts = Column(Integer, nullable=False)

    def __repr__(self) -> str:
        return f"<UrlCache url={self.url} status={self.status} ts={self.ts}>"


class InviteCheck(Base):
    """
    Черга перевірок інвайтів по сесіях (backoff).
    Первинний ключ: (session, invite_hash).
    """

    __tablename__ = "invite_check"

    invite_hash = Column(Text, nullable=False)
    session = Column(Text, nullable=False)
    noted_at = Column(Integer, nullable=False)
    next_check_at = Column(Integer, nullable=False)
    tries = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        PrimaryKeyConstraint("session", "invite_hash", name="pk_invite_check"),
        Index("idx_invite_check_next", "next_check_at"),
        Index("idx_invite_check_session", "session"),
    )

    def __repr__(self) -> str:
        return (
            f"<InviteCheck session={self.session} invite_hash={self.invite_hash} "
            f"next_check_at={self.next_check_at} tries={self.tries}>"
        )


class RequestedCheck(Base):
    """
    Черга повторних перевірок заявок (requested) по сесіях/каналах.
    Первинний ключ: (session, channel_id).
    """

    __tablename__ = "requested_check"

    session = Column(Text, nullable=False)
    channel_id = Column(Integer, nullable=False)
    noted_at = Column(Integer, nullable=False)
    next_check_at = Column(Integer, nullable=False)
    tries = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        PrimaryKeyConstraint("session", "channel_id", name="pk_requested_check"),
        Index("idx_requested_check_next", "next_check_at"),
        Index("idx_requested_check_session", "session"),
    )

    def __repr__(self) -> str:
        return (
            f"<RequestedCheck session={self.session} channel_id={self.channel_id} "
            f"next_check_at={self.next_check_at} tries={self.tries}>"
        )


class OwnerConflict(Base):
    __tablename__ = "owner_conflicts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner = Column(String, nullable=False)
    channel_id = Column(Integer)
    source_ref = Column(String)
    reason = Column(String, nullable=False)
    created_at = Column(Integer, nullable=False)


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
    cpm = Column(Float)
    expected_views = Column(Integer)
    actual_views = Column(Integer)
    avg_views_30d = Column(Integer)
    last_views = Column(Integer)
    theme = Column(String)
    note = Column(Text)
    created_at = Column(Integer)
    updated_at = Column(Integer)


class InviteOwner(Base):
    __tablename__ = "invite_owners"

    invite_hash = Column(Text, primary_key=True)
    owner_admin_id = Column(Integer)
    owner_username = Column(Text)
    created_at = Column(Text)


class BotLink(Base):
    __tablename__ = "bot_links"
    __table_args__ = (
        UniqueConstraint("username", name="uq_bot_links_username"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(Text)
    raw_url = Column(Text)
    status = Column(Text)
    session = Column(Text)
    title = Column(Text)
    owner_admin_id = Column(Integer)
    owner_username = Column(Text)
    batch_id = Column(Text)
    last_ts = Column(Integer)
    last_error = Column(Text)


class PostTemplate(Base):
    __tablename__ = "post_template"

    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(Text, nullable=False)
    mode = Column(Text, nullable=False)
    threshold = Column(Float, nullable=False)
    created_at = Column(Integer, nullable=False)
    title = Column(Text)
    links = Column(Text)


class SheetProject(Base):
    __tablename__ = "sheet_projects"

    project = Column(Text, primary_key=True)
    active_spreadsheet_id = Column(Text)
    active_title = Column(Text)
    updated_at = Column(Text)


class SheetProjectArchive(Base):
    __tablename__ = "sheet_project_archives"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project = Column(Text, nullable=False)
    spreadsheet_id = Column(Text, nullable=False)
    title = Column(Text)
    archived_at = Column(Text)


class WatchGroup(Base):
    __tablename__ = "watch_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project = Column(Text, nullable=True)
    title = Column(Text, nullable=True)
    created_by = Column(BigInteger, nullable=True)
    created_via = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)
    admin_id = Column(Integer, nullable=True)
    network_id = Column(Integer, nullable=True)
    actual_views = Column(Integer, nullable=True)
    actual_price = Column(Float, nullable=True)
    actual_cpm = Column(Float, nullable=True)
    subscribers = Column(Integer, nullable=True)


class WatchPost(Base):
    __tablename__ = "watch_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(BigInteger, nullable=True, index=True)
    template_id = Column(Integer, nullable=True)
    expected_text_hash = Column(Text, nullable=True)
    expected_text_norm_len = Column(Integer, nullable=True)
    expected_links_json = Column(Text, nullable=True)
    expected_media_fingerprint = Column(Text, nullable=True)
    time_window_start = Column(Text, nullable=True)
    time_window_end = Column(Text, nullable=True)
    status = Column(Text, nullable=True, index=True)
    matched_message_id = Column(BigInteger, nullable=True)
    matched_at = Column(Text, nullable=True)
    coverage_check_at = Column(Text, nullable=True, index=True)
    final_views = Column(Integer, nullable=True)
    deleted_at = Column(Text, nullable=True)
    created_at = Column(Text, nullable=True)
    updated_at = Column(Text, nullable=True)
    matched_session = Column(Text, nullable=True, index=True)
    source_url = Column(Text, nullable=True)
    created_by = Column(BigInteger, nullable=True, index=True)
    created_via = Column(Text, nullable=True)
    project = Column(Text, nullable=True)
    group_id = Column(BigInteger, nullable=True, index=True)
    admin_id = Column(Integer, nullable=True, index=True)
    network_id = Column(Integer, nullable=True, index=True)
    posted_at = Column(Text, nullable=True, index=True)
    views_at_post = Column(Integer, nullable=True)
    subs_at_post = Column(Integer, nullable=True)
    cpm_at_post = Column(Float, nullable=True)
    price_at_post = Column(Float, nullable=True)

    __table_args__ = (
        Index(
            "uq_active_watch",
            "channel_id",
            "template_id",
            "expected_text_hash",
            unique=True,
            sqlite_where=text("status IN ('pending','matched')"),
        ),
    )


class WatchEvent(Base):
    __tablename__ = "watch_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    watch_id = Column(BigInteger, nullable=False)
    event_type = Column(String, nullable=False)
    payload_json = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)
    sent_to = Column(BigInteger, nullable=True)
    sent_at = Column(Text, nullable=True, index=True)

    __table_args__ = (
        Index("idx_we_unsent", "sent_at", "id"),
    )


class WatchCandidate(Base):
    __tablename__ = "watch_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    watch_id = Column(BigInteger, nullable=False, index=True)
    channel_id = Column(BigInteger, nullable=True)
    message_id = Column(BigInteger, nullable=True)
    text_hash = Column(Text, nullable=True, index=True)
    similarity = Column(Float, nullable=True)
    message_text = Column(Text, nullable=True)
    status = Column(String, nullable=True, default="pending", index=True)
    created_at = Column(Text, nullable=False)
    expires_at = Column(Text, nullable=True, index=True)


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
    db: Session, owner_admin_id: Optional[int], owner_user: Optional[str]
) -> Tuple[int, int]:
    where_raw = []
    params_raw = {}
    if owner_admin_id is not None:
        where_raw.append("owner_admin_id = :oaid")
        params_raw["oaid"] = owner_admin_id
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
