from __future__ import annotations

from typing import Optional, List
import logging
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.utils.time_utils import moscow_timestamp

from app.db import models as m
from app.DAL import session_scope
from app.DAL import channels_operations as cho
from app.DAL import admins_operations as admin_ops
from app.DAL import membership_operations as mem_db
from app.DAL import invite_cache_operations as ic_db
from app.DAL import network_channels_operations as net_db
from app.DAL import link_operations as link_db
from app.services import link_queue
from app.utils.link_parser import sanitize_link
from app.DAL.schemas import AdminRecord

log = logging.getLogger("admin_bot.services.admins")
import asyncio


def _expand_url_variants(url: str) -> list[str]:
    """
    Повертає список варіантів URL (raw, sanitized, joinchat/+ заміна) для надійного очищення кешів.
    """
    out = set()
    if url:
        base = (url or "").replace("\u200b", "").replace("\u200e", "").replace("\u200f", "").strip()
        if base:
            out.add(base)
        try:
            clean = sanitize_link(base) or base
            out.add(clean)
        except Exception:
            pass
        if "joinchat/" in base:
            out.add(base.replace("joinchat/", "+"))
        if base.startswith("https://t.me/+"):
            out.add(base.replace("https://t.me/+", "https://t.me/joinchat/"))
    return list(out)


def _sample(items: list[str], limit: int = 5) -> str:
    if not items:
        return "[]"
    head = items[:limit]
    more = "" if len(items) <= limit else f"... (+{len(items) - limit})"
    return f"{head}{more}"

def _count_url_cache(urls: list[str], db: Optional[Session] = None) -> int:
    """
    Повертає кількість записів у url_cache для списку URL (будь-які статуси).
    """
    urls = [u for u in urls if u]
    if not urls:
        return 0
    try:
        if db is None:
            return 0
        return db.query(m.UrlCache).filter(m.UrlCache.url.in_(urls)).count()
    except Exception:
        return 0


def _delete_url_cache_db(db: Session, urls: list[str], statuses: Optional[list[str]]) -> int:
    """
    Видаляє url_cache через поточний db-коннект (уникає locks окремого sqlite-з'єднання).
    """
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
    rc = db.execute(text(sql), params).rowcount or 0
    return rc


def get_or_create_admin(
    db: Session,
    tg_id: Optional[int],
    username: Optional[str],
    display: Optional[str],
) -> m.Admin:
    return admin_ops.get_or_create_admin_entity(db, tg_id=tg_id, username=username, display=display)


def list_admins(db: Session) -> List[AdminRecord]:
    return admin_ops.list_admins(db)


def get_admin_by_display(db: Session, display: str) -> Optional[AdminRecord]:
    return admin_ops.get_admin_by_display(db, display)


def get_admin_by_id(db: Session, admin_id: int) -> Optional[AdminRecord]:
    return admin_ops.get_admin_by_id(db, admin_id)


def toggle_admin_new(db: Session, admin_id: int) -> Optional[m.Admin]:
    return admin_ops.toggle_admin_new_flag(db, admin_id)


def update_admin_params(
    db: Session,
    admin_id: int,
    *,
    cpm: Optional[float] = None,
    price: Optional[float] = None,
    subscribers: Optional[int] = None,
) -> Optional[m.Admin]:
    return admin_ops.update_admin_params(db, admin_id, cpm=cpm, price=price, subscribers=subscribers)


def remove_admin(db: Session, admin_id: int) -> bool:
    return admin_ops.remove_admin(db, admin_id)


def collect_admin_delete_info(admin_id: int) -> dict:
    with session_scope() as db:
        admin_obj = admin_ops.get_admin_by_id(db, admin_id)
        if not admin_obj:
            return {"exists": False, "chan_ids": [], "acct_map": {}}
        chan_ids = admin_ops.list_admin_channel_ids(db, admin_id)
        net_chan_ids = net_db.list_channel_ids_for_admin_networks(db, admin_id)
        if net_chan_ids:
            chan_ids = list(set(chan_ids) | set(net_chan_ids))
        pairs = mem_db.list_membership_account_pairs(db, chan_ids)
        acct_map = {}
        for account, cid in pairs:
            acct_map.setdefault(account, set()).add(cid)
        return {"exists": True, "chan_ids": chan_ids, "acct_map": acct_map}


