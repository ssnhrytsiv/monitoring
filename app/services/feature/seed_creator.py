"""Seed creator: creates channels using a dedicated session (CREATOR_SESSION_NAME).
Independent from account pool and join_scheduler.

API (async):
 - ensure_client()
 - create_channel(title, kind) -> dict(meta)
 - send_links(target, links: List[str])

Behavior: built-in delays, floodwait handling, DB writes via seed_db.
"""
import asyncio
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional

from telethon import TelegramClient, errors
from telethon.tl.functions.channels import CreateChannelRequest
from telethon.tl.functions.messages import ExportChatInviteRequest

# ---- credentials: app.config -> app.settings -> ENV --------------------------
try:
    from app.config import API_ID as CFG_API_ID, API_HASH as CFG_API_HASH
except Exception:
    CFG_API_ID = None
    CFG_API_HASH = None

try:
    from app import settings  # SEED_* та імена сесій беремо звідси
except Exception:
    class _S: ...
    settings = _S()

def _get_api_credentials():
    api_id = CFG_API_ID
    api_hash = CFG_API_HASH
    if (api_id is None or api_hash is None) and hasattr(settings, "API_ID") and hasattr(settings, "API_HASH"):
        api_id = getattr(settings, "API_ID", None)
        api_hash = getattr(settings, "API_HASH", None)
    if api_id is None:
        api_id = os.getenv("API_ID")
    if api_hash is None:
        api_hash = os.getenv("API_HASH")
    if not api_id or not api_hash:
        raise RuntimeError(
            "seed_creator: API_ID/API_HASH not found. "
            "Expected in app.config or app.settings or env variables."
        )
    return int(api_id), str(api_hash)
# -----------------------------------------------------------------------------

from app.services.feature import seed_db

log = logging.getLogger("seed_creator")

CREATOR_SESSION_NAME = getattr(settings, "CREATOR_SESSION_NAME", "tg_session_3")
SEED_TARGET = getattr(settings, "SEED_TARGET", "me")  # дефолтно відправляємо у Saved Messages

# delays/limits
DELAY_BETWEEN_CREATES = float(getattr(settings, "SEED_DELAY_BETWEEN_CREATES", 7.0))
DELAY_BETWEEN_BATCHES = float(getattr(settings, "SEED_DELAY_BETWEEN_BATCHES", 20.0))
JITTER_CREATE_MIN, JITTER_CREATE_MAX = map(
    float, str(getattr(settings, "SEED_JITTER_CREATE", "0.3,1.2")).split(",")
)
MAX_PER_10_MIN = int(getattr(settings, "SEED_MAX_PER_10_MIN", 15))

client: Optional[TelegramClient] = None


async def ensure_client():
    """Гарантує піднятий клієнт на CREATOR_SESSION_NAME з правильними API_ID/HASH."""
    global client
    if client and client.is_connected():
        return client
    api_id, api_hash = _get_api_credentials()
    client = TelegramClient(CREATOR_SESSION_NAME, api_id, api_hash)
    await client.start()
    log.info("seed_creator: client started (%s)", CREATOR_SESSION_NAME)
    return client


async def _safe_sleep(base: float):
    jitter = random.uniform(JITTER_CREATE_MIN, JITTER_CREATE_MAX)
    await asyncio.sleep(base + jitter)


async def _handle_flood(e: Exception):
    sec = getattr(e, "seconds", None)
    if not sec:
        try:
            import re
            m = re.search(r"(\d+)\s*seconds", str(e))
            if m:
                sec = int(m.group(1))
        except Exception:
            sec = None
    if not sec:
        sec = 60
    hold = min(max(int(sec * 0.10), 10), 300)
    extra_j = random.uniform(0.05 * sec, 0.15 * sec)
    total = sec + hold + extra_j
    log.warning("seed_creator: FloodWait detected=%s, sleeping %s sec", sec, int(total))
    await asyncio.sleep(total)


