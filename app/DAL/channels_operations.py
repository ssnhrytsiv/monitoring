"""
DAO operations for channels, links, channel_links.
Усі функції нижче відкривають сесію самостійно (через SessionLocal) або приймають зовнішній Session.
"""
import time
from typing import Optional, List, Tuple, Dict

from sqlalchemy.orm import Session
from sqlalchemy import func, select

from app.admin_bot.db import models as m
from app.admin_bot.db.session import SessionLocal


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def upsert_channel(
    db: Session,
    channel_id: int,
    username: Optional[str],
    title: Optional[str],
    owner_display: Optional[str],
    owner_username: Optional[str],
    last_status: Optional[str],
) -> None:
    now = _now_str()
    row: Optional[m.Channel] = db.query(m.Channel).filter(m.Channel.channel_id == channel_id).one_or_none()
    if row:
        if username:
            row.username = username
        if title:
            row.title = title
        if owner_display:
            row.owner_display = owner_display
        if owner_username:
            row.owner_username = owner_username
        if last_status:
            row.last_status = last_status
        row.updated_at = now
    else:
        db.add(
            m.Channel(
                channel_id=channel_id,
                username=username,
                title=title,
                owner_display=owner_display,
                owner_username=owner_username,
                last_status=last_status,
                created_at=now,
                updated_at=now,
            )
        )
    db.commit()


def add_link(
    db: Session,
    channel_id: Optional[int],
    raw_url: str,
    kind: Optional[str],
    batch_msg_id: Optional[int],
    owner_display: Optional[str],
    owner_username: Optional[str],
) -> None:
    if not raw_url:
        return
    now = _now_str()
    db.add(
        m.Link(
            channel_id=channel_id,
            raw_url=raw_url,
            kind=kind,
            batch_msg_id=batch_msg_id,
            owner_display=owner_display,
            owner_username=owner_username,
            added_at=now,
        )
    )
    db.commit()


def find_channel_by_link(db: Session, raw_url: str) -> Optional[Tuple[int, Optional[str]]]:
    if not raw_url:
        return None
    row = (
        db.query(m.Link.channel_id, m.Channel.title)
        .outerjoin(m.Channel, m.Channel.channel_id == m.Link.channel_id)
        .filter(m.Link.raw_url == raw_url)
        .order_by(m.Link.id.desc())
        .limit(1)
        .one_or_none()
    )
    if not row or row[0] is None:
        return None
    return int(row[0]), row[1]


def get_channel_id_by_username(username: str) -> Optional[int]:
    if not username:
        return None
    db = SessionLocal()
    try:
        row = db.execute(
            select(m.Channel.channel_id).where(func.lower(m.Channel.username) == username.lower()).limit(1)
        ).first()
        if not row or row[0] is None:
            return None
        return int(row[0])
    finally:
        db.close()


def get_channel_id_by_invite_hash(invite_hash: str) -> Optional[int]:
    if not invite_hash:
        return None
    db = SessionLocal()
    try:
        row = db.execute(
            select(m.InviteMap.channel_id).where(m.InviteMap.invite_hash == invite_hash).limit(1)
        ).first()
        if not row or row[0] is None:
            return None
        return int(row[0])
    finally:
        db.close()


def get_channel_id_by_url(url_norm: str) -> Optional[int]:
    if not url_norm:
        return None
    db = SessionLocal()
    try:
        row = db.execute(
            select(m.ChannelLink.channel_id).where(m.ChannelLink.link_url_norm == url_norm).limit(1)
        ).first()
        if not row or row[0] is None:
            return None
        return int(row[0])
    finally:
        db.close()


def get_links_by_channel_ids(ids: List[int]) -> Dict[int, str]:
    clean_ids = [int(x) for x in ids or [] if x]
    if not clean_ids:
        return {}
    db = SessionLocal()
    try:
        result: Dict[int, str] = {}
        rows = db.execute(
            select(m.Channel.channel_id, m.Channel.username).where(m.Channel.channel_id.in_(clean_ids))
        ).all()
        for cid, username in rows:
            cid_i = int(cid)
            if username:
                result[cid_i] = f"https://t.me/{str(username).lstrip('@')}"
        rows = db.execute(
            select(m.InviteMap.channel_id, m.InviteMap.invite_hash).where(m.InviteMap.channel_id.in_(clean_ids))
        ).all()
        for cid, invite_hash in rows:
            cid_i = int(cid)
            if cid_i not in result and invite_hash:
                result[cid_i] = f"https://t.me/+{invite_hash}"
        rows = db.execute(
            select(m.ChannelLink.channel_id, m.ChannelLink.link_url_norm).where(m.ChannelLink.channel_id.in_(clean_ids))
        ).all()
        for cid, link_url_norm in rows:
            cid_i = int(cid)
            if cid_i not in result and link_url_norm:
                result[cid_i] = str(link_url_norm)
        return {cid: link for cid, link in result.items() if link}
    finally:
        db.close()


def get_raw_links_by_channel_ids(ids: List[int]) -> Dict[int, str]:
    clean_ids = [int(x) for x in ids or [] if x]
    if not clean_ids:
        return {}
    db = SessionLocal()
    try:
        rows = (
            db.execute(
                select(m.Link.channel_id, m.Link.raw_url)
                .where(m.Link.channel_id.in_(clean_ids), m.Link.raw_url.isnot(None))
                .order_by(m.Link.id.desc())
            )
            .all()
        )
        result: Dict[int, str] = {}
        for cid, raw_url in rows:
            if cid is None or not raw_url:
                continue
            cid_i = int(cid)
            if cid_i not in result:
                result[cid_i] = str(raw_url)
        return result
    finally:
        db.close()