def remove_admin_deep(admin_id: int, cleanup_channels: bool = True) -> dict:
    """
    Видаляє адміна та пов'язані дані:
    - канали цього адміна (channels.owner_admin_id)
    - networks / network_channels цього адміна
    - самого адміна
    Опційно чистить канали/інвайти/мембершип/лінки, якщо channel більше ніде не використовується.
    """
    with session_scope() as db:
        admin_obj = admin_ops.get_admin_by_id(db, admin_id)
        if not admin_obj:
            return {
                "admin_deleted": 0,
                "admin_channels_deleted": 0,
                "network_channels_deleted": 0,
                "networks_deleted": 0,
                "membership_deleted": 0,
                "invite_cache_deleted": 0,
                "owner_conflicts_deleted": 0,
                "links_deleted": 0,
                "url_cache_deleted": 0,
                "channels_deleted": 0,
                "membership_status_deleted": 0,
                "link_queue_deleted": 0,
            }

        chan_ids = admin_ops.list_admin_channel_ids(db, admin_id)
        net_chan_ids = net_db.list_channel_ids_for_admin_networks(db, admin_id)
        if net_chan_ids:
            chan_ids = list(set(chan_ids) | set(net_chan_ids))
        log.info("remove_admin_deep admin_id=%s chan_ids=%s", admin_id, chan_ids)

        ac_deleted = 0
        net_deleted_count, net_ids = net_db.delete_networks_by_admin(db, admin_id)
        nc_deleted = net_db.delete_network_channels_by_networks(db, net_ids) if net_ids else 0
        adm_deleted = admin_ops.delete_admin_by_id(db, admin_id)

        mem_deleted = 0
        url_cache_deleted = 0
        invite_cache_deleted = 0
        owner_conflicts_deleted = 0
        links_deleted = 0
        channels_deleted = 0
        membership_status_deleted = 0
        link_queue_deleted = 0

        urls_for_cleanup: list[str] = []
        if cleanup_channels and chan_ids:
            link_records = cho.list_links_for_channels(db, chan_ids)
            for u in [rec.url_norm for rec in link_records if rec and rec.url_norm]:
                urls_for_cleanup.extend(_expand_url_variants(u))
            pre_count = _count_url_cache(urls_for_cleanup, db) if urls_for_cleanup else 0
            if urls_for_cleanup:
                log.info("remove_admin_deep urls_for_cleanup(chan) count=%s sample=%s", len(urls_for_cleanup), _sample(urls_for_cleanup))
                log.info("remove_admin_deep url_cache pre-count (chan)=%s", pre_count)
            mem_deleted = mem_db.delete_memberships_by_channels(db, chan_ids)
            membership_status_deleted = mem_db.delete_membership_status_by_channels(db, chan_ids)
            owner_conflicts_deleted = mem_db.owner_conflict_delete_by_channels(db, chan_ids)
            links_deleted = link_db.delete_links_by_channels(db, chan_ids)
            try:
                url_cache_deleted = admin_ops.delete_url_cache(db, urls_for_cleanup, ["already", "joined"])
            except Exception as e:
                log.exception("remove_admin_deep url_cache delete (chan) failed: %s", e)
                url_cache_deleted = 0
            if pre_count > 0 and url_cache_deleted == 0:
                try:
                    url_cache_deleted = admin_ops.delete_url_cache(db, urls_for_cleanup, None)
                    log.info("remove_admin_deep chan_cleanup fallback url_cache_deleted=%s", url_cache_deleted)
                except Exception as e:
                    log.exception("remove_admin_deep url_cache delete fallback (chan) failed: %s", e)
            log.info(
                "remove_admin_deep chan_cleanup mem_deleted=%s links_deleted=%s url_cache_deleted=%s url_cache_post=%s",
                mem_deleted,
                links_deleted,
                url_cache_deleted,
                _count_url_cache(urls_for_cleanup, db),
            )

            keep_ids = set(net_db.list_channel_ids_for_admin_networks(db, admin_id))
            delete_ids = [cid for cid in chan_ids if cid not in keep_ids]
            if delete_ids:
                channels_deleted = cho.delete_channels_by_ids(db, delete_ids)
            try:
                invite_cache_deleted = ic_db.invite_cache_delete_by_channels(db, chan_ids)
            except Exception as e:
                log.exception("remove_admin_deep invite_cache delete failed: %s", e)

        owner_user = admin_obj.username
        owner_admin_id = admin_obj.id

    try:
        link_queue_deleted = link_queue.delete_by_owner(
            owner_admin_id=admin_id,
            urls=list(set(urls_for_cleanup)) if urls_for_cleanup else None,
        )
    except Exception as e:
        log.exception("remove_admin_deep link_queue cleanup failed: %s", e)
        link_queue_deleted = 0

    return {
        "admin_deleted": adm_deleted,
        "admin_channels_deleted": ac_deleted,
        "network_channels_deleted": nc_deleted,
        "networks_deleted": net_deleted_count,
        "membership_deleted": mem_deleted,
        "invite_cache_deleted": invite_cache_deleted,
        "owner_conflicts_deleted": owner_conflicts_deleted,
        "links_deleted": links_deleted,
        "url_cache_deleted": url_cache_deleted,
        "channels_deleted": channels_deleted,
        "membership_status_deleted": membership_status_deleted,
        "link_queue_deleted": link_queue_deleted,
    }


