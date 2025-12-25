from __future__ import annotations

from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import select, delete, text

from admin_bot.db import models as m


def get_or_create_admin(
    db: Session,
    tg_id: Optional[int],
    username: Optional[str],
    display: Optional[str],
) -> m.Admin:
    admin = None

    if tg_id is not None:
        admin = db.execute(select(m.Admin).where(m.Admin.tg_id == tg_id)).scalar_one_or_none()
    if admin is None and username:
        admin = db.execute(select(m.Admin).where(m.Admin.username == username)).scalar_one_or_none()
    if admin is None and display:
        admin = db.execute(select(m.Admin).where(m.Admin.display == display)).scalar_one_or_none()

    if admin:
        if tg_id is not None:
            admin.tg_id = tg_id
        if username:
            admin.username = username
        if display:
            admin.display = display
    else:
        admin = m.Admin(tg_id=tg_id, username=username, display=display)
        db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def list_admins(db: Session) -> List[m.Admin]:
    return list(db.execute(select(m.Admin).order_by(m.Admin.id.desc())).scalars())


def get_admin_by_id(db: Session, admin_id: int) -> Optional[m.Admin]:
    return db.execute(select(m.Admin).where(m.Admin.id == admin_id)).scalar_one_or_none()


def remove_admin(db: Session, admin_id: int) -> bool:
    res = db.execute(delete(m.Admin).where(m.Admin.id == admin_id))
    db.commit()
    return res.rowcount > 0


def remove_admin_deep(db: Session, admin_id: int, cleanup_channels: bool = True) -> dict:
    """
    Видаляє адміна та пов'язані дані:
    - admin_channels
    - networks / network_channels цього адміна
    - самого адміна
    Опційно чистить канали/інвайти/мембершип/лінки, якщо channel більше ніде не використовується.
    """
    # Спершу дістаємо сам об'єкт адміна (для owner_display/username)
    admin_obj = db.execute(select(m.Admin).where(m.Admin.id == admin_id)).scalar_one_or_none()

    # Збираємо канали адміна
    chan_ids = [
        ac.channel_id
        for ac in db.execute(select(m.AdminChannel).where(m.AdminChannel.admin_id == admin_id)).scalars().all()
    ]

    # Прибираємо прив'язки admin_channels
    ac_deleted = db.execute(delete(m.AdminChannel).where(m.AdminChannel.admin_id == admin_id)).rowcount or 0
    # Прибираємо мережі та їх канали
    net_ids = list(db.execute(select(m.Network.id).where(m.Network.admin_id == admin_id)).scalars().all())
    nc_deleted = 0
    if net_ids:
        nc_deleted = db.execute(delete(m.NetworkChannel).where(m.NetworkChannel.network_id.in_(net_ids))).rowcount or 0
        db.execute(delete(m.Network).where(m.Network.id.in_(net_ids)))
    adm_deleted = db.execute(delete(m.Admin).where(m.Admin.id == admin_id)).rowcount or 0

    # Додаткове очищення
    mem_deleted = 0
    invite_map_deleted = 0
    invite_status_deleted = 0
    owner_conflicts_deleted = 0
    invite_owners_deleted = 0
    links_no_channel_deleted = 0
    links_deleted = 0
    channels_deleted = 0
    membership_status_deleted = 0

    if cleanup_channels and chan_ids:
        # membership
        mem_deleted = db.execute(delete(m.Membership).where(m.Membership.channel_id.in_(chan_ids))).rowcount or 0
        # membership_status (raw table) — видаляємо лише якщо є колонка channel_id
        try:
            placeholders = ",".join([str(cid) for cid in chan_ids])
            membership_status_deleted = db.execute(
                text(f"DELETE FROM membership_status WHERE channel_id IN ({placeholders})")
            ).rowcount or 0
        except Exception:
            membership_status_deleted = 0  # таблиця/колонка може відрізнятись у схемі
        # invite_map + invite_status
        hashes = [h for h in db.execute(select(m.InviteMap.invite_hash).where(m.InviteMap.channel_id.in_(chan_ids))).scalars().all()]
        if hashes:
            invite_status_deleted = db.execute(delete(m.InviteStatus).where(m.InviteStatus.invite_hash.in_(hashes))).rowcount or 0
        invite_map_deleted = db.execute(delete(m.InviteMap).where(m.InviteMap.channel_id.in_(chan_ids))).rowcount or 0
        owner_conflicts_deleted = db.execute(delete(m.OwnerConflict).where(m.OwnerConflict.channel_id.in_(chan_ids))).rowcount or 0
        # links
        links_deleted = db.execute(delete(m.Link).where(m.Link.channel_id.in_(chan_ids))).rowcount or 0

        # Визначаємо канали, які можна прибрати: якщо не залишилось admin_channel або network_channel
        keep_ids = set(
            db.execute(select(m.AdminChannel.channel_id)).scalars().all()
        ) | set(db.execute(select(m.NetworkChannel.channel_id)).scalars().all())
        delete_ids = [cid for cid in chan_ids if cid not in keep_ids]
        if delete_ids:
            channels_deleted = db.execute(delete(m.Channel).where(m.Channel.channel_id.in_(delete_ids))).rowcount or 0

    # invite_owners та links без channel_id для цього адміна (по display/username)
    if admin_obj:
        owner_disp = admin_obj.display
        owner_user = admin_obj.username
        # invite_owners: лише за власником (таблиця не має channel_id у схемі)
        conds = []
        params = {}
        if owner_disp:
            conds.append("owner_display = :od")
            params["od"] = owner_disp
        if owner_user:
            conds.append("owner_username = :ou")
            params["ou"] = owner_user
        if conds:
            where = " OR ".join(conds)
            invite_owners_deleted += db.execute(
                text(f"DELETE FROM invite_owners WHERE {where}"),
                params,
            ).rowcount or 0
            links_no_channel_deleted += db.execute(
                text(f"DELETE FROM links WHERE channel_id IS NULL AND ({where})"),
                params,
            ).rowcount or 0

    db.commit()
    return {
        "admin_deleted": adm_deleted,
        "admin_channels_deleted": ac_deleted,
        "network_channels_deleted": nc_deleted,
        "networks_deleted": len(net_ids),
        "membership_deleted": mem_deleted,
        "invite_map_deleted": invite_map_deleted,
        "invite_status_deleted": invite_status_deleted,
        "owner_conflicts_deleted": owner_conflicts_deleted,
        "links_deleted": links_deleted,
        "channels_deleted": channels_deleted,
        "membership_status_deleted": membership_status_deleted,
        "invite_owners_deleted": invite_owners_deleted,
        "links_no_channel_deleted": links_no_channel_deleted,
    }


