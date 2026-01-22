# app/services/joiner.py
import logging
from contextlib import contextmanager

from app.utils.throttle import throttle_invite, throttle_public, throttle_invite_peek
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
from app.utils.link_parser import sanitize_link, build_invite_url
from app.DAL import channels_operations as cho
from app.DAL import link_cache_operations as lc_db
from app.DAL.schemas import LinkCachePatch
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


@contextmanager
def _db():
    with session_scope() as db:
        yield db


def any_final_for_channel(channel_id: int):
    with _db() as db:
        return mem_db.any_final_for_channel(db, channel_id)


def url_put(url: str, status: str, *, account: str | None = None):
    try:
        clean = sanitize_link(url) or url
    except Exception:
        clean = url
    if account:
        try:
            lc_db.update_link_cache_status(
                LinkCachePatch(
                    url_norm=clean,
                    kind="public",
                    status=status,
                    account=account,
                )
            )
        except Exception:
            _log_exc("url_put: link_cache update")


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
        log.exception("_upsert_channel_basic failed cid=%s status=%s", cid, status)


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
    invite_url_norm = build_invite_url(_extract_invite_hash(url))

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
    sess_current: str | None = None
    try:
        sess_current = session_name(client)
    except Exception:
        sess_current = None
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
        key = invite_url_norm or invite_hash
        sess = sess_current
        try:
            lc_db.update_link_cache_status(
                LinkCachePatch(
                    url_norm=key,
                    kind="invite",
                    status=status or "",
                    account=sess or "",
                    channel_id=cid,
                    title=title,
                    last_error=last_error,
                )
            )
        except Exception:
            log.exception("ensure_join: link_cache_upsert status failed invite=%s status=%s", invite_hash, status)

    def _requested_status() -> str:
        """
        Інкрементує лічильник requested для інвайта і повертає
        requested або requested_fast (якщо >3 за добу).
        """
        if not invite_hash:
            return "requested"
        sess = sess_current
        try:
            cnt = bump_requested_attempt(invite_hash)
            if cnt > requested_limit:
                try:
                    lc_db.update_link_cache_status(
                        LinkCachePatch(
                            url_norm=invite_url_norm or invite_hash,
                            kind="invite",
                            status="requested_fast",
                            account=sess or "",
                        )
                    )
                except Exception:
                    _log_exc("ensure_join: link_cache_upsert requested_fast")
                return "requested_fast"
        except Exception:
            _log_exc("ensure_join: bump_requested_attempt")
        try:
            lc_db.update_link_cache_status(
                LinkCachePatch(
                    url_norm=invite_url_norm or invite_hash,
                    kind="invite",
                    status="requested",
                    account=sess or "",
                )
            )
        except Exception:
            _log_exc("ensure_join: link_cache_upsert requested")
        return "requested"

    # --- Спроба знайти канал за raw_url у кеші links через DAO (якщо вже лінкували) ---
    if cleaned_url:
        try:
            link_row = _find_channel_by_link(cleaned_url)
            if link_row:
                cid_link = getattr(link_row, "channel_id", None)
                title_link = getattr(link_row, "title", None)
                # Підтримуємо стару форму (tuple), якщо DAO поверне кортеж
                if cid_link is None and isinstance(link_row, (tuple, list)) and len(link_row) >= 1:
                    cid_link = link_row[0]
                if title_link is None and isinstance(link_row, (tuple, list)) and len(link_row) >= 2:
                    title_link = link_row[1]
                if cid_link is not None:
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
                rec_cached_link = lc_db.get_link_cache_record(invite_url_norm or invite_hash)
                if rec_cached_link:
                    cid_cached = rec_cached_link.channel_id or cid_cached
                    title_cached = rec_cached_link.title or title_cached
            except Exception:
                _log_exc("ensure_join: link_cache_get invite")

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
                    try:
                        lc_db.update_link_cache_status(
                            LinkCachePatch(
                                url_norm=invite_url_norm or invite_hash,
                                kind="invite",
                                status="duplicate",
                                account=sess_current or "",
                                channel_id=cid_cached,
                                title=title_cached or None,
                            )
                        )
                    except Exception:
                        _log_exc("ensure_join: link_cache_upsert duplicate invite already")
                    return "already", (title_cached or None), "invite", int(cid_cached), invite_hash

                # 🟢 Глобальна перевірка: якщо в кеші membership вже є фінальний статус по цьому каналу,
                # не робимо мережеву спробу, одразу повертаємо його.
                try:
                    with _db() as db:
                        final = _final_from_cache(mem_db.any_final_for_channel(db, int(cid_cached)))
                        if final:
                            if final not in ("joined", "already"):
                                _cache_status(final, cid=cid_cached, title=title_cached or None)
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
                rec_cached_link = lc_db.get_link_cache_record(invite_url_norm or invite_hash)
                st = rec_cached_link.status if rec_cached_link else None
                cid_known = rec_cached_link.channel_id if rec_cached_link else None
                title_known = rec_cached_link.title if rec_cached_link else None
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
                                _cache_status("already", cid=cid_new, title=title_new or None)
                                log.debug(
                                    "ensure_join(invite_cache): link_cache_upsert invite=%s cid=%s title=%r (requested->already)",
                                    invite_hash,
                                    cid_new,
                                    title_new,
                                )
                            except Exception:
                                _log_exc("ensure_join: link_cache_upsert requested->already")
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
                                _cache_status("invalid", last_error=msg)
                            except Exception:
                                _log_exc("ensure_join: link_cache_upsert(invalid) recheck")
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
                            _cache_status(None, cid=cid_peek, title=title_peek or None)
                            log.debug(
                                "ensure_join(invite): peek link_cache_upsert invite=%s cid=%s title=%r sess=%s",
                                invite_hash,
                                cid_peek,
                                title_peek,
                                sess_name,
                            )
                        except Exception:
                            _log_exc("ensure_join: link_cache_upsert peek")
                        try:
                            final_peek = _final_from_cache(any_final_for_channel(cid_peek))
                        except Exception:
                            final_peek = None
                        if not final_peek:
                            final_peek = _known_status_by_cid(cid_peek)
                        if final_peek:
                            try:
                                # кешуємо фінальний статус для інвайта (включно з joined/already)
                                _cache_status(final_peek, cid=cid_peek, title=title_peek or None)
                            except Exception:
                                _log_exc("ensure_join: link_cache_upsert peek status")
                        log.info(
                            "ensure_join(invite): peek final=%s cid=%s title=%r sess=%s -> skip join",
                            final_peek,
                            cid_peek,
                            title_peek,
                            sess_name,
                        )
                        try:
                            lc_db.update_link_cache_status(
                                LinkCachePatch(
                                    url_norm=invite_url_norm or invite_hash,
                                    kind="invite",
                                    status="duplicate",
                                    account=sess_current or "",
                                    channel_id=cid_peek,
                                    title=title_peek or None,
                                )
                            )
                        except Exception:
                            _log_exc("ensure_join: link_cache_upsert duplicate invite")
                        return final_peek, (title_peek or None), "invite", cid_peek, invite_hash
                except FloodWaitError as e:
                    log.warning("ensure_join(invite): CheckChatInviteRequest flood %ss invite=%s", e.seconds, invite_hash)
                    return f"flood_wait_{int(e.seconds)}", None, "invite", None, invite_hash
                except (InviteHashInvalidError, InviteHashExpiredError):
                    log.debug("ensure_join(invite): peek invalid invite=%s", invite_hash)
                    try:
                        _cache_status("invalid", last_error="invalid_invite")
                    except Exception:
                        _log_exc("ensure_join: link_cache_upsert invalid invite")
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
                    url_put(cleaned_url, "joined", account=sess_current)
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
            try:
                if cleaned_url:
                    lc_db.update_link_cache_status(
                        LinkCachePatch(
                            url_norm=cleaned_url,
                            kind="public",
                            status="invalid",
                            account=sess_current or "",
                            last_error="username_not_occupied",
                        )
                    )
            except Exception:
                _log_exc("ensure_join: link_cache_upsert invalid public")
            return "invalid", None, "public", None, invite_hash
        except ChannelPrivateError:
            log.debug("ensure_join(public): channel private url=%s", url)
            try:
                if cleaned_url:
                    lc_db.update_link_cache_status(
                        LinkCachePatch(
                            url_norm=cleaned_url,
                            kind="public",
                            status="private",
                            account=sess_current or "",
                            last_error="channel_private",
                        )
                    )
            except Exception:
                _log_exc("ensure_join: link_cache_upsert private public")
            return "private", None, "public", None, invite_hash
        except Exception as e:
            _log_exc("ensure_join: get_entity")
            try:
                if cleaned_url:
                    lc_db.update_link_cache_status(
                        LinkCachePatch(
                            url_norm=cleaned_url,
                            kind="public",
                            status="invalid",
                            account=sess_current or "",
                            last_error=str(e),
                        )
                    )
            except Exception:
                _log_exc("ensure_join: link_cache_upsert invalid exception")
            return "invalid", None, "public", None, invite_hash

        if not is_invite:
            await throttle_public()
        try:
            # якщо вже знаємо цей канал — позначаємо duplicate і не робимо join
            cid_pre = int(getattr(ent, "id", 0) or 0) or None
            if cid_pre:
                known = _known_status_by_cid(cid_pre)
                if known:
                    try:
                        if cleaned_url:
                            lc_db.update_link_cache_status(
                                LinkCachePatch(
                                    url_norm=cleaned_url,
                                    kind="public",
                                    status="duplicate",
                                    account=sess_current or "",
                                    channel_id=cid_pre,
                                    title=getattr(ent, "title", None),
                                )
                            )
                    except Exception:
                        _log_exc("ensure_join: link_cache_upsert duplicate public")
                    return known, getattr(ent, "title", None), "public", cid_pre, invite_hash

            await client(JoinChannelRequest(ent))
            title = getattr(ent, "title", "?")
            cid = int(getattr(ent, "id", 0) or 0) or None
            # якщо це був інвайт-URL, збережемо мапу/статус навіть у public-гілці
            if invite_hash and cid:
                _cache_status("joined", cid=cid, title=title or None)
            log.info("ensure_join(public): joined url=%s cid=%s title=%r", url, cid, title)
            try:
                if cleaned_url:
                    url_put(cleaned_url, "joined", account=sess_current)
            except Exception:
                log.exception("ensure_join: url_put joined public failed url=%s cid=%s", cleaned_url, cid)
            try:
                if cleaned_url and cid:
                    lc_db.update_link_cache_status(
                        LinkCachePatch(
                            url_norm=cleaned_url,
                            kind="public",
                            status="joined",
                            account=sess_current or "",
                            channel_id=cid,
                            title=title or None,
                        )
                    )
            except Exception:
                _log_exc("ensure_join: link_cache_upsert joined public")
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
                    url_put(cleaned_url, "already", account=sess_current)
            except Exception:
                log.exception("ensure_join: url_put already public failed url=%s cid=%s", cleaned_url, cid)
            try:
                if cleaned_url and cid:
                    lc_db.update_link_cache_status(
                        LinkCachePatch(
                            url_norm=cleaned_url,
                            kind="public",
                            status="already",
                            account=sess_current or "",
                            channel_id=cid,
                            title=title or None,
                        )
                    )
            except Exception:
                _log_exc("ensure_join: link_cache_upsert already public")
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
            _cache_status("private", last_error="channel_private")
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
