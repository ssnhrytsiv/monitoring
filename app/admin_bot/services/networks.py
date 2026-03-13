from __future__ import annotations

import re
import time
import html
from typing import List, Optional

from sqlalchemy import select, func, text, delete
from sqlalchemy.orm import Session

from app.admin_bot.db import models as m
from app.services import link_queue
from app.utils.link_parser import sanitize_link

_NETWORK_SCHEMA_PATCHED = False


def ensure_network_schema(db: Session) -> None:
    global _NETWORK_SCHEMA_PATCHED
    if _NETWORK_SCHEMA_PATCHED:
        return
    try:
        cols = [r[1] for r in db.execute(text("PRAGMA table_info(networks)")).fetchall()]
        if "subscribers" not in cols:
            db.execute(text("ALTER TABLE networks ADD COLUMN subscribers INTEGER"))
            db.commit()
        if "price_negotiated" not in cols:
            db.execute(text("ALTER TABLE networks ADD COLUMN price_negotiated FLOAT"))
            db.commit()
        if "cpm_negotiated" not in cols:
            db.execute(text("ALTER TABLE networks ADD COLUMN cpm_negotiated FLOAT"))
            db.commit()
        if "actual_price" not in cols:
            db.execute(text("ALTER TABLE networks ADD COLUMN actual_price FLOAT"))
            db.commit()
        if "actual_cpm" not in cols:
            db.execute(text("ALTER TABLE networks ADD COLUMN actual_cpm FLOAT"))
            db.commit()
        if "actual_views" not in cols:
            db.execute(text("ALTER TABLE networks ADD COLUMN actual_views INTEGER"))
            db.commit()
        _NETWORK_SCHEMA_PATCHED = True
    except Exception:
        db.rollback()
        _NETWORK_SCHEMA_PATCHED = False


def list_networks_by_admin(db: Session, admin_id: int) -> List[m.Network]:
    # гарантуємо наявність базової сітки
    ensure_network_schema(db)
    ensure_primary_network(db, admin_id)
    return list(
        db.execute(
            select(m.Network).where(m.Network.admin_id == admin_id).order_by(m.Network.name)
        ).scalars()
    )


def stats_for_admin(db: Session, admin_id: int) -> dict:
    ensure_network_schema(db)
    q = (
        select(
            func.sum(m.NetworkChannel.price),
            func.sum(m.NetworkChannel.avg_views_30d),
            func.count(func.distinct(m.NetworkChannel.channel_id)),
        )
        .join(m.Network, m.NetworkChannel.network_id == m.Network.id)
        .where(m.Network.admin_id == admin_id)
    )
    price_sum, avg_views_30d_sum, total_channels = db.execute(q).one()
    return {
        "price_sum": float(price_sum) if price_sum is not None else None,
        "avg_views_30d_sum": int(avg_views_30d_sum) if avg_views_30d_sum is not None else 0,
        "total_channels": int(total_channels) if total_channels is not None else 0,
    }


def create_network(db: Session, admin_id: int, name: str, description: Optional[str] = None) -> m.Network:
    ensure_network_schema(db)
    existing = db.execute(
        select(m.Network).where(m.Network.admin_id == admin_id, m.Network.name == name)
    ).scalar_one_or_none()
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


def _resolve_channel_by_url(db: Session, url: str) -> Optional[m.Channel]:
    clean = sanitize_link(url)
    # Invite link t.me/+hash
    m_inv = re.search(r"t\.me/\+(?P<hash>[A-Za-z0-9_\-]+)", clean)
    if m_inv:
        h = m_inv.group("hash")
        imap = db.execute(select(m.InviteMap).where(m.InviteMap.invite_hash == h)).scalar_one_or_none()
        if imap:
            ch = db.execute(select(m.Channel).where(m.Channel.channel_id == imap.channel_id)).scalar_one_or_none()
            if ch:
                return ch
    # Public username t.me/username
    m_user = re.search(r"t\.me/(?P<uname>[A-Za-z0-9_]{3,})", clean)
    if m_user:
        uname = m_user.group("uname")
        ch = db.execute(select(m.Channel).where(m.Channel.username == uname)).scalar_one_or_none()
        if ch:
            return ch
    return None


