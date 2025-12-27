from __future__ import annotations

from typing import Optional, List
import logging
from sqlalchemy.orm import Session
from sqlalchemy import select, delete, text, or_

from admin_bot.db import models as m
from app.services import membership_db
from app.utils.tg_links import sanitize_link
import re

log = logging.getLogger("admin_bot.services.admins")


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

def _count_url_cache(urls: list[str]) -> int:
    """
    Повертає кількість записів у url_cache для списку URL (будь-які статуси).
    """
    if not urls:
        return 0
    try:
        with membership_db._conn() as c:  # type: ignore[attr-defined]
            placeholders = ",".join("?" for _ in urls)
            cur = c.execute(f"SELECT COUNT(*) FROM url_cache WHERE url IN ({placeholders})", tuple(urls))
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
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
        admin = db.execute(select(m.Admin).where(m.Admin.tg_id == tg_id)).scalar_one_or_none()
    if admin is None and username:
        admin = db.execute(select(m.Admin).where(m.Admin.username == username)).scalar_one_or_none()
    if admin is None and display:
        admin = db.execute(select(m.Admin).where(m.Admin.display == display)).scalar_one_or_none()

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
    admin = None

    if tg_id is not None:
        admin = db.execute(select(m.Admin).where(m.Admin.tg_id == tg_id)).scalar_one_or_none()
    if admin is None and username:
        admin = db.execute(select(m.Admin).where(m.Admin.username == username)).scalar_one_or_none()
    if admin is None and display:
        admin = db.execute(select(m.Admin).where(m.Admin.display == display)).scalar_one_or_none()
    return admin


def list_admins(db: Session) -> List[m.Admin]:
    return list(db.execute(select(m.Admin).order_by(m.Admin.id.desc())).scalars())


def get_admin_by_id(db: Session, admin_id: int) -> Optional[m.Admin]:
    return db.execute(select(m.Admin).where(m.Admin.id == admin_id)).scalar_one_or_none()


def remove_admin(db: Session, admin_id: int) -> bool:
    res = db.execute(delete(m.Admin).where(m.Admin.id == admin_id))
    db.commit()
    return res.rowcount > 0


