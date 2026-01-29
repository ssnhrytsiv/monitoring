"""
DAO for membership / invite_map / invite_status / url_cache.
Класовий стиль: інстанс приймає Session у конструкторі, методи працюють через self.db.
"""
import logging
import time
from typing import Optional, Tuple

from sqlalchemy import case, delete
from sqlalchemy.orm import Session

from app.admin_bot.db import models as m
from app.services import models as sm  # InviteCheck/RequestedCheck live here

log = logging.getLogger(__name__)

FINAL_GLOBAL = ("joined", "already", "requested", "invalid", "private")
FINAL_PER_ACC = ("joined", "already", "requested", "invalid", "private", "blocked", "too_many")


def _now_ts() -> int:
    return int(time.time())


def _extract_invite_hash(inv_or_url: str) -> Optional[str]:
    """
    Повертає чистий invite-hash із:
      - https://t.me/+XXXXXXXX
      - https://t.me/joinchat/XXXXXXXX
    або None, якщо це не інвайт.
    Приймає також уже чистий хеш (без пробілів та '/').
    """
    if not inv_or_url:
        return None
    s = str(inv_or_url)
    s = s.replace("\u200b", "").replace("\u200e", "").replace("\u200f", "").strip()
    try:
        if "/+" in s:
            return s.rsplit("/", 1)[-1].replace("+", "").strip()
        if "joinchat/" in s:
            return s.rsplit("joinchat/", 1)[-1].strip()
        if "/" not in s and " " not in s:
            return s
    except Exception:
        return None
    return None


