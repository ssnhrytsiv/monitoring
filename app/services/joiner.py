# app/services/joiner.py
import logging
from contextlib import contextmanager

from app.utils.throttle import throttle_probe, throttle_invite, throttle_public, throttle_invite_peek
from telethon.errors.rpcerrorlist import InviteRequestSentError

from telethon.errors import (
    InviteHashInvalidError, InviteHashExpiredError,
    UserAlreadyParticipantError, FloodWaitError,
    UsernameNotOccupiedError, ChannelPrivateError,
    ChannelsTooMuchError,
)
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest,CheckChatInviteRequest

from app.DAL import session_scope
from app.DAL import membership_operations as mem_db
from app.DAL.membership_operations import FINAL_GLOBAL
from app.utils.link_parser import sanitize_link
from app.DAL import channels_operations as cho
from app.services.account_pool import is_already_subscribed, session_name

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


@contextmanager
def _db():
    with session_scope() as db:
        yield db


# DAO helpers
def invite_cache_get(invite_hash: str):
    with _db() as db:
        return mem_db.invite_cache_get(db, invite_hash)


def invite_cache_upsert(
    invite_hash: str,
    *,
    channel_id: int | None = None,
    title: str | None = None,
    status: str | None = None,
    session: str | None = None,
    last_error: str | None = None,
):
    with _db() as db:
        return mem_db.invite_cache_upsert(
            db,
            invite_hash,
            channel_id=channel_id,
            title=title,
            status=status,
            session=session,
            last_error=last_error,
        )


def any_final_for_channel(channel_id: int):
    with _db() as db:
        return mem_db.any_final_for_channel(db, channel_id)


def url_put(url: str, status: str):
    with _db() as db:
        return mem_db.url_put(db, url, status)


def bump_requested_attempt(invite_hash: str) -> int:
    with _db() as db:
        return mem_db.bump_requested_attempt(db, invite_hash)


def invite_check_last_session(invite_hash: str):
    with _db() as db:
        return mem_db.invite_check_last_session(db, invite_hash)


def _find_channel(channel_id: int):
    with _db() as db:
        return cho.find_channel(db, channel_id)


def _find_channel_by_link(raw_url: str):
    with _db() as db:
        return cho.find_channel_by_link(db, raw_url)


