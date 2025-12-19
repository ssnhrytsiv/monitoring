# app/services/joiner.py
import logging

from app.utils.throttle import throttle_probe, throttle_invite, throttle_public
from telethon.errors.rpcerrorlist import InviteRequestSentError

from telethon.errors import (
    InviteHashInvalidError, InviteHashExpiredError,
    UserAlreadyParticipantError, FloodWaitError,
    UsernameNotOccupiedError, ChannelPrivateError,
    ChannelsTooMuchError,
)
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest,CheckChatInviteRequest

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
                    log.debug("ensure_join(invite): already member via %s; invite=%s, cid=%s",
                              who, invite_hash, cid_cached)
                    invite_status_put(invite_hash, "already")
                    return "already", (title_cached or None), "invite", int(cid_cached), invite_hash

            # --- КРОК 0b: перевірка кешу статусу по invite_hash (без API)
            st = invite_status_get(invite_hash)
            # Кешований too_many прив'язаний до інвайта, але це ліміт акаунта, тож його ігноруємо.
            if st == "too_many":
                pass
            elif st in ("invalid", "private", "requested", "already", "joined", "blocked"):
                cid_known, title_known = map_invite_get(invite_hash)
                log.debug("ensure_join(invite): cached status=%s invite=%s cid=%s", st, invite_hash, cid_known)

                # Якщо в кеші "requested", спробуємо перепитати CheckChatInvite на випадок,
                # коли канал вже прийняв, щоб прибрати "заявку".
                if st == "requested":
                    try:
                        await throttle_invite()
                        inv = await client(CheckChatInviteRequest(invite_hash))
                        chat = getattr(inv, "chat", None)
                        cid_new = int(getattr(chat, "id", 0) or 0) if chat else None
                        title_new = getattr(chat, "title", None)
                        if cid_new:
                            try:
                                map_invite_set(invite_hash, cid_new, title_new or None)
                                invite_status_put(invite_hash, "already")
                            except Exception:
                                pass
                            log.info("ensure_join(invite): requested->already via recheck invite=%s cid=%s", invite_hash, cid_new)
                            return "already", (title_new or title_known or None), "invite", cid_new, invite_hash
                    except InviteRequestSentError:
                        # все ще заявка, залишаємо requested
                        pass
                    except FloodWaitError as e:
                        log.warning("ensure_join(invite): recheck FloodWait %ss", e.seconds)
                    except Exception as e:
                        log.debug("ensure_join(invite): recheck failed invite=%s: %s", invite_hash, e)

                return st, (title_known or None), "invite", (int(cid_known) if cid_known else None), invite_hash

            # --- КРОК 1: реальна спроба приєднатися
            log.debug("ensure_join(invite): ImportChatInviteRequest invite=%s", invite_hash)
            await throttle_invite()
            try:
                updates = await client(ImportChatInviteRequest(invite_hash))
            except FloodWaitError as e:
                log.warning("FLOOD ensure_join(ImportChatInviteRequest): invite=%s seconds=%s", invite_hash, e.seconds)
                raise

            chats = getattr(updates, "chats", None)
            if not chats:
                # join request flow → нас ще не прийняли
                try:
                    invite_status_put(invite_hash, "requested")
                except Exception:
                    pass
                log.info("ensure_join(invite): sent join request invite=%s -> requested", invite_hash)
                return "requested", None, "invite", None, invite_hash

            ch = chats[0]
            cid = int(getattr(ch, "id", 0) or 0) or None
            title = getattr(ch, "title", "?") if ch else "?"

            if invite_hash and cid:
                try:
                    map_invite_set(invite_hash, cid, title or None)
                    invite_status_put(invite_hash, "joined")
                except Exception:
                    pass
            log.info("ensure_join(invite): joined invite=%s cid=%s title=%r", invite_hash, cid, title)
            return "joined", title, "invite", cid, invite_hash

        # --- публічний канал/чат ---
        await throttle_public()
        ent = await client.get_entity(url)

        await throttle_public()
        try:
            await client(JoinChannelRequest(ent))
            title = getattr(ent, "title", "?")
            cid = int(getattr(ent, "id", 0) or 0) or None
            log.info("ensure_join(public): joined url=%s cid=%s title=%r", url, cid, title)
            return "joined", title, "public", cid, invite_hash
        except UserAlreadyParticipantError:
            title = getattr(ent, "title", None)
            cid = int(getattr(ent, "id", 0) or 0) or None
            log.debug("ensure_join(public): already url=%s cid=%s title=%r", url, cid, title)
            return "already", title, "public", cid, invite_hash

    # ---- обробка винятків ----
    except InviteRequestSentError:
        if is_invite and invite_hash:
            invite_status_put(invite_hash, "requested")
        log.info("ensure_join(invite): InviteRequestSentError invite=%s -> requested", invite_hash)
        return "requested", None, "invite", None, invite_hash




    except UserAlreadyParticipantError:

        kind = "invite" if is_invite else "public"

        log.debug("ensure_join(%s): UserAlreadyParticipantError -> already", kind)

        if is_invite and invite_hash:

            # 1) Позначаємо статус

            try:

                invite_status_put(invite_hash, "already")


            except Exception:

                pass

            # 2) Прагнемо отримати channel_id без join – одним легким викликом

            try:

                from telethon.tl.functions.messages import CheckChatInviteRequest

                await throttle_invite()  # поважаємо троттл

                inv = await client(CheckChatInviteRequest(invite_hash))

                chat = getattr(inv, "chat", None)

                cid = int(getattr(chat, "id", 0) or 0) if chat else None

                title = getattr(chat, "title", None)

                if cid:

                    try:

                        # збережемо мапу invite -> (channel_id, title)

                        map_invite_set(invite_hash, cid, title or None)


                    except Exception:

                        pass

                return "already", title, "invite", cid, invite_hash


            except Exception:

                # якщо з якоїсь причини не вийшло — повертаємось без cid

                return "already", None, "invite", None, invite_hash

        # публічні чати/канали: як і було

        return "already", None, kind, None, invite_hash

    except (InviteHashInvalidError, InviteHashExpiredError, UsernameNotOccupiedError):
        if is_invite and invite_hash:
            invite_status_put(invite_hash, "invalid")
        kind = "invite" if is_invite else "public"
        log.debug("ensure_join(%s): invalid/expired/not_occupied", kind)
        return "invalid", None, kind, None, invite_hash

    except ChannelPrivateError:
        if is_invite and invite_hash:
            invite_status_put(invite_hash, "private")
        kind = "invite" if is_invite else "public"
        log.debug("ensure_join(%s): ChannelPrivateError -> private", kind)
        return "private", None, kind, None, invite_hash

    except ChannelsTooMuchError:
        kind = "invite" if is_invite else "public"
        log.warning("ensure_join(%s): channels too much", kind)
        return "too_many", None, kind, None, invite_hash

    except FloodWaitError as e:
        kind = "invite" if is_invite else "public"
        log.warning("ensure_join(%s): FloodWaitError %ss", kind, e.seconds)
        return f"flood_wait_{e.seconds}", None, kind, None, invite_hash

    except Exception as e:
        msg = str(e) if e else "error"
        kind = "invite" if is_invite else "public"
        if "Too many channels" in msg or "CHANNELS_TOO_MUCH" in msg:
            log.warning("ensure_join(%s): too_many channels", kind)
            return "too_many", None, kind, None, invite_hash
        if "USER_BANNED_IN_CHANNEL" in msg or "USER_KICKED" in msg:
            if is_invite and invite_hash:
                invite_status_put(invite_hash, "blocked")
            log.warning("ensure_join(%s): blocked/banned", kind)
            return "blocked", None, kind, None, invite_hash
        if "INVITE_REQUEST_SENT" in msg:
            if is_invite and invite_hash:
                invite_status_put(invite_hash, "requested")
            log.info("ensure_join(%s): INVITE_REQUEST_SENT -> requested", kind)
            return "requested", None, kind, None, invite_hash
        log.exception("ensure_join(%s): unexpected error: %s", kind, msg)
        return "error", msg, kind, None, invite_hash