def attach_channel(db: Session, admin_id: int, channel_id: int) -> dict:
    """
    Прив'язує канал до адміна, але блокує, якщо канал уже закріплений за іншим адміном.
    Повертає dict:
      {"status": "added"|"exists"|"conflict", "admin_id": <int|None>}
    """
    ch = cho.get_channel_by_id(db, channel_id)
    if not ch:
        return {"status": "not_found", "admin_id": None}
    if ch.owner_admin_id:
        if ch.owner_admin_id == admin_id:
            return {"status": "exists", "admin_id": admin_id}
        return {"status": "conflict", "admin_id": ch.owner_admin_id}
    ch.owner_admin_id = admin_id
    db.commit()
    db.refresh(ch)
    return {"status": "added", "admin_id": admin_id}


def list_channels_for_admin(db: Session, admin_id: int) -> List[m.Channel]:
    admin = admin_ops.get_admin_by_id(db, admin_id)
    if not admin:
        return []
    chan_ids = [ac.channel_id for ac in admin.channels]
    if not chan_ids:
        return []
    return cho.list_channels_by_ids(db, chan_ids)


def ensure_channel(db: Session, channel_id: int, username: Optional[str] = None, title: Optional[str] = None) -> m.Channel:
    """
    Створює канал або доповнює відсутні username/title для існуючого.
    DAL сам виконує commit.
    """
    cho.upsert_channel(db, channel_id=channel_id, username=username, title=title, owner_admin_id=None)
    return cho.get_channel_by_id(db, channel_id)


def get_admin_for_refresh(*, admin: Optional[AdminRecord]) -> Optional[AdminRecord]:
    with session_scope() as db:
        if admin and admin.id is not None:
            return admin_ops.get_admin_by_record(db, admin)
        return None


def add_admin_and_enqueue_links(
    *,
    urls: list[str],
    display: str,
    username: Optional[str],
    chat_id: Optional[int],
    msg_id: Optional[int],
) -> tuple[int, str, int]:
    if not urls:
        return 0, "", 0
    admin = admin_ops.get_admin_by_display_autosession(display, username=username) if display else None
    admin_id = admin.id if admin and admin.id is not None else None
    batch_id = f"adminbot:{chat_id}:{moscow_timestamp()}"
    added = link_queue.enqueue(
        urls,
        batch_id=batch_id,
        origin_msg=msg_id,
        owner_admin_id=admin_id,
        adopt_existing=True,
        reset_next_try=True,
    )
    return admin_id or 0, batch_id, added
