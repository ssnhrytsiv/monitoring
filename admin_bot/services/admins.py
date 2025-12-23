from __future__ import annotations

from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import select, delete

from admin_bot.db import models as m


def get_or_create_admin(db: Session, tg_id: int, username: Optional[str], display: Optional[str]) -> m.Admin:
    admin = db.execute(select(m.Admin).where(m.Admin.tg_id == tg_id)).scalar_one_or_none()
    if admin:
        admin.username = username or admin.username
        admin.display = display or admin.display
    else:
        admin = m.Admin(tg_id=tg_id, username=username, display=display)
        db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def list_admins(db: Session) -> List[m.Admin]:
    return list(db.execute(select(m.Admin).order_by(m.Admin.id.desc())).scalars())


def remove_admin(db: Session, admin_id: int) -> bool:
    res = db.execute(delete(m.Admin).where(m.Admin.id == admin_id))
    db.commit()
    return res.rowcount > 0


def attach_channel(db: Session, admin_id: int, channel_id: int) -> None:
    exists = db.execute(
        select(m.AdminChannel).where(
            m.AdminChannel.admin_id == admin_id,
            m.AdminChannel.channel_id == channel_id,
        )
    ).scalar_one_or_none()
    if exists:
        return
    link = m.AdminChannel(admin_id=admin_id, channel_id=channel_id)
    db.add(link)
    db.commit()


def list_channels_for_admin(db: Session, admin_id: int) -> List[m.Channel]:
    admin = db.execute(select(m.Admin).where(m.Admin.id == admin_id)).scalar_one_or_none()
    if not admin:
        return []
    chan_ids = [ac.channel_id for ac in admin.channels]
    if not chan_ids:
        return []
    chans = db.execute(select(m.Channel).where(m.Channel.id.in_(chan_ids))).scalars().all()
    return list(chans)