def add_channels_to_network(
    db: Session,
    network_id: int,
    urls: List[str],
    admin_id: Optional[int] = None,
    move_existing: bool = False,
) -> dict:
    """
    Додає канали до мережі.
    - якщо admin_id заданий, канал має бути прив'язаний до цього адміна (admin_channels), інакше не додаємо;
    - якщо move_existing=True: якщо канал уже є в іншій сітці того ж адміна – переносимо в цільову.
    """
    ensure_network_schema(db)
    net = db.execute(select(m.Network).where(m.Network.id == network_id)).scalar_one_or_none()
    if not net:
        return {"added": 0, "not_found": len(urls), "moved": 0}

    added = 0
    moved = 0
    not_found = 0
    for u in urls:
        ch = _resolve_channel_by_url(db, u)
        if not ch:
            not_found += 1
            continue
        # перевірка належності адміна
        if admin_id is not None:
            ac = db.execute(
                select(m.AdminChannel).where(
                    m.AdminChannel.admin_id == admin_id,
                    m.AdminChannel.channel_id == ch.channel_id,
                )
            ).scalar_one_or_none()
            if not ac:
                not_found += 1
                continue

        # перевіряємо існуючі зв'язки цього каналу з мережами адміна
        existing_same = db.execute(
            select(m.NetworkChannel).where(
                m.NetworkChannel.network_id == network_id,
                m.NetworkChannel.channel_id == ch.channel_id,
            )
        ).scalar_one_or_none()
        if existing_same:
            continue

        if move_existing and admin_id is not None:
            other_net = db.execute(
                select(m.NetworkChannel, m.Network)
                .join(m.Network, m.NetworkChannel.network_id == m.Network.id)
                .where(
                    m.NetworkChannel.channel_id == ch.channel_id,
                    m.Network.admin_id == admin_id,
                )
            ).first()
            if other_net and other_net[0].network_id != network_id:
                # перенесення: видаляємо старий зв'язок
                db.delete(other_net[0])
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


def networks_with_channels(db: Session, admin_id: int) -> list[dict]:
    ensure_network_schema(db)
    nets = list_networks_by_admin(db, admin_id)
    results = []
    for n in nets:
        rows = db.execute(
            select(m.Channel, m.NetworkChannel)
            .join(m.NetworkChannel, m.NetworkChannel.channel_id == m.Channel.channel_id)
            .where(m.NetworkChannel.network_id == n.id)
            .order_by(m.Channel.title)
        ).all()
        channels = [r[0] for r in rows]
        results.append({"network": n, "channels": channels})
    return results


def admin_channels_without_network(db: Session, admin_id: int) -> List[m.Channel]:
    ensure_network_schema(db)
    # канали, прив'язані до адміна, але не мають запису в network_channels
    admin = db.execute(select(m.Admin).where(m.Admin.id == admin_id)).scalar_one_or_none()
    if not admin or not admin.channels:
        return []
    admin_chan_ids = [ac.channel_id for ac in admin.channels]
    if not admin_chan_ids:
        return []
    mapped = set(db.execute(select(m.NetworkChannel.channel_id)).scalars().all())
    rows = db.execute(
        select(m.Channel).where(
            m.Channel.channel_id.in_(admin_chan_ids),
            ~m.Channel.channel_id.in_(mapped),
        )
    ).scalars().all()
    return list(rows)


def delete_network(db: Session, network_id: int) -> dict:
    """
    Видаляє сітку: зв'язки network_channels переносить у базову сітку «Основные каналы»
    для цього адміна (створює її при потребі), потім видаляє саму сітку.
    """
    net = db.execute(select(m.Network).where(m.Network.id == network_id)).scalar_one_or_none()
    if not net:
        return {"deleted": False, "moved": 0, "admin_id": None, "name": None}
    moved = 0
    # переносимо канали у базову сітку, якщо відомий admin_id
    if net.admin_id:
        primary = ensure_primary_network(db, net.admin_id)
        chans = db.execute(
            select(m.NetworkChannel.channel_id).where(m.NetworkChannel.network_id == network_id)
        ).scalars().all()
        for ch_id in chans:
            exists = db.execute(
                select(m.NetworkChannel).where(
                    m.NetworkChannel.network_id == primary.id,
                    m.NetworkChannel.channel_id == ch_id,
                )
            ).scalar_one_or_none()
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
        moved = db.execute(
            select(func.count(m.NetworkChannel.id)).where(m.NetworkChannel.network_id == network_id)
        ).scalar() or 0

    db.query(m.NetworkChannel).filter(m.NetworkChannel.network_id == network_id).delete()
    db.query(m.Network).filter(m.Network.id == network_id).delete()
    db.commit()
    return {"deleted": True, "moved": moved, "admin_id": net.admin_id, "name": net.name}


