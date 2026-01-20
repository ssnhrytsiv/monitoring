"""DAL для сіток (networks) та зв'язків каналів із сітками."""
from dataclasses import dataclass
from typing import Optional, List, Dict
import time
import re

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db import models as m
from app.utils.link_parser import sanitize_link, normalize
from app.DAL import channels_operations as cho


@dataclass
class NetworkChannelBind:
    network_id: Optional[int]
    admin_id: Optional[int]


@dataclass
class NetworkStats:
    price_sum: Optional[float]
    avg_views_30d_sum: int
    total_channels: int


@dataclass
class NetworkWithChannels:
    network: m.Network
    channels: List[m.Channel]


@dataclass
class ChannelLinkMeta:
    channel_id: int
    username: Optional[str]
    title: Optional[str]
    invite_hash: Optional[str]
    invite_title: Optional[str]
    last_raw_url: Optional[str]


def get_network_for_channel(db: Session, channel_id: int) -> Optional[NetworkChannelBind]:
    row = (
        db.query(m.NetworkChannel.network_id, m.Network.admin_id)
        .outerjoin(m.Network, m.Network.id == m.NetworkChannel.network_id)
        .filter(m.NetworkChannel.channel_id == int(channel_id))
        .limit(1)
        .one_or_none()
    )
    if not row:
        return None
    net_id, adm_id = row
    return NetworkChannelBind(
        network_id=int(net_id) if net_id is not None else None,
        admin_id=int(adm_id) if adm_id is not None else None,
    )


def list_networks_by_admin(db: Session, admin_id: int) -> List[m.Network]:
    return (
        db.query(m.Network)
        .filter(m.Network.admin_id == admin_id)
        .order_by(m.Network.name)
        .all()
    )


def stats_for_admin(db: Session, admin_id: int) -> NetworkStats:
    price_sum, avg_views_30d_sum, total_channels = (
        db.query(
            func.sum(m.NetworkChannel.price),
            func.sum(m.NetworkChannel.avg_views_30d),
            func.count(func.distinct(m.NetworkChannel.channel_id)),
        )
        .join(m.Network, m.NetworkChannel.network_id == m.Network.id)
        .filter(m.Network.admin_id == admin_id)
        .one()
    )
    return NetworkStats(
        price_sum=float(price_sum) if price_sum is not None else None,
        avg_views_30d_sum=int(avg_views_30d_sum) if avg_views_30d_sum is not None else 0,
        total_channels=int(total_channels) if total_channels is not None else 0,
    )


def create_network(db: Session, admin_id: int, name: str, description: Optional[str] = None) -> m.Network:
    existing = (
        db.query(m.Network)
        .filter(m.Network.admin_id == admin_id, m.Network.name == name)
        .one_or_none()
    )
    if existing:
        if description is not None:
            existing.description = description
        existing.updated_at = int(time.time())
        db.commit()
        db.refresh(existing)
        return existing
    net = m.Network(
        admin_id=admin_id,
        name=name,
        description=description,
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )
    db.add(net)
    db.commit()
    db.refresh(net)
    return net


def resolve_channel_by_url(db: Session, url: str) -> Optional[m.Channel]:
    clean = sanitize_link(url)

    m_inv = re.search(r"t\.me/\+(?P<hash>[A-Za-z0-9_\-]+)", clean)
    if m_inv:
        h = m_inv.group("hash")
        cache = (
            db.query(m.InviteCache.channel_id)
            .filter(m.InviteCache.invite_hash == h)
            .one_or_none()
        )
        if cache and cache[0]:
            ch = (
                db.query(m.Channel)
                .filter(m.Channel.channel_id == int(cache[0]))
                .one_or_none()
            )
            if ch:
                return ch

    norm = normalize(clean)
    cid = cho.get_channel_id_by_norm_url(db, norm)
    if cid:
        ch = (
            db.query(m.Channel)
            .filter(m.Channel.channel_id == cid)
            .one_or_none()
        )
        if ch:
            return ch

    m_user = re.search(r"t\.me/(?P<uname>[A-Za-z0-9_]{3,})", clean)
    if m_user:
        uname = m_user.group("uname")
        cid = cho.get_channel_id_by_username(db, uname)
        if cid:
            ch = (
                db.query(m.Channel)
                .filter(m.Channel.channel_id == cid)
                .one_or_none()
            )
            if ch:
                return ch
    return None


