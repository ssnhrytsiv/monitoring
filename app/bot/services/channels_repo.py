from typing import Optional, List, Dict
import re
import logging

from app.services.posts_watch_result_db import raw_connection

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

    m = _USER_RE.search(s)
    if m:
        username = m.group(1)
        try:
            conn = raw_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT channel_id FROM channels WHERE lower(username)=lower(?) LIMIT 1",
                (username,),
            )
            r = cur.fetchone()
            if r and r[0] is not None:
                return int(r[0])
        except Exception as e:
            log.exception(f"resolve_cid username lookup failed: {e}")

    im = _INV_RE.search(s)
    if im:
        ih = im.group(1)
        try:
            conn = raw_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT channel_id FROM invite_map WHERE invite_hash=? LIMIT 1",
                (ih,),
            )
            r = cur.fetchone()
            if r and r[0] is not None:
                return int(r[0])
        except Exception as e:
            log.exception(f"resolve_cid invite_map lookup failed: {e}")

    try:
        conn = raw_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT channel_id FROM channel_links WHERE link_url_norm=? LIMIT 1",
            (s,),
        )
        r = cur.fetchone()
        if r and r[0] is not None:
            return int(r[0])
    except Exception as e:
        log.exception(f"resolve_cid channel_links lookup failed: {e}")

    return None

def get_links_by_channel_ids(cids: List[int]) -> Dict[int, str]:
    ids = [int(x) for x in cids or [] if x]
    if not ids:
        return {}

    mp: Dict[int, str] = {}
    try:
        conn = raw_connection()
        cur = conn.cursor()
        qmarks = ",".join("?" for _ in ids)

        cur.execute(
            f"""
            SELECT channel_id, username
            FROM channels
            WHERE channel_id IN ({qmarks})
            """,
            ids,
        )
        for cid, username in cur.fetchall():
            cid_i = int(cid)
            if username:
                mp[cid_i] = f"https://t.me/{str(username).lstrip('@')}"

        cur.execute(
            f"""
            SELECT channel_id, invite_hash
            FROM invite_map
            WHERE channel_id IN ({qmarks})
            """,
            ids,
        )
        for cid, invite_hash in cur.fetchall():
            cid_i = int(cid)
            if cid_i not in mp and invite_hash:
                mp[cid_i] = f"https://t.me/+{invite_hash}"

        cur.execute(
            f"""
            SELECT channel_id, link_url_norm
            FROM channel_links
            WHERE channel_id IN ({qmarks})
            """,
            ids,
        )
        for cid, link_url_norm in cur.fetchall():
            cid_i = int(cid)
            if cid_i not in mp and link_url_norm:
                mp[cid_i] = str(link_url_norm)

    except Exception as e:
        log.exception(f"get_links_by_channel_ids failed: {e}")

    return {cid: link for cid, link in mp.items() if link}

def get_owners_by_channel_ids(cids: List[int]) -> Dict[int, str]:
    ids = [int(x) for x in cids or [] if x]
    if not ids:
        return {}

    mp: Dict[int, str] = {}
    try:
        conn = raw_connection()
        cur = conn.cursor()
        qmarks = ",".join("?" for _ in ids)
        cur.execute(
            f"""
            SELECT channel_id, owner_display
            FROM channels
            WHERE channel_id IN ({qmarks})
            """,
            ids,
        )
        for cid, owner in cur.fetchall():
            if cid is None:
                continue
            cid_i = int(cid)
            o = str(owner).strip() if owner is not None else ""
            if o:
                mp[cid_i] = o
    except Exception as e:
        log.exception(f"get_owners_by_channel_ids failed: {e}")

    return mp