# app/services/joiner.py
import logging

from app.utils.throttle import throttle_probe, throttle_invite, throttle_public
from telethon.errors.rpcerrorlist import InviteRequestSentError

from telethon.errors import (
    InviteHashInvalidError, InviteHashExpiredError,
    UserAlreadyParticipantError, FloodWaitError,
    UsernameNotOccupiedError, ChannelPrivateError,
)
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

from app.services.membership_db import (
    map_invite_set, map_invite_get,
    invite_status_get, invite_status_put,
)
from app.services.account_pool import is_already_subscribed

log = logging.getLogger("services.joiner")


def _extract_invite_hash(url: str) -> str | None:
    """
    Надійно дістає invite-hash з:
      • https://t.me/+XXXXXXXX
      • https://t.me/joinchat/XXXXXXXX
      • або повертає None, якщо це не інвайт.
    Терпимо до зайвих пробілів/небачимих символів.
    """
    if not url:
        return None
    s = str(url)
    # прибираємо типові невидимі артефакти копіпаста
    s = s.replace("\u200b", "").replace("\u200e", "").replace("\u200f", "")
    s = s.strip()
    try:
        import re
        m = re.search(r"(?:t\.me/(?:\+|joinchat/))([A-Za-z0-9_-]{5,128})", s)
        if m:
            return m.group(1)
        return None
    except Exception:
        return None


def _plausible_invite_hash(h: str | None) -> bool:
    """
    Дуже легка локальна перевірка “схожості” на валідний інвайт-хеш, без API:
      - тільки A-Za-z0-9_- ,
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
      - kind: 'invite' | 'public'

    Для інвайтів: лише локальні/кеш перевірки (жодних мережевих CheckChatInviteRequest).
    """
    invite_hash = _extract_invite_hash(url)
    if invite_hash:
        log.debug(
            "probe_channel_id: invite detected (no-api) hash=%s url=%s",
            invite_hash, url
        )
        # 0) локальна форма
        if not _plausible_invite_hash(invite_hash):
            log.debug("probe_channel_id: invite hash looks invalid (local) %s", invite_hash)
            return None, None, "invite", invite_hash

        # 1) кеш відповідності: hash -> channel_id/title
        try:
            cid_cached, title_cached = map_invite_get(invite_hash)
            if cid_cached:
                return int(cid_cached), (title_cached or None), "invite", invite_hash
        except Exception:
            pass

        # 2) Більше *нічого* не робимо на probe (жодних API).
        return None, None, "invite", invite_hash

    # 3) public / username / прямий t.me/channel
    try:
        # Захист від хибнопозитивів: якщо це схоже на інвайт посилання, НЕ ліземо в get_entity
        s = (url or "").replace("\u200b", "").replace("\u200e", "").replace("\u200f", "").strip()
        if "t.me/+" in s or "joinchat/" in s:
            log.debug("probe_channel_id: forced invite-path (guard) url=%s", url)
            return None, None, "public", None

        if not s or " " in s:
            return None, None, "public", None

        await throttle_probe(url)
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
            # --- КРОК 0a: якщо інвайт уже знаємо і вже підписані — НЕ викликаємо ImportChatInviteRequest
            cid_cached, title_cached = (None, None)
            try:
                if invite_hash:
                    cid_cached, title_cached = map_invite_get(invite_hash)
            except Exception:
                pass

            if cid_cached:
                try:
                    who = await is_already_subscribed(url)
                except Exception:
                    who = None
                if who:
                    # ми вже учасник — нічого не імпортуємо
                    invite_status_put(invite_hash, "already")
                    return "already", (title_cached or None), "invite", int(cid_cached), invite_hash

            # --- КРОК 0b: перевірка кешу статусу по invite_hash (без API)
            st = invite_status_get(invite_hash)
            if st in ("invalid", "private", "requested", "already", "joined", "blocked", "too_many"):
                # Якщо є channel_id в карті — повернемо його; якщо ні — повернемо None
                cid_known, title_known = map_invite_get(invite_hash)
                return st, (title_known or None), "invite", (int(cid_known) if cid_known else None), invite_hash

            # --- КРОК 1: реальна спроба приєднатися
            log.debug("ensure_join: ImportChatInviteRequest for %s", url)
            await throttle_invite()
            try:
                updates = await client(ImportChatInviteRequest(invite_hash))
            except FloodWaitError as e:
                log.warning(
                    "FLOOD in ensure_join(ImportChatInviteRequest): url=%s seconds=%s",
                    url, e.seconds
                )
                raise

            # ДЕФЕНСИВНО: якщо апдейт без chats (join request flow) — вважаємо як 'requested'
            chats = getattr(updates, "chats", None)
            if not chats:
                try:
                    invite_status_put(invite_hash, "requested")
                except Exception:
                    pass
                return "requested", None, "invite", None, invite_hash

            ch = chats[0] if chats else None
            cid = int(ch.id) if ch else None
            title = getattr(ch, "title", "?") if ch else "?"

            if invite_hash and cid:
                try:
                    map_invite_set(invite_hash, cid, title or None)
                    invite_status_put(invite_hash, "joined")
                except Exception:
                    pass

            return "joined", title, "invite", cid, invite_hash

        # --- публічний канал/чат ---
        await throttle_public()
        ent = await client.get_entity(url)

        await throttle_public()
        try:
            await client(JoinChannelRequest(ent))
            # публічний сценарій — статуса інвайту немає
            return "joined", getattr(ent, "title", "?"), "public", int(getattr(ent, "id", 0) or 0), invite_hash
        except UserAlreadyParticipantError:
            return "already", getattr(ent, "title", None), "public", int(getattr(ent, "id", 0) or 0), invite_hash

    # ---- обробка винятків ----
    except InviteRequestSentError:
        if is_invite and invite_hash:
            invite_status_put(invite_hash, "requested")
        return "requested", None, "invite", None, invite_hash


    except UserAlreadyParticipantError:
        if is_invite and invite_hash:
            invite_status_put(invite_hash, "already")
        return "already", None, "invite" if is_invite else "public", None, invite_hash

    except (InviteHashInvalidError, InviteHashExpiredError, UsernameNotOccupiedError):
        if is_invite and invite_hash:
            invite_status_put(invite_hash, "invalid")
        return "invalid", None, "invite" if is_invite else "public", None, invite_hash

    except ChannelPrivateError:
        if is_invite and invite_hash:
            invite_status_put(invite_hash, "private")
        return "private", None, "invite" if is_invite else "public", None, invite_hash

    except FloodWaitError as e:
        # FLOOD — це тимчасово, у кеш як фінальний не пишемо
        return f"flood_wait_{e.seconds}", None, "invite" if is_invite else "public", None, invite_hash

    except Exception as e:
        msg = str(e) if e else "error"
        if "Too many channels" in msg or "CHANNELS_TOO_MUCH" in msg:
            if is_invite and invite_hash:
                invite_status_put(invite_hash, "too_many")
            return "too_many", None, "public", None, invite_hash
        if "USER_BANNED_IN_CHANNEL" in msg or "USER_KICKED" in msg:
            if is_invite and invite_hash:
                invite_status_put(invite_hash, "blocked")
            return "blocked", None, "public", None, invite_hash
        if "INVITE_REQUEST_SENT" in msg:
            if is_invite and invite_hash:
                invite_status_put(invite_hash, "requested")
            return "requested", None, "invite" if is_invite else "public", None, invite_hash
        # інші помилки не кешуємо як фінальні
        return "error", msg, "invite" if is_invite else "public", None, invite_hash