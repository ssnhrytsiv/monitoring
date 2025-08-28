import logging
from typing import Optional

from telethon.errors import (
    InviteHashInvalidError, InviteHashExpiredError,
    UserAlreadyParticipantError, FloodWaitError,
    UsernameNotOccupiedError, ChannelPrivateError,
)
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest

from app.services.membership_db import map_invite_set, map_invite_get, bad_invite_get, bad_invite_put
from app.utils.link_parser import is_invite, extract_invite_hash, is_valid_invite_hash, normalize_url

log = logging.getLogger("services.joiner")

# In-memory negative cache to avoid repeated API calls within the same session
_memory_negative_cache = {}  # invite_hash -> (status, timestamp)
_MEMORY_CACHE_TTL = 300  # 5 minutes


def _clean_memory_cache():
    """Clean expired entries from memory cache."""
    import time
    current_time = time.time()
    expired_keys = [
        k for k, (_, ts) in _memory_negative_cache.items() 
        if current_time - ts > _MEMORY_CACHE_TTL
    ]
    for k in expired_keys:
        _memory_negative_cache.pop(k, None)


def _get_memory_cached_status(invite_hash: str) -> Optional[str]:
    """Get status from in-memory negative cache."""
    import time
    if invite_hash in _memory_negative_cache:
        status, timestamp = _memory_negative_cache[invite_hash]
        if time.time() - timestamp <= _MEMORY_CACHE_TTL:
            return status
        else:
            _memory_negative_cache.pop(invite_hash, None)
    return None


def _set_memory_cached_status(invite_hash: str, status: str):
    """Set status in in-memory negative cache."""
    import time
    if status in ("invalid", "private", "requested"):
        _memory_negative_cache[invite_hash] = (status, time.time())
        # Clean cache periodically
        if len(_memory_negative_cache) > 100:
            _clean_memory_cache()


async def probe_channel_id(client, url: str):
    """
    Повертає (channel_id, title, kind, invite_hash)
    kind: 'invite' | 'public'
    
    For invite links, this is now purely lightweight:
    - Local validation + cache lookups only
    - No CheckChatInviteRequest to reduce API calls
    """
    normalized_url = normalize_url(url)
    
    if is_invite(normalized_url):
        invite_hash = extract_invite_hash(normalized_url)
        
        # Local format validation first
        if not is_valid_invite_hash(invite_hash):
            return None, None, "invite", invite_hash
        
        # Check existing mapping
        mapped = map_invite_get(invite_hash)
        if mapped:
            return mapped, None, "invite", invite_hash
        
        # For invite links, return what we know without API calls
        return None, None, "invite", invite_hash
    else:
        # For public channels, we still need to resolve the entity
        try:
            ent = await client.get_entity(normalized_url)
            return int(getattr(ent, "id", 0) or 0), getattr(ent, "title", None), "public", None
        except UsernameNotOccupiedError:
            # Handle invalid public usernames
            return None, None, "public", None
        except Exception:
            return None, None, "public", None


async def ensure_join(client, url: str):
    """
    Реальна спроба приєднання з layered checks для зменшення API викликів.
    Повертає (status, title, kind, channel_id|None, invite_hash|None)
    
    Layered approach:
    1. Local format validation
    2. Persistent bad cache
    3. In-memory negative cache
    4. Optional CheckChatInviteRequest (if needed)
    5. ImportChatInviteRequest/JoinChannelRequest
    """
    normalized_url = normalize_url(url)
    is_invite_link = is_invite(normalized_url)
    
    try:
        if is_invite_link:
            invite_hash = extract_invite_hash(normalized_url)
            
            # Layer 1: Local format validation
            if not is_valid_invite_hash(invite_hash):
                log.debug("Invalid invite hash format: %s", invite_hash)
                return "invalid", None, "invite", None, invite_hash
            
            # Layer 2: Persistent bad cache
            cached_bad_status = bad_invite_get(invite_hash)
            if cached_bad_status:
                log.debug("Found cached bad status: %s for %s", cached_bad_status, invite_hash)
                return cached_bad_status, None, "invite", None, invite_hash
            
            # Layer 3: In-memory negative cache
            memory_status = _get_memory_cached_status(invite_hash)
            if memory_status:
                log.debug("Found memory cached status: %s for %s", memory_status, invite_hash)
                return memory_status, None, "invite", None, invite_hash
            
            # Layer 4 & 5: Try ImportChatInviteRequest directly
            # (Skip CheckChatInviteRequest to reduce API calls)
            try:
                updates = await client(ImportChatInviteRequest(invite_hash))
                ch = updates.chats[0] if getattr(updates, "chats", None) else None
                cid = int(ch.id) if ch else None
                title = getattr(ch, "title", "?") if ch else "?"
                if invite_hash and cid:
                    map_invite_set(invite_hash, cid)
                return "joined", title, "invite", cid, invite_hash
                
            except UserAlreadyParticipantError:
                # If already participant, we need to find the channel ID
                # Try CheckChatInviteRequest to get channel info
                try:
                    info = await client(CheckChatInviteRequest(invite_hash))
                    chat = getattr(info, "chat", None)
                    if chat is not None:
                        cid = int(chat.id)
                        title = getattr(chat, "title", None)
                        if invite_hash and cid:
                            map_invite_set(invite_hash, cid)
                        return "already", title, "invite", cid, invite_hash
                    return "already", getattr(info, "title", None), "invite", None, invite_hash
                except Exception:
                    return "already", None, "invite", None, invite_hash
                    
            except (InviteHashInvalidError, InviteHashExpiredError):
                # Cache negative result
                bad_invite_put(invite_hash, "invalid")
                _set_memory_cached_status(invite_hash, "invalid")
                return "invalid", None, "invite", None, invite_hash
                
            except ChannelPrivateError:
                # Cache negative result
                bad_invite_put(invite_hash, "private")
                _set_memory_cached_status(invite_hash, "private")
                return "private", None, "invite", None, invite_hash

        else:
            # Public channel logic
            try:
                ent = await client.get_entity(normalized_url)
                try:
                    await client(JoinChannelRequest(ent))
                    return "joined", getattr(ent, "title", "?"), "public", int(getattr(ent, "id", 0) or 0), None
                except UserAlreadyParticipantError:
                    return "already", getattr(ent, "title", None), "public", int(getattr(ent, "id", 0) or 0), None
                    
            except UsernameNotOccupiedError:
                return "invalid", None, "public", None, None

    except UserAlreadyParticipantError:
        return "already", None, "invite" if is_invite_link else "public", None, None
    except FloodWaitError as e:
        return f"flood_wait_{e.seconds}", None, "invite" if is_invite_link else "public", None, None
    except Exception as e:
        msg = str(e) if e else "error"
        
        # Check for specific error patterns
        if "Too many channels" in msg or "CHANNELS_TOO_MUCH" in msg:
            return "too_many", None, "public", None, None
        if "USER_BANNED_IN_CHANNEL" in msg or "USER_KICKED" in msg:
            return "blocked", None, "public", None, None
        if "INVITE_REQUEST_SENT" in msg:
            # Cache as requested for invites
            if is_invite_link:
                invite_hash = extract_invite_hash(normalized_url)
                if invite_hash:
                    bad_invite_put(invite_hash, "requested")
                    _set_memory_cached_status(invite_hash, "requested")
                    return "requested", None, "invite", None, invite_hash
            return "requested", None, "invite" if is_invite_link else "public", None, None
            
        return "error", msg, "invite" if is_invite_link else "public", None, None