def remove_admin_deep(db: Session, admin_id: int, cleanup_channels: bool = True) -> dict:
    """
    Видаляє адміна та пов'язані дані:
    - admin_channels
    - networks / network_channels цього адміна
    - самого адміна
    Опційно чистить канали/інвайти/мембершип/лінки, якщо channel більше ніде не використовується.
    """
    # Спершу дістаємо сам об'єкт адміна (для owner_display/username)
    admin_obj = db.execute(select(m.Admin).where(m.Admin.id == admin_id)).scalar_one_or_none()

    # Збираємо канали адміна
    chan_ids = [
        ac.channel_id
        for ac in db.execute(select(m.AdminChannel).where(m.AdminChannel.admin_id == admin_id)).scalars().all()
    ]
    log.debug("remove_admin_deep admin_id=%s chan_ids=%s", admin_id, chan_ids)

    # Прибираємо прив'язки admin_channels
    ac_deleted = db.execute(delete(m.AdminChannel).where(m.AdminChannel.admin_id == admin_id)).rowcount or 0
    # Прибираємо мережі та їх канали
    net_ids = list(db.execute(select(m.Network.id).where(m.Network.admin_id == admin_id)).scalars().all())
    nc_deleted = 0
    if net_ids:
        nc_deleted = db.execute(delete(m.NetworkChannel).where(m.NetworkChannel.network_id.in_(net_ids))).rowcount or 0
        db.execute(delete(m.Network).where(m.Network.id.in_(net_ids)))
    adm_deleted = db.execute(delete(m.Admin).where(m.Admin.id == admin_id)).rowcount or 0

    # Додаткове очищення
    mem_deleted = 0
    invite_map_deleted = 0
    invite_status_deleted = 0
    url_cache_deleted = 0
    owner_conflicts_deleted = 0
    invite_owners_deleted = 0
    links_no_channel_deleted = 0
    links_deleted = 0
    channels_deleted = 0
    membership_status_deleted = 0

    urls_for_cleanup: list[str] = []
    if cleanup_channels and chan_ids:
        # Зберемо всі URL цих каналів до видалення links
        for r in db.execute(select(m.Link.raw_url).where(m.Link.channel_id.in_(chan_ids))).all():
            if r and r[0]:
                urls_for_cleanup.extend(_expand_url_variants(r[0]))
        pre_count = _count_url_cache(urls_for_cleanup) if urls_for_cleanup else 0
        if urls_for_cleanup:
            log.debug("remove_admin_deep urls_for_cleanup(chan) count=%s sample=%s", len(urls_for_cleanup), _sample(urls_for_cleanup))
            log.debug("remove_admin_deep url_cache pre-count (chan)=%s", pre_count)
        # membership
        mem_deleted = db.execute(delete(m.Membership).where(m.Membership.channel_id.in_(chan_ids))).rowcount or 0
        # membership_status (raw table) — видаляємо лише якщо є колонка channel_id
        try:
            placeholders = ",".join([str(cid) for cid in chan_ids])
            membership_status_deleted = db.execute(
                text(f"DELETE FROM membership_status WHERE channel_id IN ({placeholders})")
            ).rowcount or 0
        except Exception:
            membership_status_deleted = 0  # таблиця/колонка може відрізнятись у схемі
        # invite_map + invite_status
        hashes = [h for h in db.execute(select(m.InviteMap.invite_hash).where(m.InviteMap.channel_id.in_(chan_ids))).scalars().all()]
        if hashes:
            invite_status_deleted = db.execute(delete(m.InviteStatus).where(m.InviteStatus.invite_hash.in_(hashes))).rowcount or 0
        invite_map_deleted = db.execute(delete(m.InviteMap).where(m.InviteMap.channel_id.in_(chan_ids))).rowcount or 0
        owner_conflicts_deleted = db.execute(delete(m.OwnerConflict).where(m.OwnerConflict.channel_id.in_(chan_ids))).rowcount or 0
        # links
        links_deleted = db.execute(delete(m.Link).where(m.Link.channel_id.in_(chan_ids))).rowcount or 0
        # url_cache у membership_db: прибираємо позитивні записи по знайдених URL
        try:
            url_cache_deleted = _delete_url_cache_db(db, urls_for_cleanup, ["already", "joined"])
        except Exception as e:
            log.exception("remove_admin_deep url_cache delete (chan) failed: %s", e)
            url_cache_deleted = 0
        # fallback: якщо знайшли рядки, але не видалили (можливо інший статус) — чистимо без фільтра статусів
        if pre_count > 0 and url_cache_deleted == 0:
            try:
                url_cache_deleted = _delete_url_cache_db(db, urls_for_cleanup, None)
                log.debug("remove_admin_deep chan_cleanup fallback url_cache_deleted=%s", url_cache_deleted)
            except Exception as e:
                log.exception("remove_admin_deep url_cache delete fallback (chan) failed: %s", e)
        log.debug(
            "remove_admin_deep chan_cleanup mem_deleted=%s invite_map_deleted=%s invite_status_deleted=%s links_deleted=%s url_cache_deleted=%s url_cache_post=%s",
            mem_deleted,
            invite_map_deleted,
            invite_status_deleted,
            links_deleted,
            url_cache_deleted,
            _count_url_cache(urls_for_cleanup),
        )

        # Визначаємо канали, які можна прибрати: якщо не залишилось admin_channel або network_channel
        keep_ids = set(
            db.execute(select(m.AdminChannel.channel_id)).scalars().all()
        ) | set(db.execute(select(m.NetworkChannel.channel_id)).scalars().all())
        delete_ids = [cid for cid in chan_ids if cid not in keep_ids]
        if delete_ids:
            channels_deleted = db.execute(delete(m.Channel).where(m.Channel.channel_id.in_(delete_ids))).rowcount or 0

    # invite_owners та links/url_cache/invite_status без channel_id для цього адміна (по display/username)
    if admin_obj:
        owner_disp = admin_obj.display
        owner_user = admin_obj.username
        conds = []
        params = {}
        if owner_disp:
            conds.append(m.Link.owner_display == owner_disp)
        if owner_user:
            conds.append(m.Link.owner_username == owner_user)
        if conds:
            # invite_owners: лише за власником (таблиця не має channel_id у схемі)
            where_raw = []
            params_raw = {}
            if owner_disp:
                where_raw.append("owner_display = :od")
                params_raw["od"] = owner_disp
            if owner_user:
                where_raw.append("owner_username = :ou")
                params_raw["ou"] = owner_user
            if where_raw:
                where_expr = " OR ".join(where_raw)
                invite_owners_deleted += db.execute(
                    text(f"DELETE FROM invite_owners WHERE {where_expr}"),
                    params_raw,
                ).rowcount or 0
                links_no_channel_deleted += db.execute(
                    text(f"DELETE FROM links WHERE channel_id IS NULL AND ({where_expr})"),
                    params_raw,
                ).rowcount or 0

            # Збираємо URL без channel_id для цього власника і чистимо url_cache (joined/already) + invite_status
            links_owner = db.execute(
                select(m.Link.raw_url).where(
                    m.Link.channel_id.is_(None),
                    or_(*conds),
                )
            ).all()
            owner_urls_raw = [r[0] for r in links_owner if r and r[0]]
            owner_urls = []
            for u in owner_urls_raw:
                owner_urls.extend(_expand_url_variants(u))
            urls_for_cleanup.extend(owner_urls)

            if owner_urls:
                try:
                    url_cache_deleted += _delete_url_cache_db(db, owner_urls, ["already", "joined"])
                except Exception as e:
                    log.exception("remove_admin_deep url_cache delete (owner) failed: %s", e)
                if _count_url_cache(owner_urls) > 0 and url_cache_deleted == 0:
                    try:
                        url_cache_deleted += _delete_url_cache_db(db, owner_urls, None)
                        log.debug("remove_admin_deep owner_cleanup fallback url_cache_deleted=%s", url_cache_deleted)
                    except Exception as e:
                        log.exception("remove_admin_deep url_cache delete fallback (owner) failed: %s", e)
                log.debug(
                    "remove_admin_deep owner_cleanup url_cache_deleted+=%s urls_count=%s sample=%s url_cache_post=%s",
                    url_cache_deleted,
                    len(owner_urls),
                    _sample(owner_urls),
                    _count_url_cache(owner_urls),
                )

                inv_hashes = []
                re_inv = re.compile(r"(?:t\\.me/(?:\\+|joinchat/))([A-Za-z0-9_-]{5,128})")
                for u in owner_urls:
                    m_inv = re_inv.search(u or "")
                    if m_inv:
                        inv_hashes.append(m_inv.group(1))
                if inv_hashes:
                    try:
                        invite_status_deleted += membership_db.invite_status_delete(inv_hashes, statuses=["already", "joined"])
                    except Exception:
                        pass
                    log.debug(
                        "remove_admin_deep owner_cleanup invite_status_deleted=%s hashes=%s",
                        invite_status_deleted,
                        _sample(inv_hashes),
                    )

    db.commit()
    return {
        "admin_deleted": adm_deleted,
        "admin_channels_deleted": ac_deleted,
        "network_channels_deleted": nc_deleted,
        "networks_deleted": len(net_ids),
        "membership_deleted": mem_deleted,
        "invite_map_deleted": invite_map_deleted,
        "invite_status_deleted": invite_status_deleted,
        "owner_conflicts_deleted": owner_conflicts_deleted,
        "links_deleted": links_deleted,
        "url_cache_deleted": url_cache_deleted,
        "channels_deleted": channels_deleted,
        "membership_status_deleted": membership_status_deleted,
        "invite_owners_deleted": invite_owners_deleted,
        "links_no_channel_deleted": links_no_channel_deleted,
    }


