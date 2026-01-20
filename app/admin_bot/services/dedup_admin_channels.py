from __future__ import annotations

from typing import List, Dict, Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db import models as m


def find_conflicts(db: Session) -> List[Dict[str, Any]]:
    """
    Повертає список конфліктів: один channel_id має кількох адмінів у admin_channels.
    Формат:
    [
        {
            "channel_id": int,
            "title": str,
            "admins": [{"id": int, "display": str, "username": str}, ...],
        },
        ...
    ]
    """
    conflict_ids = [
        row[0]
        for row in db.execute(
            select(m.AdminChannel.channel_id)
            .group_by(m.AdminChannel.channel_id)
            .having(func.count(m.AdminChannel.admin_id) > 1)
        ).all()
    ]
    if not conflict_ids:
        return []

    rows = (
        db.execute(
            select(
                m.AdminChannel.channel_id,
                m.Channel.title,
                m.Admin.id,
                m.Admin.display,
                m.Admin.username,
            )
            .join(m.Admin, m.Admin.id == m.AdminChannel.admin_id)
            .outerjoin(m.Channel, m.Channel.channel_id == m.AdminChannel.channel_id)
            .where(m.AdminChannel.channel_id.in_(conflict_ids))
            .order_by(m.AdminChannel.channel_id, m.Admin.id)
        ).all()
    )
    grouped: Dict[int, Dict[str, Any]] = {}
    for cid, title, aid, disp, uname in rows:
        grouped.setdefault(cid, {"channel_id": cid, "title": title or "", "admins": []})
        grouped[cid]["admins"].append({"id": aid, "display": disp, "username": uname})
    return list(grouped.values())


def resolve_conflict(db: Session, *, channel_id: int, keep_admin_id: int) -> int:
    """
    Залишає тільки вказаного адміна для channel_id, інші записи видаляє.
    Повертає кількість видалених записів.
    """
    removed = 0
    rows = db.query(m.AdminChannel).filter(m.AdminChannel.channel_id == channel_id).all()
    for r in rows:
        if r.admin_id != keep_admin_id:
            db.delete(r)
            removed += 1
    db.commit()
    return removed