class MembershipDAO:
    def __init__(self, db: Session):
        self.db = db

    # ---------- membership (пер-акаунтний стан у каналі) ----------

    def upsert_membership(self, account: str, channel_id: int, status: str) -> None:
        membership = (
            self.db.query(m.Membership)
            .filter(m.Membership.channel_id == int(channel_id), m.Membership.account == account)
            .one_or_none()
        )
        now = _now_ts()
        if membership:
            membership.status = status
            membership.ts = now
        else:
            self.db.add(
                m.Membership(
                    channel_id=int(channel_id),
                    account=account,
                    status=status,
                    ts=now,
                )
            )
        self.db.commit()

    def get_membership(self, account: str, channel_id: int) -> Optional[str]:
        membership_row = (
            self.db.query(m.Membership.status)
            .filter(m.Membership.channel_id == int(channel_id), m.Membership.account == account)
            .limit(1)
            .one_or_none()
        )
        return membership_row[0] if membership_row else None

    def any_final_for_channel(self, channel_id: int) -> Optional[str]:
        membership_row = (
            self.db.query(m.Membership.status)
            .filter(m.Membership.channel_id == int(channel_id), m.Membership.status.in_(FINAL_GLOBAL))
            .limit(1)
            .one_or_none()
        )
        return membership_row[0] if membership_row else None

    def get_any_session_for_channel(self, channel_id: int) -> Optional[str]:
        """
        Повертає якусь сесію (account) для channel_id, пріоритезуючи joined/already/requested.
        """
        priority = case(
            (m.Membership.status.in_(("joined", "already")), 1),
            (m.Membership.status == "requested", 2),
            else_=3,
        )
        row = (
            self.db.query(m.Membership.account, m.Membership.status)
            .filter(m.Membership.channel_id == int(channel_id))
            .order_by(priority, m.Membership.ts.desc())
            .limit(1)
            .one_or_none()
        )
        if not row:
            log.debug("membership: session_lookup channel_id=%s -> none", channel_id)
            return None
        account_val, status_val = row
        log.debug("membership: session_lookup channel_id=%s -> account=%s status=%s", channel_id, account_val, status_val)
        return str(account_val)

    def get_session_by_channel(self, channel_id: int) -> Optional[str]:
        """Аліас для get_any_session_for_channel — для читабельності викликів."""
        return self.get_any_session_for_channel(channel_id)

    def delete_membership(self, account: str, channel_id: int) -> int:
        """
        Видаляє запис membership для конкретної сесії в каналі.
        Повертає кількість видалених рядків.
        """
        if not account or channel_id is None:
            return 0
        deleted = (
            self.db.query(m.Membership)
            .filter(m.Membership.channel_id == int(channel_id), m.Membership.account == account)
            .delete(synchronize_session=False)
        )
        self.db.commit()
        return deleted or 0

    # ---------- invite_map (інвайт-хеш -> channel_id, title) ----------

    def map_invite_set(self, invite_or_hash: str, channel_id: Optional[int], title: Optional[str] = None) -> None:
        h = _extract_invite_hash(invite_or_hash)
        if not h:
            return
        now = _now_ts()
        invite_map = self.db.query(m.InviteMap).filter(m.InviteMap.invite_hash == h).one_or_none()
        if invite_map:
            invite_map.channel_id = int(channel_id) if channel_id is not None else None
            if title is not None:
                invite_map.title = title
            invite_map.updated_at = now
        else:
            self.db.add(
                m.InviteMap(
                    invite_hash=h,
                    channel_id=int(channel_id) if channel_id is not None else None,
                    title=title,
                    updated_at=now,
                )
            )
        self.db.commit()

    def map_invite_get(self, invite_or_hash: str) -> Tuple[Optional[int], Optional[str]]:
        h = _extract_invite_hash(invite_or_hash)
        if not h:
            return None, None
        invite_map_row = (
            self.db.query(m.InviteMap.channel_id, m.InviteMap.title)
            .filter(m.InviteMap.invite_hash == h)
            .limit(1)
            .one_or_none()
        )
        if not invite_map_row:
            return None, None
        cid, title = invite_map_row
        return (int(cid) if cid is not None else None, title)

    # ---------- invite_status (статус інвайту за invite_hash) ----------

    def invite_status_get(self, invite_or_hash: str) -> Optional[str]:
        h = _extract_invite_hash(invite_or_hash)
        if not h:
            return None
        invite_status_row = (
            self.db.query(m.InviteStatus.status)
            .filter(m.InviteStatus.invite_hash == h)
            .limit(1)
            .one_or_none()
        )
        return invite_status_row[0] if invite_status_row else None

    def invite_status_put(self, invite_or_hash: str, status: str) -> None:
        h = _extract_invite_hash(invite_or_hash)
        if not h:
            return
        now = _now_ts()
        invite_status = self.db.query(m.InviteStatus).filter(m.InviteStatus.invite_hash == h).one_or_none()
        if invite_status:
            invite_status.status = status
            invite_status.ts = now
        else:
            self.db.add(m.InviteStatus(invite_hash=h, status=status, ts=now))
        self.db.commit()

    def invite_status_delete(self, invite_hashes: list[str], statuses: Optional[list[str]] = None) -> int:
        hashes = [h for h in (invite_hashes or []) if h]
        if not hashes:
            return 0
        q = self.db.query(m.InviteStatus).filter(m.InviteStatus.invite_hash.in_(hashes))
        if statuses:
            st = [s for s in statuses if s]
            if not st:
                return 0
            q = q.filter(m.InviteStatus.status.in_(st))
        deleted = q.delete(synchronize_session=False)
        self.db.commit()
        return deleted or 0

    def invite_status_put_for_channel(self, channel_id: int, status: str) -> int:
        if channel_id is None:
            return 0
        hashes = (
            self.db.query(m.InviteMap.invite_hash)
            .filter(m.InviteMap.channel_id == int(channel_id))
            .all()
        )
        hashes_list = [h[0] for h in hashes if h and h[0]]
        if not hashes_list:
            return 0
        now_ts = _now_ts()
        for h in hashes_list:
            invite_status = self.db.query(m.InviteStatus).filter(m.InviteStatus.invite_hash == h).one_or_none()
            if invite_status:
                invite_status.status = status
                invite_status.ts = now_ts
            else:
                self.db.add(m.InviteStatus(invite_hash=h, status=status, ts=now_ts))
        self.db.commit()
        return len(hashes_list)

    def bump_requested_attempt(self, invite_or_hash: str) -> int:
        h = _extract_invite_hash(invite_or_hash)
        if not h:
            return 0
        day = int(time.time()) // 86400
        attempt = (
            self.db.query(m.InviteAttempt)
            .filter(m.InviteAttempt.invite_hash == h, m.InviteAttempt.day == day)
            .one_or_none()
        )
        attempts = 0
        if attempt:
            attempts = attempt.attempts + 1
            attempt.attempts = attempts
        else:
            attempts = 1
            self.db.add(m.InviteAttempt(invite_hash=h, day=day, attempts=attempts))
        self.db.commit()
        return attempts

    def invite_check_last_session(self, invite_or_hash: str) -> Optional[str]:
        h = _extract_invite_hash(invite_or_hash)
        if not h:
            return None
        rec = (
            self.db.query(sm.InviteCheck.session)
            .filter(sm.InviteCheck.invite_hash == h)
            .order_by(sm.InviteCheck.noted_at.desc())
            .limit(1)
            .one_or_none()
        )
        return rec[0] if rec else None

    # ---------- url_cache (статус по URL) ----------

    def url_put(self, url: str, status: str) -> None:
        if not url:
            return
        now = _now_ts()
        url_cache = self.db.query(m.UrlCache).filter(m.UrlCache.url == url).one_or_none()
        if url_cache:
            url_cache.status = status
            url_cache.ts = now
        else:
            self.db.add(m.UrlCache(url=url, status=status, ts=now))
        self.db.commit()

    def url_get(self, url: str) -> Optional[str]:
        if not url:
            return None
        url_cache = self.db.query(m.UrlCache.status).filter(m.UrlCache.url == url).one_or_none()
        return url_cache[0] if url_cache else None

    def url_delete(self, urls: list[str], statuses: Optional[list[str]] = None) -> int:
        if not urls:
            return 0
        q = self.db.query(m.UrlCache).filter(m.UrlCache.url.in_(urls))
        if statuses:
            st = [s for s in statuses if s]
            if not st:
                return 0
            q = q.filter(m.UrlCache.status.in_(st))
        deleted = q.delete(synchronize_session=False)
        self.db.commit()
        return deleted or 0


