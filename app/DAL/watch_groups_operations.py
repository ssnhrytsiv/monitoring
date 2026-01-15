from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import exists, select, update

from app.admin_bot.db import models as m
from app.admin_bot.db.session import SessionLocal
from app.utils.time_utils import ensure_moscow_timezone, moscow_now


def list_groups_for_admin(admin_id: int, network_ids: Optional[List[int]] = None) -> List[Dict]:
    network_ids = network_ids or []
    db = SessionLocal()
    try:
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
        return [
            {
                "id": int(g.id),
                "title": g.title,
                "created_at": g.created_at,
                "actual_cpm": g.actual_cpm,
                "actual_price": g.actual_price,
                "actual_views": g.actual_views,
                "subscribers": g.subscribers,
            }
            for g in rows
        ]
    finally:
        db.close()


def sum_actual_price_for_network(net_id: int, days: int = 30) -> float:
    try:
        cutoff = moscow_now() - timedelta(days=days)
    except Exception:
        return 0.0
    total = 0.0
    db = SessionLocal()
    try:
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
    finally:
        db.close()


def sum_subscribers_for_network(net_id: int, days: int = 30) -> int:
    try:
        cutoff = moscow_now() - timedelta(days=days)
    except Exception:
        return 0
    total = 0
    db = SessionLocal()
    try:
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
    finally:
        db.close()


def get_group_detail(group_id: int) -> Tuple[Optional[Dict], List[Dict]]:
    db = SessionLocal()
    try:
        g = db.query(m.WatchGroup).filter(m.WatchGroup.id == int(group_id)).one_or_none()
        posts = (
            db.query(m.WatchPost)
            .filter(m.WatchPost.group_id == int(group_id), m.WatchPost.status != "cancelled")
            .order_by(m.WatchPost.id.desc())
            .all()
        )
        group_dict = None
        if g:
            group_dict = {
                "id": int(g.id),
                "title": g.title,
                "created_at": g.created_at,
                "actual_cpm": g.actual_cpm,
                "actual_price": g.actual_price,
                "actual_views": g.actual_views,
                "subscribers": g.subscribers,
            }
        posts_list: List[Dict] = []
        for p in posts:
            posts_list.append(
                {
                    "id": int(p.id),
                    "final_views": p.final_views,
                    "views_at_post": p.views_at_post,
                    "price_at_post": p.price_at_post,
                    "cpm_at_post": p.cpm_at_post,
                }
            )
        return group_dict, posts_list
    finally:
        db.close()


def set_watch_group_subscribers(group_id: int, subscribers: int) -> None:
    db = SessionLocal()
    try:
        db.execute(
            update(m.WatchGroup)
            .where(m.WatchGroup.id == int(group_id))
            .values(subscribers=int(subscribers))
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