def add_channels_to_network(
    db: Session,
    network_id: int,
    urls: List[str],
    admin_id: Optional[int] = None,
    move_existing: bool = False,
) -> Dict[str, int]:
    net = db.query(m.Network).filter(m.Network.id == network_id).one_or_none()
    if not net:
        return {"added": 0, "not_found": len(urls), "moved": 0}

    added = 0
    moved = 0
    not_found = 0
    for u in urls:
        ch = resolve_channel_by_url(db, u)
        if not ch:
            not_found += 1
            continue
        if admin_id is not None:
            ac = (
                db.query(m.AdminChannel)
                .filter(
                    m.AdminChannel.admin_id == admin_id,
                    m.AdminChannel.channel_id == ch.channel_id,
                )
                .one_or_none()
            )
            if not ac:
                not_found += 1
                continue

        existing_same = (
            db.query(m.NetworkChannel)
            .filter(
                m.NetworkChannel.network_id == network_id,
                m.NetworkChannel.channel_id == ch.channel_id,
            )
            .one_or_none()
        )
        if existing_same:
            continue

        if move_existing and admin_id is not None:
            other_net = (
                db.query(m.NetworkChannel)
                .join(m.Network, m.NetworkChannel.network_id == m.Network.id)
                .filter(
                    m.NetworkChannel.channel_id == ch.channel_id,
                    m.Network.admin_id == admin_id,
                )
                .first()
            )
            if other_net and other_net.network_id != network_id:
                db.delete(other_net)
                moved += 1

        db.add(
            m.NetworkChannel(
                network_id=network_id,
                channel_id=ch.channel_id,
                created_at=int(time.time()),
                updated_at=int(time.time()),
            )
        )
        added += 1
    db.commit()
    return {"added": added, "not_found": not_found, "moved": moved}


def ensure_primary_network(db: Session, admin_id: int, name: str = "Основные каналы") -> m.Network:
    net = (
        db.query(m.Network)
        .filter(m.Network.admin_id == admin_id, m.Network.name == name)
        .one_or_none()
    )
    if net:
        return net
    net = m.Network(
        admin_id=admin_id,
        name=name,
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )
    db.add(net)
    db.commit()
    db.refresh(net)
    return net


def admin_channels_without_network(db: Session, admin_id: int) -> List[m.Channel]:
    admin = db.query(m.Admin).filter(m.Admin.id == admin_id).one_or_none()
    if not admin or not admin.channels:
        return []
    admin_chan_ids = [ac.channel_id for ac in admin.channels]
    if not admin_chan_ids:
        return []
    mapped = {
        cid for (cid,) in db.query(m.NetworkChannel.channel_id).all()
    }
    return (
        db.query(m.Channel)
        .filter(
            m.Channel.channel_id.in_(admin_chan_ids),
            ~m.Channel.channel_id.in_(mapped),
        )
        .all()
    )


def networks_with_channels(db: Session, admin_id: int) -> List[NetworkWithChannels]:
    nets = list_networks_by_admin(db, admin_id)
    results: List[NetworkWithChannels] = []
    for n in nets:
        channels = (
            db.query(m.Channel)
            .join(m.NetworkChannel, m.NetworkChannel.channel_id == m.Channel.channel_id)
            .filter(m.NetworkChannel.network_id == n.id)
            .order_by(m.Channel.order_index.asc().nulls_last(), m.NetworkChannel.id.asc())
            .all()
        )
        results.append(NetworkWithChannels(network=n, channels=channels))
    return results


def count_channels_in_network(db: Session, network_id: int) -> int:
    return int(
        db.query(func.count(m.NetworkChannel.id))
        .filter(m.NetworkChannel.network_id == network_id)
        .scalar()
        or 0
    )


def list_channels_in_network(db: Session, network_id: int) -> List[m.Channel]:
    return (
        db.query(m.Channel)
        .join(m.NetworkChannel, m.NetworkChannel.channel_id == m.Channel.channel_id)
        .filter(m.NetworkChannel.network_id == network_id)
        .order_by(m.Channel.order_index.asc().nulls_last(), m.NetworkChannel.id.asc())
        .all()
    )


def list_channel_ids_for_admin_networks(db: Session, admin_id: int) -> List[int]:
    return [
        cid
        for (cid,) in (
            db.query(m.NetworkChannel.channel_id)
            .join(m.Network, m.NetworkChannel.network_id == m.Network.id)
            .filter(m.Network.admin_id == admin_id)
            .all()
        )
    ]


