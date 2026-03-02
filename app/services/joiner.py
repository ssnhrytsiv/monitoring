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

from app.DAL import SessionLocal
from app.DAL.membership_operations import MembershipDAO, FINAL_GLOBAL
from app.DAL import membership_operations as mem_db
from app.utils.link_parser import sanitize_link
from app.DAL import channels_operations as cho
from app.services.account_pool import is_already_subscribed, session_name

log = logging.getLogger("services.joiner")


def _log_exc(context: str) -> None:
    """Debug-log suppressed exceptions to trace why invite_map may not update."""
    log.debug("%s: suppressed exception", context, exc_info=True)


def _trace_joiner(event: str, data: dict) -> None:
    """Lightweight trace helper to avoid NameError in optional tracing."""
    try:
        log.debug("joiner.trace %s %s", event, data)
    except Exception:
        pass


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
def _membership():
    db = SessionLocal()
    try:
        yield MembershipDAO(db)
    finally:
        db.close()


@contextmanager
def _db():
    """
    Локальний синонім SessionLocal для допоміжних читань/перевірок у ensure_join.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# DAO helpers (зберігають старі назви, але працюють через класовий DAO)
def map_invite_get(invite_hash: str):
    with _membership() as mem_dao:
        return mem_dao.map_invite_get(invite_hash)


def map_invite_set(invite_hash: str, channel_id: int, title: str | None = None):
    with _membership() as mem_dao:
        return mem_dao.map_invite_set(invite_hash, channel_id, title)


def invite_status_get(invite_hash: str):
    with _membership() as mem_dao:
        return mem_dao.invite_status_get(invite_hash)


def invite_status_put(invite_hash: str, status: str):
    with _membership() as mem_dao:
        return mem_dao.invite_status_put(invite_hash, status)


def any_final_for_channel(channel_id: int):
    with _membership() as mem_dao:
        return mem_dao.any_final_for_channel(channel_id)


def url_put(url: str, status: str):
    with _membership() as mem_dao:
        return mem_dao.url_put(url, status)


def bump_requested_attempt(invite_hash: str) -> int:
    with _membership() as mem_dao:
        return mem_dao.bump_requested_attempt(invite_hash)


def invite_check_last_session(invite_hash: str):
    with _membership() as mem_dao:
        return mem_dao.invite_check_last_session(invite_hash)


def _membership_dao():
    db = SessionLocal()
    return MembershipDAO(db), db


def _find_channel(channel_id: int):
    db = SessionLocal()
    try:
        return cho.find_channel(db, channel_id)
    finally:
        db.close()


def _find_channel_by_link(raw_url: str):
    db = SessionLocal()
    try:
        return cho.find_channel_by_link(db, raw_url)
    finally:
        db.close()


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
        db = SessionLocal()
        try:
            cho.upsert_channel(db, cid, username, title, None, None, status)
        finally:
            db.close()
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
            mem_dao, db = _membership_dao()
            try:
                cid_cached, title_cached = mem_dao.map_invite_get(invite_hash)
            finally:
                db.close()
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
            with _membership() as mem_dao:
                final = _final_from_cache(mem_dao.any_final_for_channel(int(cid)))
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

    sess_current = None
    try:
        sess_current = session_name(client)
    except Exception:
        _log_exc("ensure_join: session_name init")
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
                    with _membership() as mem_dao:
                        cid_cached, title_cached = mem_dao.map_invite_get(invite_hash)
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

                # 🟢 Глобальна перевірка: якщо в кеші membership вже є фінальний статус по цьому каналу,
                # не робимо мережеву спробу, одразу повертаємо його.
                try:
                    with _membership() as mem_dao:
                        final = _final_from_cache(mem_dao.any_final_for_channel(int(cid_cached)))
                        if final:
                            if final not in ("joined", "already"):
                                mem_dao.invite_status_put(invite_hash, final)
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
            try:
                with _membership() as mem_dao:
                    st = mem_dao.invite_status_get(invite_hash)
            except Exception:
                st = None
            log.debug("ensure_join(invite): invite_status_get=%s invite=%s", st, invite_hash)
            # Кешований too_many прив'язаний до інвайта, але це ліміт акаунта, тож його ігноруємо.
            if st == "too_many":
                pass
            elif st in ("invalid", "blocked"):
                cid_known, title_known = map_invite_get(invite_hash)
                st_norm = _final_from_cache(st)
                log.debug("ensure_join(invite): cached status=%s(invite=%s cid=%s) -> %s", st, invite_hash, cid_known, st_norm)
                if invite_hash:
                    log.debug(
                        "ensure_join(invite_cache): cached status=%s invite=%s cid=%s -> invite_map not updated",
                        st_norm,
                        invite_hash,
                        cid_known,
                    )
                return st_norm, (title_known or None), "invite", (int(cid_known) if cid_known else None), invite_hash
            elif st in ("requested", "requested_fast", "private"):
                cid_known, title_known = map_invite_get(invite_hash)
                st_norm = _final_from_cache(st)
                if st == "requested":
                    st_norm = _requested_status()
                log.debug("ensure_join(invite): cached status=%s(invite=%s cid=%s) -> %s", st, invite_hash, cid_known, st_norm)

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
                                "ensure_join(invite_cache): map_invite_set invite=%s cid=%s title=%r (%s->already)",
                                invite_hash,
                                cid_new,
                                title_new,
                                st,
                            )
                        except Exception:
                            _log_exc("ensure_join: map_invite_set requested->already")
                        try:
                            invite_status_put(invite_hash, "already")
                        except Exception:
                            _log_exc("ensure_join: invite_status_put(already) recheck")
                        log.info("ensure_join(invite): %s->already via recheck invite=%s cid=%s", st, invite_hash, cid_new)
                        return "already", (title_new or title_known or None), "invite", cid_new, invite_hash
                except InviteRequestSentError:
                    # Заявка ще pending; продовжимо до ImportChatInviteRequest, щоб повторно натиснути "request".
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

                log.debug(
                    "ensure_join(invite): cached status=%s invite=%s -> continue with ImportChatInviteRequest",
                    st_norm,
                    invite_hash,
                )

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
                            map_invite_set(invite_hash, cid_peek, title_peek or None)
                            log.debug(
                                "ensure_join(invite): peek map_invite_set invite=%s cid=%s title=%r sess=%s",
                                invite_hash,
                                cid_peek,
                                title_peek,
                                sess_name,
                            )
                        except Exception:
                            _log_exc("ensure_join: map_invite_set peek")
                        try:
                            final_peek = _final_from_cache(any_final_for_channel(cid_peek))
                        except Exception:
                            final_peek = None
                        if not final_peek:
                            final_peek = _known_status_by_cid(cid_peek)
                        if final_peek:
                            try:
                                # кешуємо фінальний статус для інвайта (включно з joined/already)
                                invite_status_put(invite_hash, final_peek)
                            except Exception:
                                _log_exc("ensure_join: invite_status_put peek")
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
                    invite_status_put(invite_hash, "invalid")
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
                try:
                    invite_status_put(invite_hash, "requested")
                except Exception:
                    _log_exc("ensure_join: invite_status_put(requested) join_request")
                log.info("ensure_join(invite): sent join request invite=%s -> requested", invite_hash)
                return "requested", None, "invite", None, invite_hash

            ch = chats[0]
            cid = int(getattr(ch, "id", 0) or 0) or None
            title = getattr(ch, "title", "?") if ch else "?"

            # Якщо канал уже приєднаний іншою сесією — одразу leave і повертаємо already
            if cid:
                try:
                    with _db() as db_chk:
                        sess_other = mem_db.get_any_session_for_channel(db_chk, cid)
                    if sess_other and sess_other != (sess_current or ""):
                        _trace_joiner(
                            "leave_due_to_other_session",
                            {
                                "cid": cid,
                                "title": title,
                                "sess_current": sess_current,
                                "sess_other": sess_other,
                                "url": url,
                                "phase": "after_import_invite",
                            },
                        )
                        try:
                            from telethon.tl.functions.channels import LeaveChannelRequest

                            await client(LeaveChannelRequest(ch))
                        except Exception:
                            _log_exc("ensure_join: leave other session (invite)")
                        try:
                            mem_db.delete_membership(db_chk, sess_current or "", cid)
                        except Exception:
                            _log_exc("ensure_join: delete_membership after leave (invite)")
                        return "already", title, "invite", cid, invite_hash
                except Exception:
                    _log_exc("ensure_join: check other session after invite import")

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
                known = _known_status_by_cid(cid)
                if known:
                    try:
                        invite_status_put(invite_hash, known)
                    except Exception:
                        _log_exc("ensure_join: invite_status_put known joined")
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
            if cid:
                try:
                    with _db() as db_chk:
                        sess_other = mem_db.get_any_session_for_channel(db_chk, cid)
                    if sess_other and sess_other != (sess_current or ""):
                        _trace_joiner(
                            "leave_due_to_other_session",
                            {
                                "cid": cid,
                                "title": title,
                                "sess_current": sess_current,
                                "sess_other": sess_other,
                                "url": url,
                                "phase": "after_join_public",
                            },
                        )
                        try:
                            from telethon.tl.functions.channels import LeaveChannelRequest

                            await client(LeaveChannelRequest(ent))
                        except Exception:
                            _log_exc("ensure_join: leave other session (public)")
                        try:
                            mem_db.delete_membership(db_chk, sess_current or "", cid)
                        except Exception:
                            _log_exc("ensure_join: delete_membership after leave (public)")
                        return "already", title, "public", cid, invite_hash
                except Exception:
                    _log_exc("ensure_join: check other session after public join")
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
            try:
                if cid:
                    _upsert_channel_basic(cid, ent, "already")
            except Exception:
                pass
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
        if is_invite and invite_hash and "expired and is not valid anymore" in msg:
            try:
                invite_status_put(invite_hash, "invalid")
            except Exception:
                _log_exc("ensure_join: invite_status_put(invalid) unexpected")
            log.info("ensure_join(invite): expired -> invalid invite=%s", invite_hash)
            return "invalid", None, "invite", None, invite_hash
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
