from __future__ import annotations

from typing import Optional, List
import logging
from sqlalchemy.orm import Session
from sqlalchemy import delete, text, select
from app.utils.time_utils import moscow_timestamp

from app.db import models as m
from app.DAL import session_scope
from app.DAL import channels_operations as cho
from app.DAL import admins_operations as admin_ops
from app.DAL import membership_operations as mem_db
from app.DAL import network_channels_operations as net_db
from app.services import link_queue
from app.utils.link_parser import sanitize_link
from app.DAL.admins_operations import AdminSnapshot

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
    admin = None
    if tg_id is not None:
        snap = admin_ops.get_admin_by_tg_id(db, tg_id)
        if snap:
            admin = admin_ops.get_admin_entity_by_id(db, snap.id)
    if admin is None and username:
        admin = admin_ops.get_admin_by_username(db, username)
    if admin is None and display:
        admin = admin_ops.get_admin_by_display(db, display)

    if admin:
        if tg_id is not None:
            admin.tg_id = tg_id
        if username:
            admin.username = username
        if display:
            admin.display = display
    else:
        admin = m.Admin(tg_id=tg_id, username=username, display=display)
        db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def find_admin(
    db: Session,
    *,
    tg_id: Optional[int],
    username: Optional[str],
    display: Optional[str],
) -> Optional[m.Admin]:
    """
    Повертає існуючого адміна за tg_id/username/display без створення нового.
    """
    if tg_id is not None:
        snap = admin_ops.get_admin_by_tg_id(db, tg_id)
        if snap:
            found = admin_ops.get_admin_entity_by_id(db, snap.id)
            if found:
                return found
    if username:
        admin = admin_ops.get_admin_by_username(db, username)
        if admin:
            return admin
    if display:
        admin = admin_ops.get_admin_by_display(db, display)
        if admin:
            return admin
    return None


def list_admins(db: Session) -> List[m.Admin]:
    return admin_ops.list_admins(db)


def get_admin_by_id(db: Session, admin_id: int) -> Optional[m.Admin]:
    return admin_ops.get_admin_by_id(db, admin_id)


def get_admin_snapshot_by_id(db: Session, admin_id: int) -> Optional[admin_ops.AdminSnapshot]:
    return admin_ops.get_admin_by_id(db, admin_id)


def toggle_admin_new(db: Session, admin_id: int) -> Optional[m.Admin]:
    admin = admin_ops.get_admin_entity_by_id(db, admin_id)
    if not admin:
        return None
    current = getattr(admin, "is_new", 0) or 0
    admin.is_new = 0 if current else 1
    db.commit()
    db.refresh(admin)
    return admin


def update_admin_params(
    db: Session,
    admin_id: int,
    *,
    cpm: Optional[float] = None,
    price: Optional[float] = None,
    subscribers: Optional[int] = None,
) -> Optional[m.Admin]:
    admin = admin_ops.get_admin_by_id(db, admin_id)
    if not admin:
        return None
    if cpm is not None:
        admin.cpm = float(cpm)
    if price is not None:
        admin.price = float(price)
    if subscribers is not None:
        admin.subscribers = int(subscribers)
    db.commit()
    db.refresh(admin)
    return admin


def remove_admin(db: Session, admin_id: int) -> bool:
    res = db.execute(delete(m.Admin).where(m.Admin.id == admin_id))
    db.commit()
    return res.rowcount > 0


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
    - admin_channels
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
                "invite_owners_deleted": 0,
                "links_no_channel_deleted": 0,
                "link_queue_deleted": 0,
            }

        chan_ids = admin_ops.list_admin_channel_ids(db, admin_id)
        net_chan_ids = net_db.list_channel_ids_for_admin_networks(db, admin_id)
        if net_chan_ids:
            chan_ids = list(set(chan_ids) | set(net_chan_ids))
        log.info("remove_admin_deep admin_id=%s chan_ids=%s", admin_id, chan_ids)

        ac_deleted = admin_ops.delete_admin_channels_by_admin(db, admin_id)
        net_deleted_count, net_ids = admin_ops.delete_networks_by_admin(db, admin_id)
        nc_deleted = admin_ops.delete_network_channels_by_networks(db, net_ids) if net_ids else 0
        adm_deleted = m.delete_admin_by_id(db, admin_id)

        mem_deleted = 0
        url_cache_deleted = 0
        invite_cache_deleted = 0
        owner_conflicts_deleted = 0
        invite_owners_deleted = 0
        links_no_channel_deleted = 0
        links_deleted = 0
        channels_deleted = 0
        membership_status_deleted = 0
        link_queue_deleted = 0

        urls_for_cleanup: list[str] = []
        if cleanup_channels and chan_ids:
            raw_urls = cho.list_links_raw_for_channels(db, chan_ids)
            for u in raw_urls:
                urls_for_cleanup.extend(_expand_url_variants(u))
            pre_count = _count_url_cache(urls_for_cleanup, db) if urls_for_cleanup else 0
            if urls_for_cleanup:
                log.info("remove_admin_deep urls_for_cleanup(chan) count=%s sample=%s", len(urls_for_cleanup), _sample(urls_for_cleanup))
                log.info("remove_admin_deep url_cache pre-count (chan)=%s", pre_count)
            mem_deleted = admin_ops.delete_memberships_by_channels(db, chan_ids)
            membership_status_deleted = admin_ops.delete_membership_status_by_channels(db, chan_ids)
            owner_conflicts_deleted = admin_ops.delete_owner_conflict_by_channels(db, chan_ids)
            links_deleted = admin_ops.delete_links_by_channels(db, chan_ids)
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

            keep_ids = set(cho.list_all_admin_channel_ids(db)) | set(net_db.list_channel_ids_for_admin_networks(db, admin_id))
            delete_ids = [cid for cid in chan_ids if cid not in keep_ids]
            if delete_ids:
                channels_deleted = admin_ops.delete_channels_by_ids(db, delete_ids)
            try:
                invite_cache_deleted = mem_db.invite_cache_delete_by_channels(db, chan_ids)
            except Exception as e:
                log.exception("remove_admin_deep invite_cache delete failed: %s", e)

        owner_user = admin_obj.username
        owner_admin_id = admin_obj.id
        invite_owners_deleted += admin_ops.delete_invite_owners_by_owner(db, owner_admin_id, owner_user)
        db.commit()

        links_deleted_nc = admin_ops.delete_links_no_channel_by_owner(db, owner_admin_id, owner_user)
        links_no_channel_deleted += links_deleted_nc
        db.commit()

        owner_urls_raw = admin_ops.list_owner_links_no_channel(db, owner_admin_id, owner_user)
        owner_urls = []
        for u in owner_urls_raw:
            owner_urls.extend(_expand_url_variants(u))
        urls_for_cleanup.extend(owner_urls)

        if owner_urls:
            try:
                url_cache_deleted += admin_ops.delete_url_cache(db, owner_urls, ["already", "joined"])
            except Exception as e:
                log.exception("remove_admin_deep url_cache delete (owner) failed: %s", e)
            if _count_url_cache(owner_urls, db) > 0 and url_cache_deleted == 0:
                try:
                    url_cache_deleted += admin_ops.delete_url_cache(db, owner_urls, None)
                    log.info("remove_admin_deep owner_cleanup fallback url_cache_deleted=%s", url_cache_deleted)
                except Exception as e:
                    log.exception("remove_admin_deep url_cache delete fallback (owner) failed: %s", e)

        db.commit()

    try:
        link_queue_deleted = link_queue.delete_by_owner(
            owner_admin_id=admin_id,
            owner_username=owner_user,
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
        "invite_owners_deleted": invite_owners_deleted,
        "links_no_channel_deleted": links_no_channel_deleted,
        "link_queue_deleted": link_queue_deleted,
    }


