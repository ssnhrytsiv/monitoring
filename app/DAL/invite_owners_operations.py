"""
DAO for invite_owners table.
"""
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.admin_bot.db import models as m


class InviteOwnersDAO:
    """
    Класовий DAO: приймає Session у конструкторі, працює через self.db.
    """

    def __init__(self, db: Session):
        self.db = db

    def set_invite_owner(self, invite_hash: str, owner_display: Optional[str], owner_username: Optional[str]) -> None:
        if not invite_hash:
            return
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        invite_owner = (
            self.db.query(m.InviteOwner)
            .filter(m.InviteOwner.invite_hash == invite_hash)
            .one_or_none()
        )
        if invite_owner:
            invite_owner.owner_display = owner_display
            invite_owner.owner_username = owner_username
            invite_owner.created_at = now
        else:
            self.db.add(
                m.InviteOwner(
                    invite_hash=invite_hash,
                    owner_display=owner_display,
                    owner_username=owner_username,
                    created_at=now,
                )
            )
        self.db.commit()

    def get_invite_owner(self, invite_hash: str) -> Optional[dict]:
        if not invite_hash:
            return None
        invite_owner = (
            self.db.query(m.InviteOwner)
            .filter(m.InviteOwner.invite_hash == invite_hash)
            .one_or_none()
        )
        if not invite_owner:
            return None
        return {
            "invite_hash": invite_owner.invite_hash,
            "owner_display": invite_owner.owner_display,
            "owner_username": invite_owner.owner_username,
            "created_at": invite_owner.created_at,
        }


# Збережені функціональні обгортки для сумісності
def set_invite_owner(db: Session, invite_hash: str, owner_display: Optional[str], owner_username: Optional[str]) -> None:
    return InviteOwnersDAO(db).set_invite_owner(invite_hash, owner_display, owner_username)


def get_invite_owner(db: Session, invite_hash: str) -> Optional[dict]:
    return InviteOwnersDAO(db).get_invite_owner(invite_hash)
