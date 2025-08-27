# app/services/joiner.py
from __future__ import annotations

import logging
import os
import time
from collections import deque
from typing import Dict, Tuple

from telethon.errors import (
    InviteHashInvalidError, InviteHashExpiredError,
    UserAlreadyParticipantError, FloodWaitError,
    UsernameNotOccupiedError, ChannelPrivateError,
)
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest

from app.services.db import map_invite_set, map_invite_get
from app.utils.throttle import throttle_probe  # легкий throttle для probe

# опціонально беремо красиве ім'я акаунта для логів
try:
    from app.services.account_pool import session_name as _session_name
except Exception:  # fallback
    def _session_name(_):  # type: ignore
        return "unknown.session"

log = logging.getLogger("services.joiner")

# =========================
#   Anti-dup та rate-budget
# =========================

DEDUP_WINDOW_SEC = int(os.getenv("ANTI_DUP_WINDOW_SEC", "600"))  # 10 хв
BUDGET_CHECK_INVITE = int(os.getenv("BUDGET_CHECK_INVITE_PER_MIN", "15"))
BUDGET_GET_ENTITY   = int(os.getenv("BUDGET_GET_ENTITY_PER_MIN",   "30"))
BUDGET_IMPORT_INV   = int(os.getenv("BUDGET_IMPORT_INVITE_PER_MIN","5"))
BUDGET_JOIN         = int(os.getenv("BUDGET_JOIN_PER_MIN",         "10"))

# (call_type, key) -> last_ts
_LAST_CALL: Dict[Tuple[str, str], float] = {}

# (account, call_type) -> deque of timestamps (last 60s)
_RATE_BUCKET: Dict[Tuple[str, str], deque] = {}

def _now() -> float:
    return time.time()

def _norm_url(u: str) -> str:
    return (u or "").strip().lower()

def _anti_dup_allow(call_type: str, key: str) -> bool:
    """True -> можна викликати; False -> пропустити як дубль у межах TTL."""
    if DEDUP_WINDOW_SEC <= 0:
        return True
    k = (call_type, key)
    ts = _LAST_CALL.get(k, 0.0)
    now = _now()
    if now - ts < DEDUP_WINDOW_SEC:
        return False
    _LAST_CALL[k] = now
    return True

def _rate_allow(account: str, call_type: str) -> Tuple[bool, int]:
    """
    Простий “per-minute” бюджет. True -> можна; False -> зачекай `retry_after` сек.
    """
    limit = {
        "check_invite": BUDGET_CHECK_INVITE,
        "get_entity":   BUDGET_GET_ENTITY,
        "import_invite":BUDGET_IMPORT_INV,
        "join_channel": BUDGET_JOIN,
    }.get(call_type, 60)

    if limit <= 0:
        return True, 0

    key = (account, call_type)
    q = _RATE_BUCKET.get(key)
    if q is None:
        q = deque()
        _RATE_BUCKET[key] = q

    now = _now()
    # прибрати старіші за 60с
    while q and now - q[0] >= 60.0:
        q.popleft()

    if len(q) >= limit:
        retry_after = int(max(1.0, 60.0 - (now - q[0])))
        return False, retry_after

    q.append(now)
    return True, 0

# =========================


def _extract_invite_hash(url: str) -> str | None:
    """
    Витягує invite hash з URL виду:
      - https://t.me/+XXXXXXXX
      - https://t.me/joinchat/XXXXXXXX
    Повертає лише сам hash (без '+', без префіксів), або None.
    """
    try:
        if "/+" in url:
            return url.rsplit("/", 1)[-1].replace("+", "").strip()
        if "joinchat/" in url:
            return url.rsplit("joinchat/", 1)[-1].strip()
        return None
    except Exception:
        return None


