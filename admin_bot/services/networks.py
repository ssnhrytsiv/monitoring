from __future__ import annotations

import re
import time
import html
from typing import List, Optional

from sqlalchemy import select, func, text
from sqlalchemy.orm import Session

from admin_bot.db import models as m
from app.utils.tg_links import sanitize_link

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


def channel_hyperlink(db: Session, ch: m.Channel) -> str:
    """
    Повертає HTML-посилання на канал: username -> https://t.me/<username>,
    якщо немає username – шукаємо invite_hash у invite_map і будуємо https://t.me/+<hash> (з назвою з invite_map.title, якщо є),
    якщо немає і цього – повертаємо екрановану назву або останній raw_url.
    """
    title = ch.title or ""
    if ch.username:
        label = title or f"@{ch.username}"
        return f'<a href="https://t.me/{html.escape(ch.username)}">{html.escape(label)}</a>'

    inv_row = db.execute(
        select(m.InviteMap.invite_hash, m.InviteMap.title).where(m.InviteMap.channel_id == ch.channel_id)
    ).first()
    if inv_row:
        inv_hash, inv_title = inv_row
        label = title or inv_title or inv_hash
        return f'<a href="https://t.me/+{html.escape(inv_hash)}">{html.escape(label)}</a>'

    # Фолбек: використовуємо останній raw_url із links, щоб показати хоч щось клікабельне
    raw_url = db.execute(
        select(m.Link.raw_url)
        .where(m.Link.channel_id == ch.channel_id, m.Link.raw_url != None)  # noqa: E711
        .order_by(m.Link.id.desc())
    ).scalars().first()
    if raw_url:
        try:
            href = sanitize_link(raw_url) or raw_url
        except Exception:
            href = raw_url
        label = title or href or str(ch.channel_id)
        return f'<a href="{html.escape(href)}">{html.escape(label)}</a>'

    return html.escape(title or str(ch.channel_id))