def _build_channel_cleanup_urls(
    channel_username: Optional[str],
    invite_hashes: List[str],
    raw_link_urls: List[str],
    normalized_link_urls: List[str],
) -> list[str]:
    seed_urls = set()
    for raw_link_url in raw_link_urls:
        clean_raw_link = str(raw_link_url or "").replace("\u200b", "").replace("\u200e", "").replace("\u200f", "").strip()
        if clean_raw_link:
            seed_urls.add(clean_raw_link)
    for normalized_link_url in normalized_link_urls:
        clean_normalized_link = str(normalized_link_url or "").replace("\u200b", "").replace("\u200e", "").replace("\u200f", "").strip()
        if clean_normalized_link:
            seed_urls.add(clean_normalized_link)
    if channel_username:
        seed_urls.add(f"https://t.me/{str(channel_username).lstrip('@')}")
    for invite_hash in invite_hashes:
        invite_hash_clean = str(invite_hash or "").strip()
        if not invite_hash_clean:
            continue
        seed_urls.add(f"https://t.me/+{invite_hash_clean}")
        seed_urls.add(f"https://t.me/joinchat/{invite_hash_clean}")

    expanded_urls = set()
    for seed_url in seed_urls:
        clean_seed_url = str(seed_url or "").replace("\u200b", "").replace("\u200e", "").replace("\u200f", "").strip()
        if not clean_seed_url:
            continue
        expanded_urls.add(clean_seed_url)
        try:
            sanitized_seed_url = sanitize_link(clean_seed_url) or clean_seed_url
            expanded_urls.add(sanitized_seed_url)
        except Exception:
            pass
        if "joinchat/" in clean_seed_url:
            expanded_urls.add(clean_seed_url.replace("joinchat/", "+"))
        if clean_seed_url.startswith("https://t.me/+"):
            expanded_urls.add(clean_seed_url.replace("https://t.me/+", "https://t.me/joinchat/"))
    return [url_value for url_value in expanded_urls if url_value]


def delete_channel_and_relations(db: Session, channel_id: int) -> dict:
    channel_identifier = int(channel_id)
    channel_record = db.execute(
        select(m.Channel).where(m.Channel.channel_id == channel_identifier)
    ).scalar_one_or_none()
    channel_title = channel_record.title if channel_record else None
    channel_username = channel_record.username if channel_record else None

    invite_hashes = [
        invite_hash
        for invite_hash in db.execute(
            select(m.InviteMap.invite_hash).where(m.InviteMap.channel_id == channel_identifier)
        ).scalars().all()
        if invite_hash
    ]
    raw_link_urls = [
        raw_link_url
        for raw_link_url in db.execute(
            select(m.Link.raw_url).where(m.Link.channel_id == channel_identifier, m.Link.raw_url.isnot(None))
        ).scalars().all()
        if raw_link_url
    ]
    normalized_link_urls = [
        normalized_link_url
        for normalized_link_url in db.execute(
            select(m.ChannelLink.link_url_norm).where(
                m.ChannelLink.channel_id == channel_identifier,
                m.ChannelLink.link_url_norm.isnot(None),
            )
        ).scalars().all()
        if normalized_link_url
    ]
    channel_cleanup_urls = _build_channel_cleanup_urls(
        channel_username=channel_username,
        invite_hashes=invite_hashes,
        raw_link_urls=raw_link_urls,
        normalized_link_urls=normalized_link_urls,
    )

    admin_channels_deleted = db.execute(
        delete(m.AdminChannel).where(m.AdminChannel.channel_id == channel_identifier)
    ).rowcount or 0
    network_channels_deleted = db.execute(
        delete(m.NetworkChannel).where(m.NetworkChannel.channel_id == channel_identifier)
    ).rowcount or 0
    memberships_deleted = m.delete_memberships_by_channels(db, [channel_identifier])
    membership_status_deleted = m.delete_membership_status_by_channels(db, [channel_identifier])
    invite_status_deleted = m.delete_invite_status_by_hashes(db, invite_hashes)
    invite_map_deleted = m.delete_invite_map_by_channels(db, [channel_identifier])
    owner_conflicts_deleted = m.delete_owner_conflict_by_channels(db, [channel_identifier])
    links_deleted = m.delete_links_by_channels(db, [channel_identifier])
    channel_links_deleted = db.execute(
        delete(m.ChannelLink).where(m.ChannelLink.channel_id == channel_identifier)
    ).rowcount or 0
    subscriptions_deleted = db.execute(
        delete(m.Subscription).where(m.Subscription.channel_id == channel_identifier)
    ).rowcount or 0
    watch_posts_deleted = db.execute(
        delete(m.WatchPost).where(m.WatchPost.channel_id == channel_identifier)
    ).rowcount or 0
    watch_candidates_deleted = db.execute(
        delete(m.WatchCandidate).where(m.WatchCandidate.channel_id == channel_identifier)
    ).rowcount or 0
    invite_owners_deleted = 0
    if invite_hashes:
        invite_owners_deleted = db.execute(
            delete(m.InviteOwner).where(m.InviteOwner.invite_hash.in_(invite_hashes))
        ).rowcount or 0
    channels_deleted = m.delete_channels_by_ids(db, [channel_identifier])

    url_cache_deleted = 0
    if channel_cleanup_urls:
        url_cache_deleted = db.execute(
            delete(m.UrlCache).where(
                m.UrlCache.url.in_(channel_cleanup_urls),
                m.UrlCache.status.in_(["already", "joined"]),
            )
        ).rowcount or 0
        if url_cache_deleted == 0:
            url_cache_deleted = db.execute(
                delete(m.UrlCache).where(m.UrlCache.url.in_(channel_cleanup_urls))
            ).rowcount or 0

    db.commit()
    link_queue_deleted = 0
    if channel_cleanup_urls:
        try:
            link_queue_deleted = int(link_queue.delete_by_owner(urls=list(set(channel_cleanup_urls))) or 0)
        except Exception:
            link_queue_deleted = 0

    return {
        "channel_found": bool(channel_record),
        "channel_id": channel_identifier,
        "channel_title": channel_title,
        "channel_username": channel_username,
        "admin_channels_deleted": int(admin_channels_deleted),
        "network_channels_deleted": int(network_channels_deleted),
        "memberships_deleted": int(memberships_deleted),
        "membership_status_deleted": int(membership_status_deleted),
        "invite_map_deleted": int(invite_map_deleted),
        "invite_status_deleted": int(invite_status_deleted),
        "invite_owners_deleted": int(invite_owners_deleted),
        "owner_conflicts_deleted": int(owner_conflicts_deleted),
        "links_deleted": int(links_deleted),
        "channel_links_deleted": int(channel_links_deleted),
        "subscriptions_deleted": int(subscriptions_deleted),
        "watch_posts_deleted": int(watch_posts_deleted),
        "watch_candidates_deleted": int(watch_candidates_deleted),
        "channels_deleted": int(channels_deleted),
        "url_cache_deleted": int(url_cache_deleted),
        "link_queue_deleted": int(link_queue_deleted),
    }


