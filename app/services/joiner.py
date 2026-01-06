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
    any_final_for_channel,
    url_put,
    FINAL_GLOBAL,
    bump_requested_attempt,
)
from app.utils.tg_links import sanitize_link
from app.services import channel_db
from app.services.account_pool import is_already_subscribed

log = logging.getLogger("services.joiner")


def _log_exc(context: str) -> None:
    """Debug-log suppressed exceptions to trace why invite_map may not update."""
    log.debug("%s: suppressed exception", context, exc_info=True)


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
        _log_exc("_extract_invite_hash")
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
            _log_exc("probe_channel_id: map_invite_get")

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
        _log_exc("probe_channel_id: get_entity")
        return None, None, "public", None


async def ensure_join(client, url: str):
    """
    Реальна спроба приєднання.
    Повертає (status, title_or_msg, kind, channel_id|None, invite_hash|None)

    status: joined / already / invalid / private / flood_wait_<sec> / too_many /
            blocked / requested / error
    """
    cleaned_url = None
    try:
        cleaned_url = sanitize_link(url) or url
    except Exception:
        _log_exc("ensure_join: sanitize_link")
        cleaned_url = url

    def _final_from_cache(st: str | None) -> str | None:
        if not st:
            return st
        if st == "joined":
            return "already"
        return st

    invite_hash = _extract_invite_hash(url)
    is_invite = bool(invite_hash)
    requested_limit = 2

    def _requested_status() -> str:
        """
        Інкрементує лічильник requested для інвайта і повертає
        requested або requested_fast (якщо >3 за добу).
        """
        if not invite_hash:
            return "requested"
        try:
            cnt = bump_requested_attempt(invite_hash)
            if cnt > requested_limit:
                try:
                    invite_status_put(invite_hash, "requested_fast")
                except Exception:
                    _log_exc("ensure_join: invite_status_put(requested_fast)")
                return "requested_fast"
        except Exception:
            _log_exc("ensure_join: bump_requested_attempt")
        try:
            invite_status_put(invite_hash, "requested")
        except Exception:
            _log_exc("ensure_join: invite_status_put(requested)")
        return "requested"

    # --- Спроба знайти канал за raw_url у channel_db (якщо вже лінкували) ---
    if cleaned_url:
        try:
            link_row = channel_db.find_channel_by_link(cleaned_url)
            if link_row:
                cid_link, title_link = link_row
                final = any_final_for_channel(cid_link)
                final_norm = _final_from_cache(final)
                if final_norm in FINAL_GLOBAL:
                    if invite_hash:
                        log.debug(
                            "ensure_join(link_cache): final=%s cid=%s invite=%s -> invite_map not updated",
                            final_norm,
                            cid_link,
                            invite_hash,
                        )
                    log.debug(
                        "ensure_join(link_cache): final=%s cid=%s url=%s (no network)",
                        final_norm,
                        cid_link,
                        cleaned_url,
                    )
                    return final_norm, (title_link or None), "link_cache", cid_link, invite_hash
        except Exception:
            _log_exc("ensure_join: find_channel_by_link")

    try:
        if is_invite:
            # --- КРОК 0a: якщо інвайт уже знаємо і вже підписані — НЕ викликаємо ImportChatInviteRequest
            cid_cached, title_cached = (None, None)
            try:
                if invite_hash:
                    cid_cached, title_cached = map_invite_get(invite_hash)
            except Exception:
                _log_exc("ensure_join: map_invite_get")

            if cid_cached:
                try:
                    who = await is_already_subscribed(url)
                except Exception:
                    _log_exc("ensure_join: is_already_subscribed")
                    who = None
                if who:
                    log.debug(
                        "ensure_join(invite_cache): already via %s; invite=%s cid=%s (no network)",
                        who,
                        invite_hash,
                        cid_cached,
                    )
                    log.debug(
                        "ensure_join(invite_cache): invite_map not updated because already subscribed via %s",
                        who,
                    )
                    return "already", (title_cached or None), "invite", int(cid_cached), invite_hash

                # 🟢 Глобальна перевірка: якщо в membership_db вже є фінальний статус по цьому каналу,
                # не робимо мережеву спробу, одразу повертаємо його.
                try:
                    final = _final_from_cache(any_final_for_channel(int(cid_cached)))
                    if final:
                        # кешуємо лише негативні/нейтральні стани, "already/joined" залишаємо для membership
                        if final not in ("joined", "already"):
                            invite_status_put(invite_hash, final)
                        log.debug(
                            "ensure_join(invite_cache): final=%s invite=%s cid=%s -> invite_map not updated",
                            final,
                            invite_hash,
                            cid_cached,
                        )
                        log.debug(
                            "ensure_join(invite_cache): final=%s invite=%s cid=%s (no network)",
                            final,
                            invite_hash,
                            cid_cached,
                        )
                        return final, (title_cached or None), "invite", int(cid_cached), invite_hash
                except Exception:
                    _log_exc("ensure_join: any_final_for_channel/map_invite_set")

            # --- КРОК 0b: перевірка кешу статусу по invite_hash (без API)
            st = invite_status_get(invite_hash)
            log.debug("ensure_join(invite): invite_status_get=%s invite=%s", st, invite_hash)
            # Кешований too_many прив'язаний до інвайта, але це ліміт акаунта, тож його ігноруємо.
            if st == "too_many":
                pass
            elif st in ("invalid", "private", "requested", "requested_fast", "blocked"):
                cid_known, title_known = map_invite_get(invite_hash)
                st_norm = _final_from_cache(st)
                if st == "requested":
                    st_norm = _requested_status()
                log.debug("ensure_join(invite): cached status=%s(invite=%s cid=%s) -> %s", st, invite_hash, cid_known, st_norm)

                # Якщо досягли ліміту спроб — повертаємо fast-path без додаткових запитів
                if st_norm == "requested_fast":
                    return st_norm, (title_known or None), "invite", (int(cid_known) if cid_known else None), invite_hash

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
                                log.debug(
                                    "ensure_join(invite_cache): map_invite_set invite=%s cid=%s title=%r (requested->already)",
                                    invite_hash,
                                    cid_new,
                                    title_new,
                                )
                            except Exception:
                                _log_exc("ensure_join: map_invite_set requested->already")
                            log.info("ensure_join(invite): requested->already via recheck invite=%s cid=%s", invite_hash, cid_new)
                            return "already", (title_new or title_known or None), "invite", cid_new, invite_hash
                    except InviteRequestSentError:
                        # все ще заявка, залишаємо requested
                        pass
                    except FloodWaitError as e:
                        log.warning("ensure_join(invite): recheck FloodWait %ss", e.seconds)
                    except Exception as e:
                        msg = str(e)
                        if "expired and is not valid anymore" in msg:
                            try:
                                invite_status_put(invite_hash, "invalid")
                            except Exception:
                                _log_exc("ensure_join: invite_status_put(invalid) recheck")
                            log.info("ensure_join(invite): requested->invalid via recheck invite=%s", invite_hash)
                            return "invalid", (title_known or None), "invite", None, invite_hash
                        log.debug("ensure_join(invite): recheck failed invite=%s: %s", invite_hash, e)

                if invite_hash:
                    log.debug(
                        "ensure_join(invite_cache): cached status=%s invite=%s cid=%s -> invite_map not updated",
                        st_norm,
                        invite_hash,
                        cid_known,
                    )
                return st_norm, (title_known or None), "invite", (int(cid_known) if cid_known else None), invite_hash

            # --- КРОК 1: реальна спроба приєднатися
            log.debug("ensure_join(invite): ImportChatInviteRequest invite=%s (network)", invite_hash)
            if not invite_hash:
                log.debug("ensure_join(invite): empty invite_hash -> invalid url=%s", url)
                return "invalid", None, "invite", None, invite_hash
            await throttle_invite()
            try:
                updates = await client(ImportChatInviteRequest(invite_hash))
            except FloodWaitError as e:
                log.warning("FLOOD ensure_join(ImportChatInviteRequest): invite=%s seconds=%s", invite_hash, e.seconds)
                return f"flood_wait_{int(e.seconds)}", None, "invite", None, invite_hash
            except ChannelsTooMuchError:
                log.warning("ensure_join(invite): CHANNELS_TOO_MUCH invite=%s", invite_hash)
                return "too_many", None, "invite", None, invite_hash

            chats = getattr(updates, "chats", None)
            if not chats:
                # join request flow → нас ще не прийняли
                try:
                    invite_status_put(invite_hash, "requested")
                except Exception:
                    _log_exc("ensure_join: invite_status_put(requested) join_request")
                log.info("ensure_join(invite): sent join request invite=%s -> requested", invite_hash)
                return "requested", None, "invite", None, invite_hash

            ch = chats[0]
            cid = int(getattr(ch, "id", 0) or 0) or None
            title = getattr(ch, "title", "?") if ch else "?"

            if invite_hash and cid:
                    try:
                        map_invite_set(invite_hash, cid, title or None)
                        log.debug(
                            "ensure_join(invite): map_invite_set invite=%s cid=%s title=%r (joined)",
                            invite_hash,
                            cid,
                            title,
                        )
                    except Exception:
                        _log_exc("ensure_join: map_invite_set joined")
            log.info("ensure_join(invite): joined invite=%s cid=%s title=%r", invite_hash, cid, title)
            try:
                if cleaned_url:
                    url_put(cleaned_url, "joined")
            except Exception:
                _log_exc("ensure_join: url_put joined invite")
            return "joined", title, "invite", cid, invite_hash

        # --- публічний канал/чат ---
        # якщо прийшли сюди з інвайт-URL, ми вже відстояли invite-throttle,
        # тож пропускаємо додаткові public-затримки, щоб не дублювати очікування
        if not is_invite:
            await throttle_public()
        ent = await client.get_entity(url)

        if not is_invite:
            await throttle_public()
        try:
            await client(JoinChannelRequest(ent))
            title = getattr(ent, "title", "?")
            cid = int(getattr(ent, "id", 0) or 0) or None
            # якщо це був інвайт-URL, збережемо мапу/статус навіть у public-гілці
            if invite_hash and cid:
                try:
                    map_invite_set(invite_hash, cid, title or None)
                    invite_status_put(invite_hash, "joined")
                except Exception:
                    _log_exc("ensure_join: map_invite_set/invite_status_put joined public")
            log.info("ensure_join(public): joined url=%s cid=%s title=%r", url, cid, title)
            try:
                if cleaned_url:
                    url_put(cleaned_url, "joined")
            except Exception:
                _log_exc("ensure_join: url_put joined public")
            return "joined", title, "public", cid, invite_hash
        except UserAlreadyParticipantError:
            title = getattr(ent, "title", None)
            cid = int(getattr(ent, "id", 0) or 0) or None
            if invite_hash and cid:
                try:
                    map_invite_set(invite_hash, cid, title or None)
                    invite_status_put(invite_hash, "already")
                except Exception:
                    _log_exc("ensure_join: map_invite_set/invite_status_put already public")
            log.debug("ensure_join(public): already url=%s cid=%s title=%r", url, cid, title)
            try:
                if cleaned_url:
                    url_put(cleaned_url, "already")
            except Exception:
                _log_exc("ensure_join: url_put already public")
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
                _log_exc("ensure_join: invite_status_put(already) user_already")

            # 2) Прагнемо отримати channel_id без join – одним легким викликом

            try:
                await throttle_invite()  # поважаємо троттл
                inv = await client(CheckChatInviteRequest(invite_hash))

                chat = getattr(inv, "chat", None)

                cid = int(getattr(chat, "id", 0) or 0) if chat else None

                title = getattr(chat, "title", None)

                if cid:

                    try:

                        # збережемо мапу invite -> (channel_id, title)

                        map_invite_set(invite_hash, cid, title or None)
                        log.debug(
                            "ensure_join(invite): map_invite_set invite=%s cid=%s title=%r (already)",
                            invite_hash,
                            cid,
                            title,
                        )


                    except Exception:
                        _log_exc("ensure_join: map_invite_set already")

                return "already", title, "invite", cid, invite_hash


            except Exception:
                # якщо з якоїсь причини не вийшло — повертаємось без cid
                _log_exc("ensure_join: CheckChatInviteRequest after UserAlreadyParticipantError")
                return "already", None, "invite", None, invite_hash

        # публічні чати/канали: як і було

        return "already", None, kind, None, invite_hash

    except (InviteHashInvalidError, InviteHashExpiredError, UsernameNotOccupiedError):
        if is_invite and invite_hash:
            invite_status_put(invite_hash, "invalid")
        kind = "invite" if is_invite else "public"
        log.debug("ensure_join(%s): invalid/expired/not_occupied", kind)
        return "invalid", None, kind, None, invite_hash

    except Exception as e:
        # Якщо маємо кешований requested і Telegram каже, що інвайт протух (CheckChatInviteRequest),
        # відмічаємо як invalid, щоб не ходити по ньому знову.
        if is_invite and invite_hash and "expired and is not valid anymore" in str(e):
            try:
                invite_status_put(invite_hash, "invalid")
            except Exception:
                _log_exc("ensure_join: invite_status_put(invalid) unexpected")
            log.info("ensure_join(invite): expired -> invalid invite=%s", invite_hash)
            return "invalid", None, "invite", None, invite_hash
        raise

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