# Функціональні обгортки для сумісності
def upsert_membership(db: Session, account: str, channel_id: int, status: str) -> None:
    return MembershipDAO(db).upsert_membership(account, channel_id, status)


def get_membership(db: Session, account: str, channel_id: int) -> Optional[str]:
    return MembershipDAO(db).get_membership(account, channel_id)


def any_final_for_channel(db: Session, channel_id: int) -> Optional[str]:
    return MembershipDAO(db).any_final_for_channel(channel_id)


def get_any_session_for_channel(db: Session, channel_id: int) -> Optional[str]:
    return MembershipDAO(db).get_any_session_for_channel(channel_id)


def map_invite_set(db: Session, invite_or_hash: str, channel_id: Optional[int], title: Optional[str] = None) -> None:
    return MembershipDAO(db).map_invite_set(invite_or_hash, channel_id, title)


def map_invite_get(db: Session, invite_or_hash: str) -> Tuple[Optional[int], Optional[str]]:
    return MembershipDAO(db).map_invite_get(invite_or_hash)


def invite_status_get(db: Session, invite_or_hash: str) -> Optional[str]:
    return MembershipDAO(db).invite_status_get(invite_or_hash)


def invite_status_put(db: Session, invite_or_hash: str, status: str) -> None:
    return MembershipDAO(db).invite_status_put(invite_or_hash, status)


def invite_status_delete(db: Session, invite_hashes: list[str], statuses: Optional[list[str]] = None) -> int:
    return MembershipDAO(db).invite_status_delete(invite_hashes, statuses)


def invite_status_put_for_channel(db: Session, channel_id: int, status: str) -> int:
    return MembershipDAO(db).invite_status_put_for_channel(channel_id, status)


def bump_requested_attempt(db: Session, invite_or_hash: str) -> int:
    return MembershipDAO(db).bump_requested_attempt(invite_or_hash)


def invite_check_last_session(db: Session, invite_or_hash: str) -> Optional[str]:
    return MembershipDAO(db).invite_check_last_session(invite_or_hash)


def url_put(db: Session, url: str, status: str) -> None:
    return MembershipDAO(db).url_put(url, status)


def url_get(db: Session, url: str) -> Optional[str]:
    return MembershipDAO(db).url_get(url)


def url_delete(db: Session, urls: list[str], statuses: Optional[list[str]] = None) -> int:
    return MembershipDAO(db).url_delete(urls, statuses)


def get_session_by_channel(db: Session, channel_id: int) -> Optional[str]:
    return MembershipDAO(db).get_session_by_channel(channel_id)


def delete_membership(db: Session, account: str, channel_id: int) -> int:
    return MembershipDAO(db).delete_membership(account, channel_id)
