import logging

from telethon.errors import (
    InviteHashInvalidError, InviteHashExpiredError,
    UserAlreadyParticipantError, FloodWaitError,
    UsernameNotOccupiedError, ChannelPrivateError,
)
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

from app.services.membership_db import map_invite_set, map_invite_get

log = logging.getLogger("services.joiner")

def _extract_invite_hash(url: str) -> str | None:
    """
    Витягує інвайт-хеш із URL (формати t.me/+HASH або .../joinchat/HASH).
    Повертає None, якщо не схоже.
    """
    try:
        if not url:
            return None
        if ("/+" in url) or ("joinchat" in url):
            part = url.rstrip("/").split("")[-1]
            part = part.replace("+", "")
            return part or None
        return None
    except Exception:
        return None

def _plausible_invite_hash(h: str | None) -> bool:
    """
    Дуже легка локальна перевірка “схожості” на валідний інвайт-хеш, без API:
      - тільки A-Za-z0-9_-,
      - довжина 16..64.
    """
    if not h:
        return False
    if not (16 <= len(h) <= 64):
        return False
    for ch in h:
        if not (ch.isalnum() or ch in "_-"):
            return False
    return True

async def probe_channel_id(client, url: str):
    """
    Повертає (channel_id, title, kind, invite_hash)
    kind: 'invite' | 'public'

    Для інвайтів: лише локальні/кеш перевірки (жодних мережевих CheckChatInviteRequest).
    """
    invite_hash = _extract_invite_hash(url)
    if invite_hash:
        # 0) локальна форма
        if not _plausible_invite_hash(invite_hash):
            log.debug("probe_channel_id: invite hash looks invalid (local) %s", invite_hash)
            return None, None, "invite", invite_hash

        # 1) кеш відповідності
        try:
            cid_cached, title_cached = map_invite_get(invite_hash)
            if cid_cached:
                return int(cid_cached), (title_cached or None), "invite", invite_hash
        except Exception:
            pass

        # 2) більше нічого (нема мережевих викликів)
        return None, None, "invite", invite_hash

    # public
    try:
        s = (url or "").strip()
        if not s or " " in s:
            return None, None, "public", None
        # TODO throttle_probe if/when introduced
        log.debug("probe_channel_id: get_entity for %s", url)
        ent = await client.get_entity(url)
        cid = int(getattr(ent, "id", 0) or 0)
        title = getattr(ent, "title", None)
        return cid if cid else None, title, "public", None
    except FloodWaitError as e:
        log.warning("FLOOD in probe_channel_id(get_entity): url=%s seconds=%s", url, e.seconds)
        raise
    except UsernameNotOccupiedError:
        return None, None, "public", None
    except ChannelPrivateError:
        return None, None, "public", None
    except Exception:
        return None, None, "public", None

async def ensure_join(client, url: str):
    """
    Реальна спроба приєднання.
    Повертає (status, title_or_msg, kind, channel_id|None, invite_hash|None)

    status: joined / already / invalid / private / flood_wait_<sec> / too_many /
            blocked / requested / error
    """
    invite_hash = _extract_invite_hash(url)
    is_invite = bool(invite_hash)

    try:
        if is_invite:
            try:
                log.debug("ensure_join: ImportChatInviteRequest for %s", url)
                updates = await client(ImportChatInviteRequest(invite_hash))
            except FloodWaitError as e:
                log.warning("FLOOD in ensure_join(ImportChatInviteRequest): url=%s seconds=%s", url, e.seconds)
                raise
            ch = updates.chats[0] if getattr(updates, "chats", None) else None
            cid = int(ch.id) if ch else None
            title = getattr(ch, "title", "?") if ch else "?"
            if invite_hash and cid:
                try:
                    map_invite_set(invite_hash, cid)
                except Exception:
                    pass
            return "joined", title, "invite", cid, invite_hash

        ent = await client.get_entity(url)
        try:
            await client(JoinChannelRequest(ent))
            return "joined", getattr(ent, "title", "?"), "public", int(getattr(ent, "id", 0) or 0), invite_hash
        except UserAlreadyParticipantError:
            return "already", getattr(ent, "title", None), "public", int(getattr(ent, "id", 0) or 0), invite_hash

    except UserAlreadyParticipantError:
        return "already", None, "invite" if is_invite else "public", None, invite_hash
    except (InviteHashInvalidError, InviteHashExpiredError, UsernameNotOccupiedError):
        return "invalid", None, "invite" if is_invite else "public", None, invite_hash
    except ChannelPrivateError:
        return "private", None, "invite" if is_invite else "public", None, invite_hash
    except FloodWaitError as e:
        return f"flood_wait_{e.seconds}", None, "invite" if is_invite else "public", None, invite_hash
    except Exception as e:
        msg = str(e) if e else "error"
        if "Too many channels" in msg or "CHANNELS_TOO_MUCH" in msg:
            return "too_many", None, "public", None, invite_hash
        if "USER_BANNED_IN_CHANNEL" in msg or "USER_KICKED" in msg:
            return "blocked", None, "public", None, invite_hash
        if "INVITE_REQUEST_SENT" in msg:
            return "requested", None, "invite" if is_invite else "public", None, invite_hash
        return "error", msg, "invite" if is_invite else "public", None, invite_hash
