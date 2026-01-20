from typing import Optional, List, Dict
import re
import logging

from app.DAL import channels_operations as channels_db
from app.DAL import session_scope

log = logging.getLogger("channels_repo")

_INV_RE = re.compile(r"(?:t\.me/(?:\+|joinchat/)|tg://join\?invite=)([A-Za-z0-9_-]{6,})")
_USER_RE = re.compile(r"(?:https?://)?t\.me/([A-Za-z0-9_]{3,})/?$", re.IGNORECASE)

def normalize_target_link(target: str) -> str:
    s = str(target or "").strip()
    if not s:
        return ""
    if re.fullmatch(r"\d{5,15}", s):
        return s
    if s.startswith("@"):
        u = s[1:].strip()
        return f"https://t.me/{u}" if u else s
    if s.startswith("t.me/"):
        return "https://" + s
    if s.startswith("http://") or s.startswith("https://") or s.startswith("tg://"):
        return s
    return s

def resolve_cid_by_target(target: str) -> Optional[int]:
    s0 = str(target or "").strip()
    if not s0:
        return None

    if re.fullmatch(r"\d{5,15}", s0):
        try:
            return int(s0)
        except Exception:
            return None

    s = normalize_target_link(s0)

    match_username = _USER_RE.search(s)
    if match_username:
        username = match_username.group(1)
        try:
            with session_scope() as db:
                cid = channels_db.get_channel_id_by_username(db, username)
            if cid:
                return cid
        except Exception as e:
            log.exception("resolve_cid username lookup failed: %s", e)

    match_invite = _INV_RE.search(s)
    if match_invite:
        invite_hash = match_invite.group(1)
        # invite_hash lookup handled via invite_cache in joiner/subscription paths
        log.debug("resolve_cid: invite hash %s detected, not resolved in repo", invite_hash)

    try:
        with session_scope() as db:
            cid = channels_db.get_channel_id_by_url_any(db, s)
            if cid:
                return cid
    except Exception as e:
        log.exception("resolve_cid link lookup failed: %s", e)

    return None

def get_links_by_channel_ids(cids: List[int]) -> Dict[int, str]:
    try:
        with session_scope() as db:
            return channels_db.get_links_by_channel_ids(db, cids)
    except Exception as e:
        log.exception("get_links_by_channel_ids failed: %s", e)
        return {}

def get_owners_by_channel_ids(cids: List[int]) -> List[channels_db.ChannelOwnerLabel]:
    try:
        with session_scope() as db:
            return channels_db.get_owners_by_channel_ids(db, cids)
    except Exception as e:
        log.exception("get_owners_by_channel_ids failed: %s", e)
        return []

def get_titles_by_channel_ids(cids: List[int]) -> Dict[int, str]:
    """
    Повертає map channel_id -> title (Telegram-назва каналу) з таблиці channels.
    """
    try:
        with session_scope() as db:
            return channels_db.get_titles_by_channel_ids(db, cids)
    except Exception as e:
        log.exception("get_titles_by_channel_ids failed: %s", e)
        return {}