async def _export_invite(c: TelegramClient, chat: Any, kind: str):
    """Експортує інвайт; для private_request/private_closed вмикає заявки (Join Requests).
    Сумісність із різними версіями Telethon: пробуємо кілька сигнатур.
    """
    request_needed = (kind in {"private_request", "private_closed"})
    try:
        # новіші версії Telethon
        return await c(ExportChatInviteRequest(chat, legacy=False, request_needed=request_needed))
    except TypeError:
        try:
            # інколи legacy не підтримується як kwarg, але request_needed є
            return await c(ExportChatInviteRequest(chat, request_needed=request_needed))
        except TypeError:
            # стара сигнатура без request_needed — впаде до звичайного інвайту (без заявок)
            if request_needed:
                log.warning("seed_creator: Telethon ExportChatInviteRequest without request_needed; consider upgrading Telethon.")
            return await c(ExportChatInviteRequest(chat))


async def create_channel(title: str, kind: str = "private_open") -> Dict[str, Any]:
    """Створює канал і повертає мета-дані.
       kind ∈ {public, private_open, private_closed, private_request}
    """
    c = await ensure_client()
    try:
        res = await c(CreateChannelRequest(title=title, about=title, megagroup=False))
    except Exception:
        log.exception("create_channel failed")
        raise

    chat = res.chats[0]
    peer_id = getattr(chat, "id", None)
    meta = {"peer_id": peer_id, "title": title, "kind": kind, "username": None, "invite_link": None}

    # невелика пауза між операціями
    await _safe_sleep(DELAY_BETWEEN_CREATES)

    try:
        # username НЕ ставимо — лише інвайт
        try:
            inv = await _export_invite(c, chat, kind)
            meta["invite_link"] = getattr(inv, "link", None)
        except Exception:
            meta["invite_link"] = None
    except errors.FloodWaitError as e:
        await _handle_flood(e)
    except Exception:
        log.exception("post-create adjustments failed")

    # запис у локальну seed-БД
    try:
        seed_db.record_channel(
            peer_id=str(meta["peer_id"]),
            title=title,
            kind=kind,
            username=meta.get("username"),
            invite_link=meta.get("invite_link"),
        )
    except Exception:
        log.exception("seed_db.record_channel failed")

    return meta


async def send_links(target: str, links: List[str]):
    """Надсилає список лінків у вказаний таргет; підтримує 'me' і fallback."""
    c = await ensure_client()
    target_norm = (target or "").strip().lower()
    if target_norm in {"me", "self", ""}:
        target_peer = "me"
    else:
        try:
            target_peer = await c.get_entity(target)
        except Exception:
            target_peer = target  # може бути peer_id/phone/посилання

    text = "\n".join(links)
    try:
        await c.send_message(target_peer, text)
        log.info("seed_creator: sent %d links to %s", len(links), target)
    except errors.ChatWriteForbiddenError:
        if target_peer != "me":
            log.warning("seed_creator: write forbidden to %r — retry to 'me' (Saved Messages)", target)
            try:
                await c.send_message("me", text)
                log.info("seed_creator: sent %d links to 'me' fallback", len(links))
            except Exception:
                log.exception("seed_creator: fallback to 'me' failed")
        else:
            log.exception("seed_creator: cannot write even to 'me'")
    except errors.FloodWaitError as e:
        await _handle_flood(e)
    except Exception:
        log.exception("failed to send links")


async def create_batch(count: int, mix: Optional[Dict[str, int]] = None, title_prefix: str = "SEED") -> List[Dict[str, Any]]:
    metas: List[Dict[str, Any]] = []
    per_10min = 0
    start_window = time.time()

    # Тепер підтримуємо три приватні типи + public (для сумісності)
    kinds = ["public", "private_open", "private_closed", "private_request"]
    plan: Dict[str, int]
    if mix:
        plan = dict(mix)
    else:
        plan = {}
        for _ in range(count):
            k = random.choice(kinds)
            plan[k] = plan.get(k, 0) + 1

    for k, kcount in plan.items():
        for _ in range(kcount):
            title = f"{title_prefix}_{k}_{int(time.time())}_{random.randint(100,999)}"
            try:
                meta = await create_channel(title, k)
                metas.append(meta)
            except Exception:
                log.exception("create_channel error for %s", title)

            per_10min += 1
            elapsed = time.time() - start_window
            if per_10min >= MAX_PER_10_MIN and elapsed < 600:
                wait = 600 - elapsed + random.uniform(5, 15)
                log.warning("seed_creator: reached MAX_PER_10_MIN; sleeping %s seconds", int(wait))
                await asyncio.sleep(wait)

    return metas