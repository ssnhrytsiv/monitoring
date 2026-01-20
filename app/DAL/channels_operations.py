"""DAO operations for channels/links. Усі функції приймають зовнішній Session."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, List, Dict

from sqlalchemy.orm import Session
from sqlalchemy import func, select

from app.db import models as m
from app.utils.link_parser import sanitize_link


@dataclass
class ChannelRecord:
    channel_id: int
    username: Optional[str]
    title: Optional[str]
    owner_admin_id: Optional[int]
    last_status: Optional[str]
    order_index: Optional[int]
    updated_at: Optional[str]


@dataclass
class ChannelOwnerInfo:
    owner_admin_id: Optional[int]
    owner_display: Optional[str]


@dataclass
class ChannelTitleOwner:
    title: Optional[str]
    owner_label: Optional[str]


@dataclass
class ChannelOwnerLabel:
    channel_id: int
    owner_label: Optional[str]


@dataclass
class LinkLookup:
    channel_id: int
    title: Optional[str]


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
    raw_url: str
    channel_id: Optional[int]
    kind: Optional[str]
    added_at: Optional[str]


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _normalize_link_key(raw_url: str) -> Optional[str]:
    """
    Повертає стабільний ключ для URL (для пошуку/унікалізації):
    - sanitize_link (виправлення схеми, @username -> https://t.me/..., t.me -> https://t.me/...)
    - прибирає зайві пробіли
    Якщо парсинг падає — повертає stripped raw_url.
    """
    if not raw_url:
        return None
    try:
        norm = sanitize_link(raw_url) or raw_url
    except Exception:
        norm = raw_url
    norm = str(norm).strip()
    return norm or None


def _owner_fields_from_admin(db: Session, admin_id: Optional[int]) -> tuple[Optional[int], Optional[str], Optional[str]]:
    if not admin_id:
        return None, None, None
    adm = db.execute(select(m.Admin).where(m.Admin.id == admin_id)).scalar_one_or_none()
    if not adm:
        return None, None, None
    return adm.id, adm.display, adm.username


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
    owner_admin_id: Optional[int],
    owner_username: Optional[str],
) -> None:
    if not raw_url:
        return
    url_norm = _normalize_link_key(raw_url)
    now = _now_str()
    owner_username_norm = owner_username.lstrip("@").lower() if owner_username else None
    if url_norm:
        exists = db.query(m.Link.id).filter(m.Link.url_norm == url_norm).first()
        if exists:
            return
    db.add(
        m.Link(
            channel_id=channel_id,
            raw_url=raw_url,
            url_norm=url_norm,
            kind=kind,
            batch_msg_id=batch_msg_id,
            owner_admin_id=owner_admin_id,
            owner_username=owner_username_norm if owner_admin_id is None else None,
            added_at=now,
        )
    )
    db.commit()


def list_links_raw_for_channels(db: Session, channel_ids: List[int]) -> List[str]:
    if not channel_ids:
        return []
    rows = db.execute(
        select(m.Link.raw_url).where(m.Link.channel_id.in_(channel_ids))
    ).all()
    return [r[0] for r in rows if r and r[0]]


def find_channel_by_link(db: Session, raw_url: str) -> Optional[LinkLookup]:
    norm = _normalize_link_key(raw_url)
    if norm:
        row = (
            db.query(m.Link.channel_id, m.Channel.title)
            .outerjoin(m.Channel, m.Channel.channel_id == m.Link.channel_id)
            .filter(m.Link.url_norm == norm, m.Link.channel_id.isnot(None))
            .order_by(m.Link.id.desc())
            .limit(1)
            .one_or_none()
        )
        if row:
            channel_id_val, title_val = row
            if channel_id_val is not None:
                return LinkLookup(channel_id=int(channel_id_val), title=title_val)
    if not raw_url:
        return None
    row_raw = (
        db.query(m.Link.channel_id, m.Channel.title)
        .outerjoin(m.Channel, m.Channel.channel_id == m.Link.channel_id)
        .filter(m.Link.raw_url == raw_url, m.Link.channel_id.isnot(None))
        .order_by(m.Link.id.desc())
        .limit(1)
        .one_or_none()
    )
    if not row_raw:
        return None
    channel_id_val, title_val = row_raw
    if channel_id_val is None:
        return None
    return LinkLookup(channel_id=int(channel_id_val), title=title_val)


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
    """Шукає channel_id по url_norm/raw (links.url_norm або links.raw_url)."""
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


def get_owners_by_channel_ids(db: Session, ids: List[int]) -> List[ChannelOwnerLabel]:
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
    result: List[ChannelOwnerLabel] = []
    for cid, owner_admin_id in rows:
        if cid is None:
            continue
        if owner_admin_id:
            adm_disp = admin_map.get(owner_admin_id)
            if adm_disp:
                result.append(ChannelOwnerLabel(channel_id=int(cid), owner_label=adm_disp))
    return result


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


def get_channel_owner_info(db: Session, channel_id: int) -> Optional[ChannelOwnerInfo]:
    """
    Повертає власника каналу.
    Пріоритет: owner_admin_id -> admins.display/username.
    """
    row = db.execute(
        select(
            m.Channel.owner_admin_id,
        ).where(m.Channel.channel_id == int(channel_id))
    ).first()
    if not row:
        return None
    (owner_admin_id,) = row
    if owner_admin_id:
        adm = db.execute(select(m.Admin.display, m.Admin.username).where(m.Admin.id == owner_admin_id)).first()
        if adm:
            adm_display, _adm_username = adm
            return ChannelOwnerInfo(
                owner_admin_id=owner_admin_id,
                owner_display=(adm_display.strip() if adm_display else None),
            )
    return None


def get_channel_title_and_owner(db: Session, channel_id: int) -> Optional[ChannelTitleOwner]:
    """Повертає title і label власника для channel_id."""
    row = (
        db.execute(
            select(m.Channel.title, m.Channel.owner_admin_id)
            .where(m.Channel.channel_id == int(channel_id))
            .limit(1)
        ).first()
    )
    if not row:
        return None
    title_val, owner_admin_id = row
    title = str(title_val).strip() if title_val else None
    if owner_admin_id:
        adm_row = db.execute(select(m.Admin.display).where(m.Admin.id == owner_admin_id)).first()
        if adm_row:
            (admin_display,) = adm_row
            if admin_display:
                return ChannelTitleOwner(title=title, owner_label=admin_display.strip())
    return ChannelTitleOwner(title=title, owner_label=None)


def raw_urls_for_channels(db: Session, channel_ids: List[int]) -> List[str]:
    if not channel_ids:
        return []
    urls: List[str] = []
    for r in db.execute(select(m.Link.raw_url).where(m.Link.channel_id.in_(channel_ids))).all():
        if r and r[0]:
            urls.append(r[0])
    return urls


def list_admin_channel_ids(db: Session, admin_id: int) -> List[int]:
    """Повертає channel_id для admin_channels конкретного адміна."""
    return list(
        db.execute(select(m.AdminChannel.channel_id).where(m.AdminChannel.admin_id == admin_id)).scalars()
    )


def list_all_admin_channel_ids(db: Session) -> List[int]:
    """Повертає всі channel_id з admin_channels."""
    return list(db.execute(select(m.AdminChannel.channel_id)).scalars())


def delete_admin_channels(db: Session, admin_id: int, channel_ids: List[int]) -> int:
    if not channel_ids:
        return 0
    return (
        db.query(m.AdminChannel)
        .filter(
            m.AdminChannel.admin_id == admin_id,
            m.AdminChannel.channel_id.in_(channel_ids),
        )
        .delete(synchronize_session=False)
    )


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
            .join(m.AdminChannel, m.AdminChannel.admin_id == m.Admin.id)
            .where(m.AdminChannel.channel_id == int(channel_id))
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
        db.query(
            m.Channel.channel_id,
            m.Channel.username,
            m.Channel.title,
            m.Channel.owner_admin_id,
            m.Channel.last_status,
            m.Channel.order_index,
            m.Channel.updated_at,
        )
        .filter(m.Channel.channel_id == channel_id)
        .one_or_none()
    )
    if not row:
        return None
    return ChannelRecord(
        channel_id=row.channel_id,
        username=row.username,
        title=row.title,
        owner_admin_id=row.owner_admin_id,
        last_status=row.last_status,
        order_index=row.order_index,
        updated_at=row.updated_at,
    )


def recent_links(db: Session, limit: int = 30) -> List[RecentLink]:
    rows = (
        db.query(
            m.Link.raw_url,
            m.Link.channel_id,
            m.Link.kind,
            m.Link.added_at,
        )
        .order_by(m.Link.id.desc())
        .limit(limit)
        .all()
    )
    result: List[RecentLink] = []
    for raw_url, channel_id, kind, added_at in rows:
        result.append(
            RecentLink(
                raw_url=raw_url,
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
    norm = _normalize_link_key(raw_url)
    if norm:
        row = (
            db.query(m.Link.channel_id)
            .filter(m.Link.url_norm == norm, m.Link.channel_id.isnot(None))
            .order_by(m.Link.id.desc())
            .limit(1)
            .one_or_none()
        )
        if row:
            (channel_id_val,) = row
            if channel_id_val is not None:
                return int(channel_id_val)

    if not raw_url:
        return None

    row_raw = (
        db.query(m.Link.channel_id)
        .filter(m.Link.raw_url == raw_url, m.Link.channel_id.isnot(None))
        .order_by(m.Link.id.desc())
        .limit(1)
        .one_or_none()
    )
    if not row_raw:
        return None
    (channel_id_raw,) = row_raw
    return int(channel_id_raw) if channel_id_raw is not None else None
