"""
DAO operations for admins.
Усі функції приймають зовнішній Session (без внутрішнього SessionLocal).
"""
from typing import Optional, List

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import session_scope
from app.DAL.schemas import AdminRecord, AdminRecordListAdapter


def get_admin_by_id(db: Session, admin_id: int) -> Optional[AdminRecord]:
    row = db.execute(
        select(m.Admin.id, m.Admin.username, m.Admin.display, m.Admin.tg_id).where(m.Admin.id == int(admin_id))
    ).first()
    if not row:
        return None
    return AdminRecord.model_validate(row)


def get_admin_by_record(db: Session, admin: AdminRecord) -> Optional[AdminRecord]:
    if admin is None or admin.id is None:
        return None
    row = db.execute(
        select(m.Admin.id, m.Admin.username, m.Admin.display, m.Admin.tg_id).where(m.Admin.id == int(admin.id))
    ).first()
    if not row:
        return None
    return AdminRecord.model_validate(row)


def get_admin_by_username(db: Session, username: str) -> Optional[AdminRecord]:
    row = db.execute(select(m.Admin).where(m.Admin.username == username)).scalar_one_or_none()
    if not row:
        return None
    return AdminRecord.model_validate(row)


def get_admin_by_display(db: Session, display: str) -> Optional[AdminRecord]:
    row = db.execute(select(m.Admin).where(m.Admin.display == display)).scalar_one_or_none()
    if not row:
        return None
    return AdminRecord.model_validate(row)


def get_admin_by_display_autosession(display: str, username: Optional[str] = None) -> Optional[AdminRecord]:
    """
    Шукає адміна по display, опційно оновлює username.
    Працює всередині session_scope, не створює нового адміна.
    """
    if not display:
        return None
    with session_scope() as db:
        admin_obj = db.execute(select(m.Admin).where(m.Admin.display == display)).scalar_one_or_none()
        if not admin_obj:
            return None
        changed = False
        if username and admin_obj.username != username:
            admin_obj.username = username
            changed = True
        if display and admin_obj.display != display:
            admin_obj.display = display
            changed = True
        if changed:
            db.commit()
            db.refresh(admin_obj)
        return AdminRecord.model_validate(admin_obj)


def delete_admin_by_id(db: Session, admin_id: int) -> int:
    return (
        db.query(m.Admin)
        .filter(m.Admin.id == int(admin_id))
        .delete(synchronize_session=False)
    ) or 0


def delete_url_cache(db: Session, urls: list[str], statuses: Optional[list[str]]) -> int:
    urls = [u for u in urls if u]
    if not urls:
        return 0
    q = db.query(m.UrlCache).filter(m.UrlCache.url.in_(urls))
    if statuses:
        st = [s for s in statuses if s]
        if not st:
            return 0
        q = q.filter(m.UrlCache.status.in_(st))
    deleted = q.delete(synchronize_session=False)
    db.commit()
    return deleted or 0


def list_admins(db: Session) -> List[AdminRecord]:
    rows = db.execute(select(m.Admin).order_by(m.Admin.id.desc())).scalars().all()
    return AdminRecordListAdapter.validate_python(rows)


def list_admin_channel_ids(db: Session, admin_id: int) -> list[int]:
    rows = (
        db.execute(select(m.Channel.channel_id).where(m.Channel.owner_admin_id == int(admin_id)))
        .scalars()
        .all()
    )
    return [int(r) for r in rows if r is not None]


def get_admin_label(db: Session, admin_id: int) -> Optional[AdminRecord]:
    """
    Повертає AdminRecord(display, username) для admin_id або None, якщо немає запису.
    """
    admin_row = db.execute(
        select(m.Admin.display, m.Admin.username).where(m.Admin.id == int(admin_id))
    ).first()
    if not admin_row:
        return None
    return AdminRecord(display=admin_row[0], username=admin_row[1])


def get_or_create_admin_entity(
    db: Session,
    *,
    tg_id: Optional[int],
    username: Optional[str],
    display: Optional[str],
) -> m.Admin:
    adm = None
    if tg_id is not None:
        adm = db.query(m.Admin).filter(m.Admin.tg_id == tg_id).one_or_none()
    if adm is None and username:
        adm = db.query(m.Admin).filter(m.Admin.username == username).one_or_none()
    if adm is None and display:
        adm = db.query(m.Admin).filter(m.Admin.display == display).one_or_none()

    if adm:
        if tg_id is not None:
            adm.tg_id = tg_id
        if username:
            adm.username = username
        if display:
            adm.display = display
    else:
        adm = m.Admin(tg_id=tg_id, username=username, display=display)
        db.add(adm)
    db.commit()
    db.refresh(adm)
    return adm


def toggle_admin_new_flag(db: Session, admin_id: int) -> Optional[m.Admin]:
    adm = db.query(m.Admin).filter(m.Admin.id == int(admin_id)).one_or_none()
    if not adm:
        return None
    current = getattr(adm, "is_new", 0) or 0
    adm.is_new = 0 if current else 1
    db.commit()
    db.refresh(adm)
    return adm


def update_admin_params(
    db: Session,
    admin_id: int,
    *,
    cpm: Optional[float] = None,
    price: Optional[float] = None,
    subscribers: Optional[int] = None,
) -> Optional[m.Admin]:
    adm = db.query(m.Admin).filter(m.Admin.id == int(admin_id)).one_or_none()
    if not adm:
        return None
    if cpm is not None:
        adm.cpm = float(cpm)
    if price is not None:
        adm.price = float(price)
    if subscribers is not None:
        adm.subscribers = int(subscribers)
    db.commit()
    db.refresh(adm)
    return adm


def remove_admin(db: Session, admin_id: int) -> bool:
    res = db.query(m.Admin).filter(m.Admin.id == int(admin_id)).delete(synchronize_session=False)
    db.commit()
    return bool(res)
