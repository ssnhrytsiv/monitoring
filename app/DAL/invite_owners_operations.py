"""
DAO for invite_owners table.
"""
import time
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.db import models as m


@dataclass
class InviteOwnerRecord:
    invite_hash: str
    owner_username: Optional[str]
    owner_admin_id: Optional[int]
    created_at: str


class InviteOwnersDAO:
    """
    Класовий DAO: приймає Session у конструкторі, працює через self.db.
    """

    def __init__(self, db: Session):
        self.db = db

    def set_invite_owner(
        self,
        invite_hash: str,
        owner_username: Optional[str],
        owner_admin_id: Optional[int] = None,
    ) -> None:
        if not invite_hash:
            return
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        invite_owner = (
            self.db.query(m.InviteOwner)
            .filter(m.InviteOwner.invite_hash == invite_hash)
            .one_or_none()
        )
        if invite_owner:
            invite_owner.owner_username = owner_username
            invite_owner.owner_admin_id = owner_admin_id
            invite_owner.created_at = now
        else:
            self.db.add(
                m.InviteOwner(
                    invite_hash=invite_hash,
                    owner_username=owner_username,
                    owner_admin_id=owner_admin_id,
                    created_at=now,
                )
            )
        self.db.commit()

    def get_invite_owner(self, invite_hash: str) -> Optional[InviteOwnerRecord]:
        if not invite_hash:
            return None
        invite_owner = (
            self.db.query(m.InviteOwner)
            .filter(m.InviteOwner.invite_hash == invite_hash)
            .one_or_none()
        )
        if not invite_owner:
            return None
        return InviteOwnerRecord(
            invite_hash=invite_owner.invite_hash,
            owner_username=invite_owner.owner_username,
            owner_admin_id=invite_owner.owner_admin_id,
            created_at=invite_owner.created_at,
        )


# Збережені функціональні обгортки для сумісності
def set_invite_owner(
    db: Session,
    invite_hash: str,
    owner_username: Optional[str],
    owner_admin_id: Optional[int] = None,
) -> None:
    return InviteOwnersDAO(db).set_invite_owner(invite_hash, owner_username, owner_admin_id)


def get_invite_owner(db: Session, invite_hash: str) -> Optional[InviteOwnerRecord]:
    return InviteOwnersDAO(db).get_invite_owner(invite_hash)
