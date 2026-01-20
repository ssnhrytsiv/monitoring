"""
DAO operations for admins.
Усі функції приймають зовнішній Session (без внутрішнього SessionLocal).
"""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, text, or_
from sqlalchemy.orm import Session

from app.db import models as m


@dataclass
class AdminLabel:
    display: Optional[str]
    username: Optional[str]


@dataclass(frozen=True)
class AdminSnapshot:
    id: int
    username: Optional[str]
    display: Optional[str]
    tg_id: Optional[int]


def get_admin_by_id(db: Session, admin_id: int) -> Optional[AdminSnapshot]:
    row = db.execute(
        select(m.Admin.id, m.Admin.username, m.Admin.display, m.Admin.tg_id).where(m.Admin.id == int(admin_id))
    ).first()
    if not row:
        return None
    adm_id, username, display, tg_id = row
    if adm_id is None:
        return None
    return AdminSnapshot(id=int(adm_id), username=username, display=display, tg_id=tg_id)


def get_admin_entity_by_id(db: Session, admin_id: int) -> Optional[m.Admin]:
    return db.execute(select(m.Admin).where(m.Admin.id == int(admin_id))).scalars().first()


def get_admin_by_tg_id(db: Session, tg_id: int) -> Optional[AdminSnapshot]:
    row = db.execute(
        select(m.Admin.id, m.Admin.username, m.Admin.display, m.Admin.tg_id).where(m.Admin.tg_id == tg_id)
    ).first()
    if not row:
        return None
    adm_id, username, display, tg_id_val = row
    if adm_id is None:
        return None
    return AdminSnapshot(id=int(adm_id), username=username, display=display, tg_id=tg_id_val)


def get_admin_by_username(db: Session, username: str) -> Optional[m.Admin]:
    return db.execute(select(m.Admin).where(m.Admin.username == username)).scalar_one_or_none()


def get_admin_by_display(db: Session, display: str) -> Optional[m.Admin]:
    return db.execute(select(m.Admin).where(m.Admin.display == display)).scalar_one_or_none()


def delete_admin_channels_by_admin(db: Session, admin_id: int) -> int:
    return m.delete_admin_channels_by_admin(db, admin_id)


def delete_networks_by_admin(db: Session, admin_id: int) -> tuple[int, list[int]]:
    return m.delete_networks_by_admin(db, admin_id)


def delete_network_channels_by_networks(db: Session, network_ids: list[int]) -> int:
    return m.delete_network_channels_by_networks(db, network_ids)


def delete_memberships_by_channels(db: Session, channel_ids: list[int]) -> int:
    return m.delete_memberships_by_channels(db, channel_ids)


def delete_membership_status_by_channels(db: Session, channel_ids: list[int]) -> int:
    return m.delete_membership_status_by_channels(db, channel_ids)


def delete_owner_conflict_by_channels(db: Session, channel_ids: list[int]) -> int:
    return m.delete_owner_conflict_by_channels(db, channel_ids)


def delete_links_by_channels(db: Session, channel_ids: list[int]) -> int:
    return m.delete_links_by_channels(db, channel_ids)


def delete_channels_by_ids(db: Session, channel_ids: list[int]) -> int:
    return m.delete_channels_by_ids(db, channel_ids)


def delete_invite_owners_by_owner(db: Session, owner_admin_id: int, owner_username: Optional[str]) -> int:
    inv_where = ["owner_admin_id = :aid"]
    inv_params = {"aid": owner_admin_id}
    if owner_username:
        inv_where.append("owner_username = :ou")
        inv_params["ou"] = owner_username
    inv_sql = f"DELETE FROM invite_owners WHERE {' OR '.join(inv_where)}"
    return db.execute(text(inv_sql), inv_params).rowcount or 0


def delete_links_no_channel_by_owner(db: Session, owner_admin_id: int, owner_username: Optional[str]) -> int:
    conds = [m.Link.owner_admin_id == owner_admin_id]
    if owner_username:
        conds.append(m.Link.owner_username == owner_username)
    return (
        db.query(m.Link)
        .filter(m.Link.channel_id.is_(None))
        .filter(or_(*conds))
        .delete(synchronize_session=False)
    )


def list_owner_links_no_channel(db: Session, owner_admin_id: int, owner_username: Optional[str]) -> list[str]:
    conds = [m.Link.owner_admin_id == owner_admin_id]
    if owner_username:
        conds.append(m.Link.owner_username == owner_username)
    rows = db.execute(
        select(m.Link.raw_url).where(
            m.Link.channel_id.is_(None),
            or_(*conds),
        )
    ).all()
    return [r[0] for r in rows if r and r[0]]


def delete_url_cache(db: Session, urls: list[str], statuses: Optional[list[str]]) -> int:
    urls = [u for u in urls if u]
    if not urls:
        return 0
    url_ph = ",".join([f":u{i}" for i in range(len(urls))])
    params = {f"u{i}": u for i, u in enumerate(urls)}
    sql = f"DELETE FROM url_cache WHERE url IN ({url_ph})"
    if statuses:
        st = [s for s in statuses if s]
        if st:
            st_ph = ",".join([f":s{i}" for i in range(len(st))])
            params.update({f"s{i}": s for i, s in enumerate(st)})
            sql += f" AND status IN ({st_ph})"
    return db.execute(text(sql), params).rowcount or 0


def list_admins(db: Session) -> list[m.Admin]:
    return list(db.execute(select(m.Admin).order_by(m.Admin.id.desc())).scalars().all())


def list_admin_channel_ids(db: Session, admin_id: int) -> list[int]:
    rows = (
        db.execute(select(m.AdminChannel.channel_id).where(m.AdminChannel.admin_id == int(admin_id)))
        .scalars()
        .all()
    )
    return [int(r) for r in rows if r is not None]


def get_admin_channel_for_channel(db: Session, channel_id: int) -> Optional[m.AdminChannel]:
    return (
        db.execute(select(m.AdminChannel).where(m.AdminChannel.channel_id == int(channel_id)))
        .scalars()
        .first()
    )


def get_admin_label(db: Session, admin_id: int) -> Optional[AdminLabel]:
    """
    Повертає AdminLabel(display, username) для admin_id або None, якщо немає запису.
    """
    admin_row = db.execute(
        select(m.Admin.display, m.Admin.username).where(m.Admin.id == int(admin_id))
    ).first()
    if not admin_row:
        return None
    return AdminLabel(display=admin_row[0], username=admin_row[1])
