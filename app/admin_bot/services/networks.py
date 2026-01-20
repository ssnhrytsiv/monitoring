from __future__ import annotations

import html
from typing import List, Optional

from sqlalchemy.orm import Session

from app.db import models as m
from app.utils.link_parser import sanitize_link
from app.DAL import network_channels_operations as net_db

def list_networks_by_admin(db: Session, admin_id: int) -> List[m.Network]:
    ensure_primary_network(db, admin_id)
    return net_db.list_networks_by_admin(db, admin_id)


def stats_for_admin(db: Session, admin_id: int) -> dict:
    stats = net_db.stats_for_admin(db, admin_id)
    return {
        "price_sum": stats.price_sum,
        "avg_views_30d_sum": stats.avg_views_30d_sum,
        "total_channels": stats.total_channels,
    }


def create_network(db: Session, admin_id: int, name: str, description: Optional[str] = None) -> m.Network:
    return net_db.create_network(db, admin_id, name, description)


def _resolve_channel_by_url(db: Session, url: str) -> Optional[m.Channel]:
    return net_db.resolve_channel_by_url(db, url)


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
    return net_db.add_channels_to_network(
        db,
        network_id=network_id,
        urls=urls,
        admin_id=admin_id,
        move_existing=move_existing,
    )


def networks_with_channels(db: Session, admin_id: int) -> list[net_db.NetworkWithChannels]:
    return net_db.networks_with_channels(db, admin_id)


def admin_channels_without_network(db: Session, admin_id: int) -> List[m.Channel]:
    return net_db.admin_channels_without_network(db, admin_id)


def delete_network(db: Session, network_id: int) -> dict:
    """
    Видаляє сітку: зв'язки network_channels переносить у базову сітку «Основные каналы»
    для цього адміна (створює її при потребі), потім видаляє саму сітку.
    """
    return net_db.delete_network(db, network_id)


def ensure_primary_network(db: Session, admin_id: int, name: str = "Основные каналы") -> m.Network:
    return net_db.ensure_primary_network(db, admin_id, name)


def move_orphans_to_primary(db: Session, admin_id: int) -> int:
    """Переносить канали адміна без сіток у сітку 'Основные каналы'. Повертає кількість перенесених."""
    return net_db.move_orphans_to_primary(db, admin_id)


def update_network_params(
    db: Session,
    net_id: int,
    *,
    price: Optional[float] = None,
    cpm: Optional[float] = None,
    subscribers: Optional[int] = None,
) -> Optional[m.Network]:
    return net_db.update_network_params(
        db,
        net_id,
        price=price,
        cpm=cpm,
        subscribers=subscribers,
    )


def channel_hyperlink(db: Session, ch: m.Channel) -> str:
    """
    Повертає HTML-посилання на канал: username -> https://t.me/<username>,
    якщо немає username – шукаємо invite_hash у invite_cache і будуємо https://t.me/+<hash> (з назвою з invite_cache.title, якщо є),
    якщо немає і цього – повертаємо екрановану назву або останній raw_url.
    """
    meta = net_db.channel_link_meta(db, ch.channel_id)
    if not meta:
        return html.escape(ch.title or str(ch.channel_id))
    title = meta.title or ""
    if meta.username:
        label = title or f"@{meta.username}"
        return f'<a href="https://t.me/{html.escape(meta.username)}">{html.escape(label)}</a>'
    if meta.invite_hash:
        label = title or meta.invite_title or meta.invite_hash
        return f'<a href="https://t.me/+{html.escape(meta.invite_hash)}">{html.escape(label)}</a>'
    if meta.last_raw_url:
        try:
            href = sanitize_link(meta.last_raw_url) or meta.last_raw_url
        except Exception:
            href = meta.last_raw_url
        label = title or href or str(meta.channel_id)
        return f'<a href="{html.escape(href)}">{html.escape(label)}</a>'
    return html.escape(title or str(meta.channel_id))
