from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.utils.link_parser import sanitize_link


@dataclass(frozen=True)
class BatchResultDTO:
    original_url: str
    clean_url: str
    channel_id: Optional[int]
    title: Optional[str]
    status_raw: Optional[str]
    session_hint: Optional[str]


@dataclass(frozen=True)
class RefreshPlanDTO:
    keep_cids: Set[int] = field(default_factory=set)
    to_remove: Set[int] = field(default_factory=set)
    to_remove_order: List[int] = field(default_factory=list)
    items: List[BatchResultDTO] = field(default_factory=list)


def _collect_norm_keys(url: str) -> List[str]:
    keys: List[str] = []
    base = url or ""
    if base:
        keys.append(base)
    try:
        clean = sanitize_link(base) or base
    except Exception:
        clean = base
    if clean and clean not in keys:
        keys.append(clean)
    return keys


def build_batch_results(urls: List[str], cached_items: List[Dict]) -> List[BatchResultDTO]:
    """
    Формує BatchResultDTO на основі batch_cache items та списку URL без додаткових DB-викликів.
    """
    cache_map: Dict[str, Dict] = {}
    keep_from_cache: Set[int] = set()
    for it in cached_items or []:
        norm_keys = _collect_norm_keys(it.get("url", ""))
        for nk in norm_keys:
            cache_map[nk] = it
        cid = it.get("channel_id")
        if cid:
            keep_from_cache.add(int(cid))

    results: List[BatchResultDTO] = []
    for url in urls:
        try:
            clean = sanitize_link(url) or url
        except Exception:
            clean = url
        cached = cache_map.get(clean) or cache_map.get(url)
        cid = cached.get("channel_id") if cached else None
        title = cached.get("title") if cached else None
        status_raw = cached.get("status") if cached else None
        results.append(
            BatchResultDTO(
                original_url=url,
                clean_url=clean or url,
                channel_id=cid if cid is not None else None,
                title=title,
                status_raw=status_raw,
                session_hint=None,
            )
        )
    return results


def build_refresh_plan(current_cids: Set[int], batch_results: List[BatchResultDTO]) -> RefreshPlanDTO:
    """
    Формує базовий план оновлення: визначає keep_cids/to_remove на основі batch_results.
    """
    keep: Set[int] = set()
    ordered_cids: List[int] = []
    for item in batch_results:
        if item.channel_id is not None:
            cid_i = int(item.channel_id)
            keep.add(cid_i)
            ordered_cids.append(cid_i)

    to_remove: Set[int] = set()
    if current_cids:
        to_remove = {int(cid) for cid in current_cids if int(cid) not in keep}

    to_remove_order: List[int] = []
    if to_remove:
        seen: Set[int] = set()
        for cid in ordered_cids:
            if cid in to_remove and cid not in seen:
                to_remove_order.append(cid)
                seen.add(cid)
        for cid in to_remove:
            if cid not in seen:
                to_remove_order.append(cid)

    return RefreshPlanDTO(
        keep_cids=keep,
        to_remove=to_remove,
        to_remove_order=to_remove_order,
        items=list(batch_results),
    )


def bulk_channel_title_owner(db: Session, channel_ids: List[int]) -> Dict[int, Optional[str]]:
    ids = [int(cid) for cid in channel_ids or [] if cid is not None]
    if not ids:
        return {}
    rows = db.execute(
        select(m.Channel.channel_id, m.Channel.title).where(m.Channel.channel_id.in_(ids))
    ).all()
    return {int(cid): title for cid, title in rows if cid is not None}


def bulk_admin_for_channels(db: Session, channel_ids: List[int]) -> Dict[int, Optional[int]]:
    ids = [int(cid) for cid in channel_ids or [] if cid is not None]
    if not ids:
        return {}
    rows = db.execute(
        select(m.Channel.channel_id, m.Channel.owner_admin_id).where(m.Channel.channel_id.in_(ids))
    ).all()
    return {int(cid): admin_id for cid, admin_id in rows if cid is not None and admin_id is not None}


def bulk_owner_conflict(db: Session, channel_ids: List[int]) -> Dict[int, str]:
    ids = [int(cid) for cid in channel_ids or [] if cid is not None]
    if not ids:
        return {}
    rows = db.execute(
        select(m.OwnerConflict.channel_id, m.OwnerConflict.reason).where(m.OwnerConflict.channel_id.in_(ids))
    ).all()
    return {int(cid): reason for cid, reason in rows if cid is not None and reason}


def bulk_memberships_accounts(db: Session, channel_ids: List[int]) -> Dict[int, Set[str]]:
    ids = [int(cid) for cid in channel_ids or [] if cid is not None]
    if not ids:
        return {}
    rows = db.execute(
        select(m.Membership.channel_id, m.Membership.account)
        .where(m.Membership.channel_id.in_(ids), m.Membership.account != "")
    ).all()
    result: Dict[int, Set[str]] = {}
    for cid, acc in rows:
        if cid is None or acc is None:
            continue
        result.setdefault(int(cid), set()).add(str(acc))
    return result


def bulk_any_session(db: Session, channel_ids: List[int]) -> Dict[int, str]:
    ids = [int(cid) for cid in channel_ids or [] if cid is not None]
    if not ids:
        return {}
    rows = db.execute(
        select(m.Membership.channel_id, m.Membership.account)
        .where(m.Membership.channel_id.in_(ids), m.Membership.account != "")
    ).all()
    result: Dict[int, str] = {}
    for cid, acc in rows:
        if cid is None or acc is None:
            continue
        cid_i = int(cid)
        if cid_i not in result:
            result[cid_i] = str(acc)
    return result


def bulk_channel_link_meta(db: Session, channel_ids: List[int]) -> Dict[int, tuple[Optional[str], Optional[str]]]:
    ids = [int(cid) for cid in channel_ids or [] if cid is not None]
    if not ids:
        return {}
    channels = db.execute(
        select(m.Channel.channel_id, m.Channel.username, m.Channel.title).where(m.Channel.channel_id.in_(ids))
    ).all()
    meta: Dict[int, Dict[str, Optional[str]]] = {
        int(cid): {"username": username, "title": title, "url_norm": None} for cid, username, title in channels if cid
    }
    link_rows = db.execute(
        select(m.Link.channel_id, m.Link.url_norm)
        .where(m.Link.channel_id.in_(ids))
        .order_by(m.Link.id.desc())
    ).all()
    for cid, url_norm in link_rows:
        if cid is None:
            continue
        cid_i = int(cid)
        if cid_i not in meta:
            meta[cid_i] = {"username": None, "title": None, "url_norm": None}
        if meta[cid_i]["url_norm"] is None and url_norm:
            meta[cid_i]["url_norm"] = url_norm

    result: Dict[int, tuple[Optional[str], Optional[str]]] = {}
    for cid, data in meta.items():
        href = None
        username = data.get("username")
        if username:
            href = f"https://t.me/{str(username).lstrip('@')}"
        elif data.get("url_norm"):
            href = data.get("url_norm")
        result[cid] = (data.get("title"), href)
    return result