def attach_channel(db: Session, admin_id: int, channel_id: int) -> dict:
    """
    Прив'язує канал до адміна, але блокує, якщо канал уже закріплений за іншим адміном.
    Повертає dict:
      {"status": "added"|"exists"|"conflict", "admin_id": <int|None>}
    """
    # Перевіряємо, чи вже прив'язаний до когось
    existing_link = db.execute(
        select(m.AdminChannel).where(m.AdminChannel.channel_id == channel_id)
    ).scalars().first()
    if existing_link:
        if existing_link.admin_id == admin_id:
            return {"status": "exists", "admin_id": admin_id}
        else:
            return {"status": "conflict", "admin_id": existing_link.admin_id}

    link = m.AdminChannel(admin_id=admin_id, channel_id=channel_id)
    db.add(link)
    db.commit()
    return {"status": "added", "admin_id": admin_id}


def list_channels_for_admin(db: Session, admin_id: int) -> List[m.Channel]:
    admin = db.execute(select(m.Admin).where(m.Admin.id == admin_id)).scalar_one_or_none()
    if not admin:
        return []
    chan_ids = [ac.channel_id for ac in admin.channels]
    if not chan_ids:
        return []
    chans = db.execute(select(m.Channel).where(m.Channel.id.in_(chan_ids))).scalars().all()
    return list(chans)


def ensure_channel(db: Session, channel_id: int, username: Optional[str] = None, title: Optional[str] = None) -> m.Channel:
    ch = db.execute(select(m.Channel).where(m.Channel.channel_id == channel_id)).scalar_one_or_none()
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