async def probe_channel_id(client, url: str):
    """
    Повертає (channel_id, title, kind, invite_hash)
      - kind: 'invite' | 'public'
      - invite_hash: str | None

    1) Якщо інвайт — спершу дивимось у кеш (map_invite_get по HASH).
    2) Якщо нема — CheckChatInviteRequest(invite_hash) з легким throttle,
       але з анти-дублем (TTL) і простим rate-budget.
    3) Інакше (публічний) — client.get_entity(url) з анти-дублем і rate-budget.

    Якщо анти-дубль або rate обмеження спрацювало — виклик пропускаємо,
    логуємо причину і повертаємо (None, None, kind, invite_hash).
    """
    acc = _session_name(client)
    invite_hash = _extract_invite_hash(url)
    if invite_hash:
        # 1) кеш за інвайтом (ключ — HASH)
        try:
            cid_cached, title_cached = map_invite_get(invite_hash)
            if cid_cached:
                return int(cid_cached), (title_cached or None), "invite", invite_hash
        except Exception:
            pass

        # Анти-дубль на check_invite
        if not _anti_dup_allow("check_invite", invite_hash):
            log.debug("probe_channel_id: SKIP anti-dup for invite=%s url=%s", invite_hash, url)
            return None, None, "invite", invite_hash

        # Rate-budget на check_invite
        ok, retry = _rate_allow(acc, "check_invite")
        if not ok:
            log.debug("probe_channel_id: SKIP rate-limit for %s (retry ~%ss)", acc, retry)
            return None, None, "invite", invite_hash

        # 2) пробуємо подивитися інвайт через API
        try:
            await throttle_probe(url)
            log.debug("probe_channel_id: CheckChatInviteRequest for %s", url)
            info = await client(CheckChatInviteRequest(invite_hash))
            chat = getattr(info, "chat", None)
            if chat is not None:
                return int(chat.id), getattr(chat, "title", None), "invite", invite_hash
            return None, getattr(info, "title", None), "invite", invite_hash
        except FloodWaitError as e:
            log.warning(
                "FLOOD in probe_channel_id(CheckChatInviteRequest): url=%s seconds=%s",
                url, e.seconds
            )
            raise
        except (InviteHashInvalidError, InviteHashExpiredError):
            return None, None, "invite", invite_hash
        except ChannelPrivateError:
            return None, None, "invite", invite_hash
        except Exception:
            return None, None, "invite", invite_hash

    # 3) public / username / прямий t.me/channel
    # Анти-дубль на get_entity
    url_key = _norm_url(url)
    if not _anti_dup_allow("get_entity", url_key):
        log.debug("probe_channel_id: SKIP anti-dup for get_entity url=%s", url)
        return None, None, "public", None

    ok, retry = _rate_allow(acc, "get_entity")
    if not ok:
        log.debug("probe_channel_id: SKIP rate-limit get_entity for %s (retry ~%ss)", acc, retry)
        return None, None, "public", None

    try:
        await throttle_probe(url)
        log.debug("probe_channel_id: get_entity for %s", url)
        ent = await client.get_entity(url)
        cid = int(getattr(ent, "id", 0) or 0)
        title = getattr(ent, "title", None)
        return cid if cid else None, title, "public", None
    except FloodWaitError as e:
        log.warning(
            "FLOOD in probe_channel_id(get_entity): url=%s seconds=%s",
            url, e.seconds
        )
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
    Повертає кортеж із 5 полів:
      (status, title, kind, channel_id|None, invite_hash|None)

    Можливі status:
      - 'joined'
      - 'already'
      - 'requested'   (INVITE_REQUEST_SENT)
      - 'invalid'     (інвайт невалідний/прострочений/імʼя не зайняте)
      - 'private'
      - 'blocked'
      - 'too_many'    (CHANNELS_TOO_MUCH / Too many channels)
      - 'flood_wait_<sec>'
      - 'temp_rate_limit'
      - 'error'       (+ текст у title)
    """
    acc = _session_name(client)
    invite_hash = _extract_invite_hash(url)
    is_invite = invite_hash is not None

    try:
        if is_invite:
            # Rate-budget на import_invite
            ok, retry = _rate_allow(acc, "import_invite")
            if not ok:
                log.debug("ensure_join: SKIP rate-limit ImportChatInviteRequest for %s (retry~%ss)", acc, retry)
                return "temp_rate_limit", None, "invite", None, invite_hash

            # --- інвайт ---
            try:
                log.debug("ensure_join: ImportChatInviteRequest for %s", url)
                updates = await client(ImportChatInviteRequest(invite_hash))
            except FloodWaitError as e:
                log.warning(
                    "FLOOD in ensure_join(ImportChatInviteRequest): url=%s seconds=%s",
                    url, e.seconds
                )
                raise
            ch = updates.chats[0] if getattr(updates, "chats", None) else None
            cid = int(ch.id) if ch else None
            title = getattr(ch, "title", "?") if ch else "?"
            # закріплюємо мапу інвайта по HASH (стабільний ключ)
            if invite_hash and cid:
                map_invite_set(invite_hash, cid, title or None)
            return "joined", title, "invite", cid, invite_hash

        # --- публічний канал/чат ---
        # Rate-budget на get_entity
        ok, retry = _rate_allow(acc, "get_entity")
        if not ok:
            log.debug("ensure_join: SKIP rate-limit get_entity for %s (retry~%ss)", acc, retry)
            return "temp_rate_limit", None, "public", None, None

        try:
            log.debug("ensure_join: get_entity for %s", url)
            ent = await client.get_entity(url)
        except FloodWaitError as e:
            log.warning(
                "FLOOD in ensure_join(get_entity): url=%s seconds=%s",
                url, e.seconds
            )
            raise

        cid_public = int(getattr(ent, "id", 0) or 0)
        title_public = getattr(ent, "title", None)

        # Rate-budget на join_channel
        ok, retry = _rate_allow(acc, "join_channel")
        if not ok:
            log.debug("ensure_join: SKIP rate-limit JoinChannelRequest for %s (retry~%ss)", acc, retry)
            return "temp_rate_limit", title_public, "public", (cid_public or None), None

        try:
            log.debug("ensure_join: JoinChannelRequest for %s", url)
            await client(JoinChannelRequest(ent))
            return "joined", (title_public or "?"), "public", (cid_public or None), None
        except FloodWaitError as e:
            log.warning(
                "FLOOD in ensure_join(JoinChannelRequest): url=%s seconds=%s",
                url, e.seconds
            )
            raise
        except UserAlreadyParticipantError:
            return "already", title_public, "public", (cid_public or None), None

    # ---- обробка винятків ----
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