def _upsert_channel_basic(cid: int, ent, status: str) -> None:
    """
    Легкий апдейт channels: зберігаємо username/title для публічних каналів (не ботів).
    """
    if not cid or not ent:
        return
    try:
        username = getattr(ent, "username", None)
        if not username or getattr(ent, "bot", False):
            return
        title = getattr(ent, "title", None)
        with _db() as db:
            cho.upsert_channel(db, cid, username, title, owner_admin_id=None, last_status=status)
    except Exception:
        _log_exc("_upsert_channel_basic")


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
            with _db() as db:
                cache = mem_db.invite_cache_get(db, invite_hash)
                cid_cached = cache.channel_id if cache else None
                title_cached = cache.title if cache else None
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

    def _known_status_by_cid(cid: int | None) -> str | None:
        """Повертає already/known, якщо канал уже є в базі/мембершипі."""
        if not cid:
            return None
        try:
            with _db() as db:
                final = _final_from_cache(mem_db.any_final_for_channel(db, int(cid)))
        except Exception:
            _log_exc("ensure_join: any_final_for_channel known")
            final = None
        if final:
            return final
        try:
            if _find_channel(int(cid)):
                return "already"
        except Exception:
            _log_exc("ensure_join: find_channel known")
        return None

    invite_hash = _extract_invite_hash(url)
    is_invite = bool(invite_hash)
    requested_limit = 2

    def _cache_status(
        status: str | None,
        *,
        cid: int | None = None,
        title: str | None = None,
        last_error: str | None = None,
    ) -> None:
        if not invite_hash:
            return
        try:
            sess = None
            try:
                sess = session_name(client)
            except Exception:
                pass
            invite_cache_upsert(
                invite_hash,
                channel_id=cid,
                title=title,
                status=status,
                session=sess,
                last_error=last_error,
            )
        except Exception:
            _log_exc("ensure_join: invite_cache_upsert status")

    def _requested_status() -> str:
        """
        Інкрементує лічильник requested для інвайта і повертає
        requested або requested_fast (якщо >3 за добу).
        """
        if not invite_hash:
            return "requested"
        # рахуємо локально, але зберігаємо лише в invite_cache.status
        try:
            cnt = bump_requested_attempt(invite_hash)
            if cnt > requested_limit:
                invite_cache_upsert(invite_hash, status="requested_fast")
                return "requested_fast"
        except Exception:
            _log_exc("ensure_join: bump_requested_attempt")
        try:
            invite_cache_upsert(invite_hash, status="requested")
        except Exception:
            _log_exc("ensure_join: invite_cache_upsert(requested)")
        return "requested"

    # --- Спроба знайти канал за raw_url у кеші links через DAO (якщо вже лінкували) ---
    if cleaned_url:
        try:
            link_row = _find_channel_by_link(cleaned_url)
            if link_row:
                cid_link, title_link = link_row
                final = any_final_for_channel(cid_link)
                final_norm = _final_from_cache(final)
                if final_norm in FINAL_GLOBAL:
                    if invite_hash:
                        log.debug(
                            "ensure_join(link_cache): final=%s cid=%s invite=%s -> invite_cache not updated",
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
                    cache = invite_cache_get(invite_hash)
                    cid_cached = cache.channel_id if cache else None
                    title_cached = cache.title if cache else None
            except Exception:
                _log_exc("ensure_join: invite_cache_get")

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
                        "ensure_join(invite_cache): invite_cache not updated because already subscribed via %s",
                        who,
                    )
                    return "already", (title_cached or None), "invite", int(cid_cached), invite_hash

                # 🟢 Глобальна перевірка: якщо в кеші membership вже є фінальний статус по цьому каналу,
                # не робимо мережеву спробу, одразу повертаємо його.
                try:
                    with _db() as db:
                        final = _final_from_cache(mem_db.any_final_for_channel(db, int(cid_cached)))
                        if final:
                            if final not in ("joined", "already"):
                                invite_cache_upsert(invite_hash, status=final)
                            log.debug(
                                "ensure_join(invite_cache): final=%s invite=%s cid=%s -> invite_cache not updated",
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
            try:
                cache = invite_cache_get(invite_hash)
                st = cache.status if cache else None
                cid_known = cache.channel_id if cache else None
                title_known = cache.title if cache else None
            except Exception:
                st = None
                cid_known = None
                title_known = None
            log.debug("ensure_join(invite): invite_cache_get status=%s invite=%s", st, invite_hash)
            # Кешований too_many прив'язаний до інвайта, але це ліміт акаунта, тож його ігноруємо.
            if st == "too_many":
                pass
            elif st in ("invalid", "private", "requested", "requested_fast", "blocked"):
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
                                invite_cache_upsert(
                                    invite_hash,
                                    channel_id=cid_new,
                                    title=title_new or None,
                                    status="already",
                                    session=session_name(client),
                                )
                                log.debug(
                                    "ensure_join(invite_cache): invite_cache_upsert invite=%s cid=%s title=%r (requested->already)",
                                    invite_hash,
                                    cid_new,
                                    title_new,
                                )
                            except Exception:
                                _log_exc("ensure_join: invite_cache_upsert requested->already")
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
                                invite_cache_upsert(invite_hash, status="invalid", last_error=msg)
                            except Exception:
                                _log_exc("ensure_join: invite_cache_upsert(invalid) recheck")
                            log.info("ensure_join(invite): requested->invalid via recheck invite=%s", invite_hash)
                            return "invalid", (title_known or None), "invite", None, invite_hash
                        log.debug("ensure_join(invite): recheck failed invite=%s: %s", invite_hash, e)

                if invite_hash:
                    log.debug(
                        "ensure_join(invite_cache): cached status=%s invite=%s cid=%s -> invite_cache not updated",
                        st_norm,
                        invite_hash,
                        cid_known,
                    )
                return st_norm, (title_known or None), "invite", (int(cid_known) if cid_known else None), invite_hash

            # --- КРОК 1: реальна спроба приєднатися
            # Спершу легка перевірка інвайта без join: якщо вже є фінальний статус по channel_id,
            # не робимо ImportChatInviteRequest і не підписуємо іншу сесію.
            if invite_hash:
                sess_name = None
                try:
                    sess_name = session_name(client)
                except Exception:
                    _log_exc("ensure_join: session_name peek")
                try:
                    await throttle_invite_peek()
                    peek = await client(CheckChatInviteRequest(invite_hash))
                    chat = getattr(peek, "chat", None)
                    cid_peek = int(getattr(chat, "id", 0) or 0) if chat else None
                    title_peek = getattr(chat, "title", None)
                    if cid_peek:
                        try:
                            invite_cache_upsert(
                                invite_hash,
                                channel_id=cid_peek,
                                title=title_peek or None,
                                session=sess_name,
                            )
                            log.debug(
                                "ensure_join(invite): peek invite_cache_upsert invite=%s cid=%s title=%r sess=%s",
                                invite_hash,
                                cid_peek,
                                title_peek,
                                sess_name,
                            )
                        except Exception:
                            _log_exc("ensure_join: invite_cache_upsert peek")
                        try:
                            final_peek = _final_from_cache(any_final_for_channel(cid_peek))
                        except Exception:
                            final_peek = None
                        if not final_peek:
                            final_peek = _known_status_by_cid(cid_peek)
                        if final_peek:
                            try:
                                # кешуємо фінальний статус для інвайта (включно з joined/already)
                                invite_cache_upsert(
                                    invite_hash,
                                    status=final_peek,
                                    session=sess_name,
                                )
                            except Exception:
                                _log_exc("ensure_join: invite_cache_upsert peek status")
                            log.info(
                                "ensure_join(invite): peek final=%s cid=%s title=%r sess=%s -> skip join",
                                final_peek,
                                cid_peek,
                                title_peek,
                                sess_name,
                            )
                            return final_peek, (title_peek or None), "invite", cid_peek, invite_hash
                except FloodWaitError as e:
                    log.warning("ensure_join(invite): CheckChatInviteRequest flood %ss invite=%s", e.seconds, invite_hash)
                    return f"flood_wait_{int(e.seconds)}", None, "invite", None, invite_hash
                except (InviteHashInvalidError, InviteHashExpiredError):
                    log.debug("ensure_join(invite): peek invalid invite=%s", invite_hash)
                    invite_cache_upsert(invite_hash, status="invalid", last_error="invalid_invite")
                    return "invalid", None, "invite", None, invite_hash
                except Exception:
                    _log_exc("ensure_join: CheckChatInviteRequest peek")

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
                _cache_status("requested")
                log.info("ensure_join(invite): sent join request invite=%s -> requested", invite_hash)
                return "requested", None, "invite", None, invite_hash

            ch = chats[0]
            cid = int(getattr(ch, "id", 0) or 0) or None
            title = getattr(ch, "title", "?") if ch else "?"

            if invite_hash and cid:
                _cache_status(None, cid=cid, title=title or None)
                known = _known_status_by_cid(cid)
                if known:
                    _cache_status(known, cid=cid, title=title or None)
                    log.info(
                        "ensure_join(invite): known channel cid=%s status=%s title=%r (no rejoin)",
                        cid,
                        known,
                        title,
                    )
                    return known, (title or None), "invite", cid, invite_hash
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
        try:
            ent = await client.get_entity(url)
        except (UsernameNotOccupiedError, ValueError):
            log.debug("ensure_join(public): username not occupied url=%s", url)
            return "invalid", None, "public", None, invite_hash
        except ChannelPrivateError:
            log.debug("ensure_join(public): channel private url=%s", url)
            return "private", None, "public", None, invite_hash
        except Exception:
            _log_exc("ensure_join: get_entity")
            return "invalid", None, "public", None, invite_hash

        if not is_invite:
            await throttle_public()
        try:
            await client(JoinChannelRequest(ent))
            title = getattr(ent, "title", "?")
            cid = int(getattr(ent, "id", 0) or 0) or None
            # якщо це був інвайт-URL, збережемо мапу/статус навіть у public-гілці
            if invite_hash and cid:
                _cache_status("joined", cid=cid, title=title or None)
            log.info("ensure_join(public): joined url=%s cid=%s title=%r", url, cid, title)
            try:
                if cleaned_url:
                    url_put(cleaned_url, "joined")
            except Exception:
                _log_exc("ensure_join: url_put joined public")
            try:
                if cid:
                    _upsert_channel_basic(cid, ent, "joined")
            except Exception:
                pass
            return "joined", title, "public", cid, invite_hash
        except UserAlreadyParticipantError:
            title = getattr(ent, "title", None)
            cid = int(getattr(ent, "id", 0) or 0) or None
            if invite_hash and cid:
                _cache_status("already", cid=cid, title=title or None)
            log.debug("ensure_join(public): already url=%s cid=%s title=%r", url, cid, title)
            try:
                if cleaned_url:
                    url_put(cleaned_url, "already")
            except Exception:
                _log_exc("ensure_join: url_put already public")
            try:
                if cid:
                    _upsert_channel_basic(cid, ent, "already")
            except Exception:
                pass
            return "already", title, "public", cid, invite_hash

    # ---- обробка винятків ----
    except InviteRequestSentError:
        if is_invite and invite_hash:
            _cache_status("requested")
        log.info("ensure_join(invite): InviteRequestSentError invite=%s -> requested", invite_hash)
        return "requested", None, "invite", None, invite_hash




    except UserAlreadyParticipantError:

        kind = "invite" if is_invite else "public"

        log.debug("ensure_join(%s): UserAlreadyParticipantError -> already", kind)

        if is_invite and invite_hash:

            # 1) Позначаємо статус

            _cache_status("already")

            # 2) Прагнемо отримати channel_id без join – одним легким викликом

            try:
                await throttle_invite()  # поважаємо троттл
                inv = await client(CheckChatInviteRequest(invite_hash))

                chat = getattr(inv, "chat", None)

                cid = int(getattr(chat, "id", 0) or 0) if chat else None

                title = getattr(chat, "title", None)

                if cid:

                    _cache_status("already", cid=cid, title=title or None)

                return "already", title, "invite", cid, invite_hash


            except Exception:
                # якщо з якоїсь причини не вийшло — повертаємось без cid
                _log_exc("ensure_join: CheckChatInviteRequest after UserAlreadyParticipantError")
                return "already", None, "invite", None, invite_hash

        # публічні чати/канали: як і було

        return "already", None, kind, None, invite_hash

    except (InviteHashInvalidError, InviteHashExpiredError, UsernameNotOccupiedError):
        if is_invite and invite_hash:
            _cache_status("invalid")
        kind = "invite" if is_invite else "public"
        log.debug("ensure_join(%s): invalid/expired/not_occupied", kind)
        return "invalid", None, kind, None, invite_hash

    except Exception as e:
        # Якщо маємо кешований requested і Telegram каже, що інвайт протух (CheckChatInviteRequest),
        # відмічаємо як invalid, щоб не ходити по ньому знову.
        if is_invite and invite_hash and "expired and is not valid anymore" in str(e):
            _cache_status("invalid")
            log.info("ensure_join(invite): expired -> invalid invite=%s", invite_hash)
            return "invalid", None, "invite", None, invite_hash
        raise

    except ChannelPrivateError:
        if is_invite and invite_hash:
            _cache_status("private")
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
                _cache_status("blocked")
            log.warning("ensure_join(%s): blocked/banned", kind)
            return "blocked", None, kind, None, invite_hash
        if "INVITE_REQUEST_SENT" in msg:
            if is_invite and invite_hash:
                _cache_status("requested")
            log.info("ensure_join(%s): INVITE_REQUEST_SENT -> requested", kind)
            return "requested", None, kind, None, invite_hash
        log.exception("ensure_join(%s): unexpected error: %s", kind, msg)
        return "error", msg, kind, None, invite_hash