def attach_channel(db: Session, admin_id: int, channel_id: int) -> dict:
    """
    Прив'язує канал до адміна, але блокує, якщо канал уже закріплений за іншим адміном.
    Повертає dict:
      {"status": "added"|"exists"|"conflict", "admin_id": <int|None>}
    """
    # Перевіряємо, чи вже прив'язаний до когось
    existing_link = admin_ops.get_admin_channel_for_channel(db, channel_id)
    if existing_link:
        if existing_link.admin_id == admin_id:
            return {"status": "exists", "admin_id": admin_id}
        else:
            return {"status": "conflict", "admin_id": existing_link.admin_id}

    link = m.AdminChannel(admin_id=admin_id, channel_id=channel_id)
    db.add(link)
    # також проставляємо owner_admin_id у channels, якщо ще не заповнено
    ch = cho.get_channel_by_id(db, channel_id)
    if ch and not ch.owner_admin_id:
        ch.owner_admin_id = admin_id
    db.commit()
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
    ch = cho.get_channel_by_id(db, channel_id)
    if ch:
        if username:
            ch.username = ch.username or username
        if title:
            ch.title = ch.title or title
        db.commit()
        db.refresh(ch)
        return ch
    ch = m.Channel(channel_id=channel_id, username=username, title=title)
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return ch


def get_admin_for_refresh(
    *,
    admin_id: Optional[int],
    from_user_id: Optional[int],
    from_username: Optional[str],
) -> Optional[AdminSnapshot]:
    with session_scope() as db:
        snap = None
        if admin_id:
            snap = admin_ops.get_admin_by_id(db, admin_id)
        if snap is None and from_user_id is not None:
            snap = admin_ops.get_admin_by_tg_id(db, from_user_id)
        if snap is None and from_username:
            snap = admin_ops.get_admin_by_username(db, from_username)
        return snap


def add_admin_and_enqueue_links(
    *,
    urls: list[str],
    display: str,
    username: Optional[str],
    raw_text: str,
    raw_html: str,
    entities: list,
    chat_id: Optional[int],
    msg_id: Optional[int],
    reply_msg,
) -> tuple[int, str, int]:
    if not urls:
        return 0, "", 0
    admin_id = None
    with session_scope() as db:
        existing_admin = find_admin(db, tg_id=None, username=username, display=display)
        if existing_admin:
            if username and existing_admin.username != username:
                existing_admin.username = username
            if display and existing_admin.display != display:
                existing_admin.display = display
            db.commit()
            db.refresh(existing_admin)
            admin_id = existing_admin.id if existing_admin else None
    batch_id = f"adminbot:{chat_id}:{moscow_timestamp()}"
    added = link_queue.enqueue(
        urls,
        batch_id=batch_id,
        origin_chat=chat_id,
        origin_msg=msg_id,
        owner_admin_id=admin_id,
        owner_username=username,
        adopt_existing=True,
        reset_next_try=True,
    )
    from app.admin_bot.services.subscription.subscription_worker import process_batch
    asyncio.create_task(
        process_batch(
            batch_id=batch_id,
            chat_id=chat_id,
            reply_msg=reply_msg,
            admin_id=admin_id,
            admin_display=display,
            admin_username=username,
            admin_tg_id=None,
            raw_text=raw_text,
            raw_html=raw_html or raw_text,
            entities=entities,
            original_urls=urls,
        )
    )
    return admin_id or 0, batch_id, added
