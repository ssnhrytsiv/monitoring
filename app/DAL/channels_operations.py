"""DAO operations for channels/links. Усі функції приймають зовнішній Session."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, List, Dict

from sqlalchemy.orm import Session
from sqlalchemy import func, select

from app.db import models as m
from app.DAL.link_operations import (
    add_link as link_add,
    list_links_for_channels as link_list_for_channels,
    find_channel_by_link as link_find_channel_by_link,
)
from app.DAL.schemas import LinkRecord
from app.DAL.schemas.channel import (
    ChannelOwner,
    ChannelOwnerListAdapter,
    ChannelRecord,
)


@dataclass
class RecentChannel:
    channel_id: int
    username: Optional[str]
    title: Optional[str]
    last_status: Optional[str]
    owner_label: Optional[str]
    updated_at: Optional[str]


@dataclass
class RecentLink:
    url_norm: str
    channel_id: Optional[int]
    kind: Optional[str]
    added_at: Optional[str]


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def upsert_channel(
    db: Session,
    channel_id: int,
    username: Optional[str],
    title: Optional[str],
    order_index: Optional[int] = None,
    owner_admin_id: Optional[int] = None,
    last_status: Optional[str] = None,
) -> None:
    now = _now_str()
    row: Optional[m.Channel] = db.query(m.Channel).filter(m.Channel.channel_id == channel_id).one_or_none()
    if row:
        if username and not row.username:
            row.username = username
        if title and not row.title:
            row.title = title
        # власника зберігаємо через admin_id; username лишаємо для історії якщо admin_id немає
        if owner_admin_id is not None and not row.owner_admin_id:
            row.owner_admin_id = owner_admin_id
        if last_status:
            row.last_status = last_status
        if row.order_index is None and order_index is not None:
            row.order_index = int(order_index)
        row.updated_at = now
    else:
        db.add(
            m.Channel(
                channel_id=channel_id,
                username=username,
                title=title,
                order_index=int(order_index) if order_index is not None else None,
                owner_admin_id=owner_admin_id,
                last_status=last_status,
                updated_at=now,
            )
        )
    db.commit()


def upsert_channel_full(
    db: Session,
    *,
    channel_id: int,
    username: Optional[str] = None,
    title: Optional[str] = None,
    order_index: Optional[int] = None,
    owner_admin_id: Optional[int] = None,
    last_status: Optional[str] = None,
) -> None:
    """
    Розширений upsert: заповнює базові поля, але не перетирає вже наявні username/title/owner_*.
    created_at оновлюємо лише при створенні, updated_at – завжди.
    """
    now = _now_str()
    row: Optional[m.Channel] = db.query(m.Channel).filter(m.Channel.channel_id == channel_id).one_or_none()
    if row:
        if username and not row.username:
            row.username = username
        if title and not row.title:
            row.title = title
        if owner_admin_id is not None and not row.owner_admin_id:
            row.owner_admin_id = owner_admin_id
        if last_status:
            row.last_status = last_status
        if row.order_index is None and order_index is not None:
            row.order_index = int(order_index)
        row.updated_at = now
    else:
        row = m.Channel(
            channel_id=channel_id,
            username=username,
            title=title,
            order_index=int(order_index) if order_index is not None else None,
            owner_admin_id=owner_admin_id,
            last_status=last_status,
            updated_at=now,
        )
        db.add(row)
    db.commit()


def get_channel_by_id(db: Session, channel_id: int) -> Optional[m.Channel]:
    return (
        db.query(m.Channel)
        .filter(m.Channel.channel_id == int(channel_id))
        .one_or_none()
    )


def list_channels_by_ids(db: Session, channel_ids: List[int]) -> List[m.Channel]:
    if not channel_ids:
        return []
    return (
        db.query(m.Channel)
        .filter(m.Channel.channel_id.in_([int(cid) for cid in channel_ids]))
        .all()
    )


def add_link(
    db: Session,
    channel_id: Optional[int],
    raw_url: str,
    kind: Optional[str],
    batch_msg_id: Optional[int],
) -> None:
    return link_add(db, channel_id, raw_url, kind, batch_msg_id)


def list_links_for_channels(db: Session, channel_ids: List[int]) -> List[LinkRecord]:
    return link_list_for_channels(db, channel_ids)


def find_channel_by_link(db: Session, raw_url: str) -> Optional[LinkRecord]:
    return link_find_channel_by_link(db, raw_url)


def get_channel_id_by_username(db: Session, username: str) -> Optional[int]:
    if not username:
        return None
    row = db.execute(
        select(m.Channel.channel_id).where(func.lower(m.Channel.username) == username.lower()).limit(1)
    ).first()
    if not row:
        return None
    (channel_id_val,) = row
    if channel_id_val is None:
        return None
    return int(channel_id_val)


def get_channel_id_by_url_any(db: Session, raw_url: str) -> Optional[int]:
    """Шукає channel_id по нормалізованому url (links.url_norm)."""
    return get_channel_id_by_url(db, raw_url)


def get_channel_id_by_norm_url(db: Session, url_norm: str) -> Optional[int]:
    """
    Повертає channel_id за нормалізованим посиланням (links.url_norm).
    """
    if not url_norm:
        return None
    row = db.execute(
        select(m.Link.channel_id)
        .where(m.Link.url_norm == url_norm, m.Link.channel_id.isnot(None))
        .order_by(m.Link.id.desc())
        .limit(1)
    ).first()
    if not row:
        return None
    (channel_id_val,) = row
    if channel_id_val is None:
        return None
    return int(channel_id_val)


def get_links_by_channel_ids(db: Session, ids: List[int]) -> Dict[int, str]:
    clean_ids = [int(x) for x in ids or [] if x]
    if not clean_ids:
        return {}
    result: Dict[int, str] = {}
    rows = db.execute(select(m.Channel.channel_id, m.Channel.username).where(m.Channel.channel_id.in_(clean_ids))).all()
    for cid, username in rows:
        cid_i = int(cid)
        if username:
            result[cid_i] = f"https://t.me/{str(username).lstrip('@')}"
    rows = db.execute(
        select(m.Link.channel_id, m.Link.url_norm)
        .where(m.Link.channel_id.in_(clean_ids), m.Link.url_norm.isnot(None))
    ).all()
    for cid, link_url_norm in rows:
        cid_i = int(cid)
        if cid_i not in result and link_url_norm:
            result[cid_i] = str(link_url_norm)
    return {cid: link for cid, link in result.items() if link}


def get_owners_by_channel_ids(db: Session, ids: List[int]) -> List[ChannelOwner]:
    clean_ids = [int(x) for x in ids or [] if x]
    if not clean_ids:
        return []
    admin_map: Dict[int, str] = {
        a.id: (a.display or a.username or "").strip() for a in db.query(m.Admin).filter(m.Admin.id.isnot(None)).all()
    }
    rows = db.execute(
        select(
            m.Channel.channel_id,
            m.Channel.owner_admin_id,
        ).where(m.Channel.channel_id.in_(clean_ids))
    ).all()
    return ChannelOwnerListAdapter.validate_python(
        [
            {
                "channel_id": int(cid),
                "owner_admin_id": owner_admin_id,
                "owner_display": admin_map.get(owner_admin_id),
                "owner_label": admin_map.get(owner_admin_id),
            }
            for cid, owner_admin_id in rows
            if cid is not None and owner_admin_id in admin_map
        ]
    )


def get_titles_by_channel_ids(db: Session, ids: List[int]) -> Dict[int, str]:
    clean_ids = [int(x) for x in ids or [] if x]
    if not clean_ids:
        return {}
    rows = db.execute(select(m.Channel.channel_id, m.Channel.title).where(m.Channel.channel_id.in_(clean_ids))).all()
    result: Dict[int, str] = {}
    for cid, title in rows:
        if cid is None:
            continue
        cid_i = int(cid)
        title_clean = str(title).strip() if title is not None else ""
        if title_clean:
            result[cid_i] = title_clean
    return result


def get_channel_owner_info(db: Session, channel_id: int) -> Optional[ChannelOwner]:
    row = (
        db.execute(
            select(
                m.Channel.channel_id,
                m.Channel.owner_admin_id,
                m.Admin.display,
            )
            .outerjoin(m.Admin, m.Admin.id == m.Channel.owner_admin_id)
            .where(m.Channel.channel_id == int(channel_id))
        ).first()
    )
    if not row:
        return None
    cid, owner_admin_id, owner_display = row
    return ChannelOwner(
        channel_id=cid,
        owner_admin_id=owner_admin_id,
        owner_display=owner_display,
        owner_label=owner_display.strip() if owner_display else None,
    )


def get_channel_title_and_owner(db: Session, channel_id: int) -> Optional[ChannelOwner]:
    row = (
        db.execute(
            select(
                m.Channel.channel_id,
                m.Channel.title,
                m.Channel.owner_admin_id,
                m.Admin.display,
            )
            .outerjoin(m.Admin, m.Admin.id == m.Channel.owner_admin_id)
            .where(m.Channel.channel_id == int(channel_id))
            .limit(1)
        ).first()
    )
    if not row:
        return None
    cid, title_val, owner_admin_id, admin_display = row
    title = str(title_val).strip() if title_val else None
    return ChannelOwner(
        channel_id=cid,
        owner_admin_id=owner_admin_id,
        owner_display=admin_display,
        owner_label=admin_display.strip() if admin_display else None,
        title=title,
    )


def raw_urls_for_channels(db: Session, channel_ids: List[int]) -> List[str]:
    records = link_list_for_channels(db, channel_ids)
    return [rec.url_norm for rec in records if rec and rec.url_norm]


def delete_channels_by_ids(db: Session, channel_ids: List[int]) -> int:
    if not channel_ids:
        return 0
    return (
        db.query(m.Channel)
        .filter(m.Channel.channel_id.in_(channel_ids))
        .delete(synchronize_session=False)
    ) or 0


def list_admin_channel_ids(db: Session, admin_id: int) -> List[int]:
    """Повертає channel_id із channels для конкретного owner_admin_id."""
    rows = (
        db.execute(
            select(m.Channel.channel_id).where(m.Channel.owner_admin_id == int(admin_id))
        )
        .scalars()
        .all()
    )
    return [int(r) for r in rows if r is not None]


def list_all_admin_channel_ids(db: Session) -> List[int]:
    """Повертає всі channel_id, де задано owner_admin_id."""
    rows = (
        db.execute(
            select(m.Channel.channel_id).where(m.Channel.owner_admin_id.isnot(None))
        )
        .scalars()
        .all()
    )
    return [int(r) for r in rows if r is not None]


def delete_admin_channels(db: Session, admin_id: int, channel_ids: List[int]) -> int:
    """Скидає owner_admin_id для заданих channel_id, якщо вони належать admin_id."""
    if not channel_ids:
        return 0
    res = (
        db.query(m.Channel)
        .filter(
            m.Channel.owner_admin_id == int(admin_id),
            m.Channel.channel_id.in_(channel_ids),
        )
        .update({"owner_admin_id": None}, synchronize_session=False)
    )
    db.commit()
    return res or 0


@dataclass
class AdminChannelOwner:
    admin_id: Optional[int]
    display: Optional[str]
    username: Optional[str]
    tg_id: Optional[int]


def get_admin_for_channel(db: Session, channel_id: int) -> Optional[AdminChannelOwner]:
    row = (
        db.execute(
            select(m.Admin.display, m.Admin.username, m.Admin.tg_id, m.Admin.id)
            .join(m.Channel, m.Channel.owner_admin_id == m.Admin.id)
            .where(m.Channel.channel_id == int(channel_id))
            .limit(1)
        ).first()
    )
    if not row:
        return None
    disp, uname, tg_id, adm_id = row
    return AdminChannelOwner(
        admin_id=int(adm_id) if adm_id is not None else None,
        display=disp,
        username=uname,
        tg_id=tg_id,
    )


def find_channel(db: Session, channel_id: int) -> Optional[ChannelRecord]:
    row = (
        db.execute(
            select(
                m.Channel.channel_id,
                m.Channel.username,
                m.Channel.title,
                m.Channel.owner_admin_id,
                m.Channel.last_status,
                m.Channel.order_index,
                m.Channel.updated_at,
            ).where(m.Channel.channel_id == channel_id)
        ).first()
    )
    if not row:
        return None
    return ChannelRecord.model_validate(row._mapping)


def recent_links(db: Session, limit: int = 30) -> List[RecentLink]:
    rows = (
        db.query(
            m.Link.url_norm,
            m.Link.channel_id,
            m.Link.kind,
            m.Link.added_at,
        )
        .order_by(m.Link.id.desc())
        .limit(limit)
        .all()
    )
    result: List[RecentLink] = []
    for url_norm, channel_id, kind, added_at in rows:
        result.append(
            RecentLink(
                url_norm=url_norm,
                channel_id=channel_id,
                kind=kind,
                added_at=added_at,
            )
        )
    return result


def recent_channels(db: Session, limit: int = 30) -> List[RecentChannel]:
    admin_sub = db.query(m.Admin.id, m.Admin.display).subquery()
    rows = (
        db.query(
            m.Channel.channel_id,
            m.Channel.username,
            m.Channel.title,
            m.Channel.last_status,
            m.Channel.owner_admin_id,
            m.Channel.updated_at,
            admin_sub.c.display,
        )
        .outerjoin(admin_sub, m.Channel.owner_admin_id == admin_sub.c.id)
        .order_by(m.Channel.updated_at.desc())
        .limit(limit)
        .all()
    )
    result: List[RecentChannel] = []
    for (
        channel_id,
        username,
        title,
        last_status,
        owner_admin_id_val,
        updated_at,
        admin_display,
    ) in rows:
        owner_label = admin_display or None
        result.append(
            RecentChannel(
                channel_id=channel_id,
                username=username,
                title=title,
                last_status=last_status,
                owner_label=owner_label,
                updated_at=updated_at,
            )
        )
    return result


def search_channels_by_username(db: Session, substring: str, limit: int = 30) -> List[RecentChannel]:
    if not substring:
        return []
    pattern = f"%{substring.lower()}%"
    admin_sub = db.query(m.Admin.id, m.Admin.display).subquery()
    rows = (
        db.query(
            m.Channel.channel_id,
            m.Channel.username,
            m.Channel.title,
            m.Channel.last_status,
            m.Channel.owner_admin_id,
            m.Channel.updated_at,
            admin_sub.c.display,
        )
        .outerjoin(admin_sub, m.Channel.owner_admin_id == admin_sub.c.id)
        .filter(func.lower(m.Channel.username).like(pattern))
        .order_by(m.Channel.updated_at.desc())
        .limit(limit)
        .all()
    )
    result: List[RecentChannel] = []
    for (
        channel_id,
        username,
        title,
        last_status,
        owner_admin_id_val,
        updated_at,
        admin_display,
    ) in rows:
        owner_label = admin_display or None
        result.append(
            RecentChannel(
                channel_id=channel_id,
                username=username,
                title=title,
                last_status=last_status,
                owner_label=owner_label,
                updated_at=updated_at,
            )
        )
    return result


def prune_orphan_links(db: Session, max_without_channel: int = 10000) -> int:
    cnt = db.query(m.Link).filter(m.Link.channel_id.is_(None)).count()
    if cnt <= max_without_channel:
        return 0
    to_delete = cnt - max_without_channel
    # delete oldest without channel_id
    subq = (
        db.query(m.Link.id)
        .filter(m.Link.channel_id.is_(None))
        .order_by(m.Link.id.asc())
        .limit(to_delete)
        .subquery()
    )
    deleted = db.query(m.Link).filter(m.Link.id.in_(subq)).delete(synchronize_session=False)
    db.commit()
    return deleted


def get_channel_id_by_url(db: Session, raw_url: str) -> Optional[int]:
    lookup = link_find_channel_by_link(db, raw_url)
    if not lookup:
        return None
    return int(lookup.channel_id)
