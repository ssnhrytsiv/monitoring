"""
DAO operations for admins.
Усі функції приймають зовнішній Session або відкривають власний через SessionLocal.
"""
from typing import Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.admin_bot.db import models as m
from app.admin_bot.db.session import SessionLocal


def get_admin_label(db: Optional[Session], admin_id: int) -> Optional[Tuple[Optional[str], Optional[str]]]:
    """
    Повертає (display, username) для admin_id або None, якщо немає запису.
    """
    session = db or SessionLocal()
    try:
        row = session.execute(select(m.Admin.display, m.Admin.username).where(m.Admin.id == int(admin_id))).first()
        if not row:
            return None
        return row[0], row[1]
    finally:
        if db is None:
            session.close()