def get_owners_by_channel_ids(ids: List[int]) -> Dict[int, str]:
    clean_ids = [int(x) for x in ids or [] if x]
    if not clean_ids:
        return {}
    db = SessionLocal()
    try:
        rows = db.execute(
            select(m.Channel.channel_id, m.Channel.owner_display).where(m.Channel.channel_id.in_(clean_ids))
        ).all()
        result: Dict[int, str] = {}
        for cid, owner in rows:
            if cid is None:
                continue
            cid_i = int(cid)
            owner_clean = str(owner).strip() if owner is not None else ""
            if owner_clean:
                result[cid_i] = owner_clean
        return result
    finally:
        db.close()


def get_titles_by_channel_ids(ids: List[int]) -> Dict[int, str]:
    clean_ids = [int(x) for x in ids or [] if x]
    if not clean_ids:
        return {}
    db = SessionLocal()
    try:
        rows = db.execute(
            select(m.Channel.channel_id, m.Channel.title).where(m.Channel.channel_id.in_(clean_ids))
        ).all()
        result: Dict[int, str] = {}
        for cid, title in rows:
            if cid is None:
                continue
            cid_i = int(cid)
            title_clean = str(title).strip() if title is not None else ""
            if title_clean:
                result[cid_i] = title_clean
        return result
    finally:
        db.close()


def get_channel_title_and_owner(channel_id: int) -> Tuple[Optional[str], Optional[str]]:
    """
    Повертає (title, owner_display) для channel_id або (None, None), якщо не знайдено.
    """
    db = SessionLocal()
    try:
        row = db.execute(
            select(m.Channel.title, m.Channel.owner_display).where(m.Channel.channel_id == int(channel_id)).limit(1)
        ).first()
    finally:
        db.close()
    if not row:
        return None, None
    title = str(row[0]).strip() if row[0] else None
    owner = str(row[1]).strip() if row[1] else None
    return title, owner


def get_channels_by_owner(db: Session, owner: str, limit: int = 50) -> List[Tuple]:
    clean = owner.lstrip("@").lower()
    rows = (
        db.query(
            m.Channel.channel_id,
            m.Channel.username,
            m.Channel.title,
            m.Channel.last_status,
            m.Channel.owner_display,
            m.Channel.owner_username,
            m.Channel.updated_at,
        )
        .filter(
            (func.lower(m.Channel.owner_username) == clean)
            | (func.lower(m.Channel.owner_display) == clean)
        )
        .order_by(m.Channel.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [tuple(r) for r in rows]


def find_channel(db: Session, channel_id: int) -> Optional[dict]:
    row = (
        db.query(
            m.Channel.channel_id,
            m.Channel.username,
            m.Channel.title,
            m.Channel.owner_display,
            m.Channel.owner_username,
            m.Channel.last_status,
            m.Channel.created_at,
            m.Channel.updated_at,
        )
        .filter(m.Channel.channel_id == channel_id)
        .one_or_none()
    )
    if not row:
        return None
    return {
        "channel_id": row[0],
        "username": row[1],
        "title": row[2],
        "owner_display": row[3],
        "owner_username": row[4],
        "last_status": row[5],
        "created_at": row[6],
        "updated_at": row[7],
    }


def recent_links(db: Session, limit: int = 30) -> List[Tuple]:
    rows = (
        db.query(
            m.Link.raw_url,
            m.Link.channel_id,
            m.Link.kind,
            m.Link.owner_display,
            m.Link.owner_username,
            m.Link.added_at,
        )
        .order_by(m.Link.id.desc())
        .limit(limit)
        .all()
    )
    return [tuple(r) for r in rows]


def recent_channels(db: Session, limit: int = 30) -> List[Tuple]:
    rows = (
        db.query(
            m.Channel.channel_id,
            m.Channel.username,
            m.Channel.title,
            m.Channel.last_status,
            m.Channel.owner_display,
            m.Channel.owner_username,
            m.Channel.updated_at,
        )
        .order_by(m.Channel.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [tuple(r) for r in rows]


def search_channels_by_username(db: Session, substring: str, limit: int = 30) -> List[Tuple]:
    if not substring:
        return []
    pattern = f"%{substring.lower()}%"
    rows = (
        db.query(
            m.Channel.channel_id,
            m.Channel.username,
            m.Channel.title,
            m.Channel.last_status,
            m.Channel.owner_display,
            m.Channel.owner_username,
            m.Channel.updated_at,
        )
        .filter(func.lower(m.Channel.username).like(pattern))
        .order_by(m.Channel.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [tuple(r) for r in rows]


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


def upsert_channel_link(db: Session, link_url_norm: str, channel_id: Optional[int]) -> None:
    if not link_url_norm:
        return
    now_ts = int(time.time())
    row = db.query(m.ChannelLink).filter(m.ChannelLink.link_url_norm == link_url_norm).one_or_none()
    if row:
        if channel_id:
            row.channel_id = channel_id
        row.last_seen_ts = now_ts
    else:
        db.add(
            m.ChannelLink(
                link_url_norm=link_url_norm,
                channel_id=channel_id,
                first_seen_ts=now_ts,
                last_seen_ts=now_ts,
            )
        )
    db.commit()


def get_channel_id_by_url(db: Session, raw_url: str) -> Optional[int]:
    if not raw_url:
        return None
    row = (
        db.query(m.Link.channel_id)
        .filter(m.Link.raw_url == raw_url, m.Link.channel_id.isnot(None))
        .order_by(m.Link.id.desc())
        .limit(1)
        .one_or_none()
    )
    if not row:
        return None
    try:
        return int(row[0])
    except Exception:
        return None
