"""
Service-style wrapper that holds a single SQLAlchemy Session and exposes DAO helpers.
Use this to avoid відкривати SessionLocal у кожній функції: створюємо один інстанс на рівні воркера/обробника.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Optional

from sqlalchemy.orm import Session

from app.DAL import SessionLocal
from app.DAL.membership_operations import MembershipDAO
from app.DAL import channels_operations as cho


class DALService(AbstractContextManager):
    """
    Один сервісний об'єкт із єдиною сесією БД.
    Піднімає DAO як поля (membership_db) і надає обгортки для поширених операцій каналів.
    """

    def __init__(self, db: Optional[Session] = None) -> None:
        self._own_session = db is None
        self.db: Session = db or SessionLocal()
        self.membership_db = MembershipDAO(self.db)

    # ---- Channels helpers (делегують у channels_operations) ----
    def find_channel(self, channel_id: int):
        return cho.find_channel(self.db, channel_id)

    def find_channel_by_link(self, raw_url: str):
        return cho.find_channel_by_link(self.db, raw_url)

    def get_channel_id_by_url(self, raw_url: str):
        return cho.get_channel_id_by_url(self.db, raw_url)

    def upsert_channel(
        self,
        channel_id: int,
        username: Optional[str],
        title: Optional[str],
        owner_display: Optional[str],
        owner_username: Optional[str],
        last_status: Optional[str],
    ) -> None:
        return cho.upsert_channel(
            self.db,
            channel_id,
            username,
            title,
            owner_display,
            owner_username,
            last_status,
        )

    def add_link(
        self,
        channel_id: Optional[int],
        raw_url: str,
        kind: Optional[str],
        batch_msg_id: Optional[int],
        owner_display: Optional[str],
        owner_username: Optional[str],
    ) -> None:
        return cho.add_link(
            self.db,
            channel_id,
            raw_url,
            kind,
            batch_msg_id,
            owner_display,
            owner_username,
        )

    # ---- Context manager protocol ----
    def __exit__(self, exc_type, exc, tb):
        try:
            if exc:
                self.db.rollback()
            else:
                self.db.commit()
        finally:
            if self._own_session:
                self.db.close()
        return False


def get_dal_service() -> DALService:
    """
    Швидкий конструктор із власною SessionLocal (автоматичний commit/close у __exit__).
    """
    return DALService()