def list_network_ids_for_admin(db: Session, admin_id: int) -> List[int]:
    return [nid for (nid,) in db.query(m.Network.id).filter(m.Network.admin_id == admin_id).all()]


def channel_link_meta(db: Session, channel_id: int) -> Optional[ChannelLinkMeta]:
    ch = db.query(m.Channel).filter(m.Channel.channel_id == channel_id).one_or_none()
    if not ch:
        return None
    invite_row = (
        db.query(m.InviteCache.invite_hash, m.InviteCache.title)
        .filter(m.InviteCache.channel_id == channel_id)
        .first()
    )
    invite_hash = invite_row.invite_hash if invite_row else None
    invite_title = invite_row.title if invite_row else None
    raw_url = (
        db.query(m.Link.raw_url)
        .filter(m.Link.channel_id == channel_id, m.Link.raw_url.isnot(None))
        .order_by(m.Link.id.desc())
        .scalar()
    )
    return ChannelLinkMeta(
        channel_id=channel_id,
        username=ch.username,
        title=ch.title,
        invite_hash=invite_hash,
        invite_title=invite_title,
        last_raw_url=raw_url,
    )


def move_orphans_to_primary(db: Session, admin_id: int) -> int:
    primary = ensure_primary_network(db, admin_id)
    orphan = admin_channels_without_network(db, admin_id)
    if not orphan:
        return 0
    moved = 0
    for ch in orphan:
        exists = (
            db.query(m.NetworkChannel)
            .filter(
                m.NetworkChannel.network_id == primary.id,
                m.NetworkChannel.channel_id == ch.channel_id,
            )
            .one_or_none()
        )
        if exists:
            continue
        db.add(
            m.NetworkChannel(
                network_id=primary.id,
                channel_id=ch.channel_id,
                created_at=int(time.time()),
                updated_at=int(time.time()),
            )
        )
        moved += 1
    db.commit()
    return moved


def delete_network(db: Session, network_id: int) -> Dict[str, object]:
    net = db.query(m.Network).filter(m.Network.id == network_id).one_or_none()
    if not net:
        return {"deleted": False, "moved": 0, "admin_id": None, "name": None}
    moved = 0
    if net.admin_id:
        primary = ensure_primary_network(db, net.admin_id)
        chans = [
            cid
            for (cid,) in db.query(m.NetworkChannel.channel_id)
            .filter(m.NetworkChannel.network_id == network_id)
            .all()
        ]
        for ch_id in chans:
            exists = (
                db.query(m.NetworkChannel)
                .filter(
                    m.NetworkChannel.network_id == primary.id,
                    m.NetworkChannel.channel_id == ch_id,
                )
                .one_or_none()
            )
            if not exists:
                db.add(
                    m.NetworkChannel(
                        network_id=primary.id,
                        channel_id=ch_id,
                        created_at=int(time.time()),
                        updated_at=int(time.time()),
                    )
                )
                moved += 1
    else:
        moved = (
            db.query(func.count(m.NetworkChannel.id))
            .filter(m.NetworkChannel.network_id == network_id)
            .scalar()
            or 0
        )

    db.query(m.NetworkChannel).filter(m.NetworkChannel.network_id == network_id).delete()
    db.query(m.Network).filter(m.Network.id == network_id).delete()
    db.commit()
    return {"deleted": True, "moved": moved, "admin_id": net.admin_id, "name": net.name}


def delete_network_channels_by_networks(db: Session, network_ids: List[int], channel_ids: Optional[List[int]] = None) -> int:
    if not network_ids:
        return 0
    q = db.query(m.NetworkChannel).filter(m.NetworkChannel.network_id.in_(network_ids))
    if channel_ids:
        q = q.filter(m.NetworkChannel.channel_id.in_(channel_ids))
    return q.delete(synchronize_session=False)


def update_network_params(
    db: Session,
    net_id: int,
    *,
    price: Optional[float] = None,
    cpm: Optional[float] = None,
    subscribers: Optional[int] = None,
) -> Optional[m.Network]:
    net = db.query(m.Network).filter(m.Network.id == net_id).one_or_none()
    if not net:
        return None
    if price is not None:
        net.price_negotiated = float(price)
    if cpm is not None:
        net.cpm_negotiated = float(cpm)
    if subscribers is not None:
        net.subscribers = int(subscribers)
    net.updated_at = int(time.time())
    db.commit()
    db.refresh(net)
    return net