def ensure_primary_network(db: Session, admin_id: int, name: str = "Основные каналы") -> m.Network:
    ensure_network_schema(db)
    net = db.execute(
        select(m.Network).where(m.Network.admin_id == admin_id, m.Network.name == name)
    ).scalar_one_or_none()
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


def move_orphans_to_primary(db: Session, admin_id: int) -> int:
    """Переносить канали адміна без сіток у сітку 'Основные каналы'. Повертає кількість перенесених."""
    ensure_network_schema(db)
    primary = ensure_primary_network(db, admin_id)
    orphan = admin_channels_without_network(db, admin_id)
    if not orphan:
        return 0
    moved = 0
    for ch in orphan:
        exists = db.execute(
            select(m.NetworkChannel).where(
                m.NetworkChannel.network_id == primary.id,
                m.NetworkChannel.channel_id == ch.channel_id,
            )
        ).scalar_one_or_none()
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


def update_network_params(
    db: Session,
    net_id: int,
    *,
    price: Optional[float] = None,
    cpm: Optional[float] = None,
    subscribers: Optional[int] = None,
) -> Optional[m.Network]:
    ensure_network_schema(db)
    net = db.execute(select(m.Network).where(m.Network.id == net_id)).scalar_one_or_none()
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


def channel_display_label_and_url(db: Session, channel_record: m.Channel) -> tuple[str, Optional[str]]:
    channel_title = channel_record.title or ""
    if channel_record.username:
        channel_label = channel_title or f"@{channel_record.username}"
        channel_url = f"https://t.me/{channel_record.username}"
        return channel_label, channel_url

    invite_map_row = db.execute(
        select(m.InviteMap.invite_hash, m.InviteMap.title).where(m.InviteMap.channel_id == channel_record.channel_id)
    ).first()
    if invite_map_row:
        invite_hash, invite_title = invite_map_row
        channel_label = channel_title or invite_title or invite_hash
        channel_url = f"https://t.me/+{invite_hash}"
        return channel_label, channel_url

    raw_link_url = db.execute(
        select(m.Link.raw_url)
        .where(m.Link.channel_id == channel_record.channel_id, m.Link.raw_url != None)  # noqa: E711
        .order_by(m.Link.id.desc())
    ).scalars().first()
    if raw_link_url:
        try:
            channel_url = sanitize_link(raw_link_url) or raw_link_url
        except Exception:
            channel_url = raw_link_url
        channel_label = channel_title or channel_url or str(channel_record.channel_id)
        return channel_label, channel_url

    return channel_title or str(channel_record.channel_id), None


def channel_hyperlink(db: Session, ch: m.Channel) -> str:
    """
    Повертає HTML-посилання на канал: username -> https://t.me/<username>,
    якщо немає username – шукаємо invite_hash у invite_map і будуємо https://t.me/+<hash> (з назвою з invite_map.title, якщо є),
    якщо немає і цього – повертаємо екрановану назву або останній raw_url.
    """
    channel_label, channel_url = channel_display_label_and_url(db, ch)
    if channel_url:
        return f'<a href="{html.escape(channel_url)}">{html.escape(channel_label)}</a>'
    return html.escape(channel_label)
