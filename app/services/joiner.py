import logging

from telethon.errors import (
    InviteHashInvalidError, InviteHashExpiredError,
    UserAlreadyParticipantError, FloodWaitError,
    UsernameNotOccupiedError, ChannelPrivateError,
)
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest

from app.services.membership_db import map_invite_set, map_invite_get

log = logging.getLogger("services.joiner")


async def probe_channel_id(client, url: str):
    """
    Повертає (channel_id, title, kind, invite_hash)
    kind: 'invite' | 'public'
    """
    is_invite = ("/+" in url) or ("joinchat" in url)
    if is_invite:
        inv = url.split("/")[-1].replace("+", "")
        mapped = map_invite_get(inv)
        if mapped:
            return mapped, None, "invite", inv
        try:
            info = await client(CheckChatInviteRequest(inv))
            chat = getattr(info, "chat", None)
            if chat is not None:
                return int(chat.id), getattr(chat, "title", None), "invite", inv
            return None, getattr(info, "title", None), "invite", inv
        except Exception:
            return None, None, "invite", inv
    else:
        try:
            ent = await client.get_entity(url)
            return int(getattr(ent, "id", 0) or 0), getattr(ent, "title", None), "public", None
        except Exception:
            return None, None, "public", None


async def ensure_join(client, url: str):
    """
    Реальна спроба приєднання.
    Повертає (status, title, kind, channel_id|None, invite_hash|None)
    """
    is_invite = ("/+" in url) or ("joinchat" in url)
    try:
        if is_invite:
            inv = url.split("/")[-1].replace("+", "")
            updates = await client(ImportChatInviteRequest(inv))
            ch = updates.chats[0] if getattr(updates, "chats", None) else None
            cid = int(ch.id) if ch else None
            title = getattr(ch, "title", "?") if ch else "?"
            if inv and cid:
                map_invite_set(inv, cid)
            return "joined", title, "invite", cid, inv

        ent = await client.get_entity(url)
        try:
            await client(JoinChannelRequest(ent))
            return "joined", getattr(ent, "title", "?"), "public", int(getattr(ent, "id", 0) or 0), None
        except UserAlreadyParticipantError:
            return "already", getattr(ent, "title", None), "public", int(getattr(ent, "id", 0) or 0), None

    except UserAlreadyParticipantError:
        return "already", None, "invite" if is_invite else "public", None, None
    except (InviteHashInvalidError, InviteHashExpiredError):
        return "invalid", None, "invite", None, url.split("/")[-1].replace("+", "")
    except ChannelPrivateError:
        return "private", None, "invite" if is_invite else "public", None, None
    except FloodWaitError as e:
        return f"flood_wait_{e.seconds}", None, "invite" if is_invite else "public", None, None
    except Exception as e:
        msg = str(e) if e else "error"
        if "Too many channels" in msg or "CHANNELS_TOO_MUCH" in msg:
            return "too_many", None, "public", None, None
        if "USER_BANNED_IN_CHANNEL" in msg or "USER_KICKED" in msg:
            return "blocked", None, "public", None, None
        if "INVITE_REQUEST_SENT" in msg:
            return "requested", None, "invite" if is_invite else "public", None, None
        return "error", msg, "invite" if is_invite else "public", None, None