def attach_channel(db: Session, admin_id: int, channel_id: int) -> dict:
    """
    Прив'язує канал до адміна, але блокує, якщо канал уже закріплений за іншим адміном.
    Повертає dict:
      {"status": "added"|"exists"|"conflict", "admin_id": <int|None>}
    """
    # Перевіряємо, чи вже прив'язаний до когось
    existing_link = db.execute(
        select(m.AdminChannel).where(m.AdminChannel.channel_id == channel_id)
    ).scalars().first()
    if existing_link:
        if existing_link.admin_id == admin_id:
            return {"status": "exists", "admin_id": admin_id}
        else:
            return {"status": "conflict", "admin_id": existing_link.admin_id}

    link = m.AdminChannel(admin_id=admin_id, channel_id=channel_id)
    db.add(link)
    db.commit()
    return {"status": "added", "admin_id": admin_id}


def list_channels_for_admin(db: Session, admin_id: int) -> List[m.Channel]:
    admin = db.execute(select(m.Admin).where(m.Admin.id == admin_id)).scalar_one_or_none()
    if not admin:
        return []
    chan_ids = [ac.channel_id for ac in admin.channels]
    if not chan_ids:
        return []
    chans = db.execute(select(m.Channel).where(m.Channel.id.in_(chan_ids))).scalars().all()
    return list(chans)


def ensure_channel(db: Session, channel_id: int, username: Optional[str] = None, title: Optional[str] = None) -> m.Channel:
    ch = db.execute(select(m.Channel).where(m.Channel.channel_id == channel_id)).scalar_one_or_none()
    if ch:
        if username:
            ch.username = ch.username or username
        if title:
            ch.title = ch.title or title
        db.commit()
        db.refresh(ch)
        return ch
    ch = m.Channel(channel_id=channel_id, username=username, title=title)
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return ch
