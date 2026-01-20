from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from app.db import models as m
from app.utils.time_utils import ensure_moscow_timezone, moscow_now


@dataclass
class WatchGroupRecord:
    id: int
    title: Optional[str]
    created_at: Optional[str]
    actual_cpm: Optional[float]
    actual_price: Optional[float]
    actual_views: Optional[int]
    subscribers: Optional[int]
    admin_id: Optional[int]
    network_id: Optional[int]


@dataclass
class WatchGroupPostRecord:
    id: int
    final_views: Optional[int]
    views_at_post: Optional[int]
    price_at_post: Optional[float]
    cpm_at_post: Optional[float]


def _group_row_to_record(row: m.WatchGroup) -> WatchGroupRecord:
    return WatchGroupRecord(
        id=int(row.id),
        title=row.title,
        created_at=row.created_at,
        actual_cpm=row.actual_cpm,
        actual_price=row.actual_price,
        actual_views=row.actual_views,
        subscribers=row.subscribers,
        admin_id=getattr(row, "admin_id", None),
        network_id=getattr(row, "network_id", None),
    )


def _post_row_to_record(row: m.WatchPost) -> WatchGroupPostRecord:
    return WatchGroupPostRecord(
        id=int(row.id),
        final_views=row.final_views,
        views_at_post=row.views_at_post,
        price_at_post=row.price_at_post,
        cpm_at_post=row.cpm_at_post,
    )


def list_groups_for_admin(db: Session, admin_id: int, network_ids: Optional[List[int]] = None) -> List[WatchGroupRecord]:
    network_ids = network_ids or []
    q = (
        db.query(m.WatchGroup)
        .filter(
            exists().where(
                (m.WatchPost.group_id == m.WatchGroup.id)
                & (m.WatchPost.status != "cancelled")
            )
        )
    )
    if network_ids:
        q = q.filter(
            (m.WatchGroup.admin_id == int(admin_id))
            | (m.WatchGroup.network_id.in_(network_ids))
        )
    else:
        q = q.filter(m.WatchGroup.admin_id == int(admin_id))
    rows = q.order_by(m.WatchGroup.id.desc()).all()
    return [_group_row_to_record(g) for g in rows]


def sum_actual_price_for_network(db: Session, net_id: int, days: int = 30) -> float:
    try:
        cutoff = moscow_now() - timedelta(days=days)
    except Exception:
        return 0.0
    total = 0.0
    rows = db.execute(
        select(m.WatchGroup.actual_price, m.WatchGroup.created_at).where(
            m.WatchGroup.network_id == int(net_id)
        )
    ).all()
    for price, created_at in rows:
        try:
            if created_at and ensure_moscow_timezone(datetime.fromisoformat(str(created_at))) < cutoff:
                continue
        except Exception:
            pass
        try:
            if price is not None:
                total += float(price)
        except Exception:
            continue
    return total


def sum_subscribers_for_network(db: Session, net_id: int, days: int = 30) -> int:
    try:
        cutoff = moscow_now() - timedelta(days=days)
    except Exception:
        return 0
    total = 0
    rows = db.execute(
        select(m.WatchGroup.subscribers, m.WatchGroup.created_at).where(
            m.WatchGroup.network_id == int(net_id)
        )
    ).all()
    for subs, created_at in rows:
        try:
            if created_at and ensure_moscow_timezone(datetime.fromisoformat(str(created_at))) < cutoff:
                continue
        except Exception:
            pass
        try:
            if subs is not None:
                total += int(subs)
        except Exception:
            continue
    return total


def get_group_detail(db: Session, group_id: int) -> Tuple[Optional[WatchGroupRecord], List[WatchGroupPostRecord]]:
    g = db.query(m.WatchGroup).filter(m.WatchGroup.id == int(group_id)).one_or_none()
    posts = (
        db.query(m.WatchPost)
        .filter(m.WatchPost.group_id == int(group_id), m.WatchPost.status != "cancelled")
        .order_by(m.WatchPost.id.desc())
        .all()
    )
    group_rec = _group_row_to_record(g) if g else None
    posts_list = [_post_row_to_record(p) for p in posts]
    return group_rec, posts_list


def set_watch_group_subscribers(db: Session, group_id: int, subscribers: int) -> None:
    db.execute(
        update(m.WatchGroup)
        .where(m.WatchGroup.id == int(group_id))
        .values(subscribers=int(subscribers))
    )
    db.commit()
