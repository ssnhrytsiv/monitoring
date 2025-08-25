# app/services/account_pool.py
from __future__ import annotations

import os
import time
import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional, List, Union

from telethon import TelegramClient
from telethon.tl import types
from telethon.tl.functions.channels import GetParticipantRequest

log = logging.getLogger("services.account_pool")

# ---------- env helpers ----------
def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v if v is not None else default

API_ID   = int(_env("API_ID", "0") or "0")
API_HASH = _env("API_HASH", "")
PRIMARY  = _env("SESSION") or _env("SESSION_NAME") or "tg_session"

def _parse_accounts_env() -> List[str]:
    """
    ACCOUNTS=tg_session_2,tg_session_3
    Прибираємо пробіли, дублікати та primary (SESSION/SESSION_NAME).
    """
    raw = _env("ACCOUNTS")
    names = [x.strip() for x in raw.split(",") if x.strip()]
    seen, out = set(), []
    for n in names:
        if n not in seen:
            out.append(n); seen.add(n)
    out = [n for n in out if n != PRIMARY]
    return out

POOL_SESSIONS = _parse_accounts_env()

# ---------- structures ----------
@dataclass
class ClientSlot:
    name: str
    client: TelegramClient
    next_ready: float = 0.0     # unix-ts, коли клієнт знову доступний
    busy: bool = False
    lock: asyncio.Lock = asyncio.Lock()

_POOL: List[ClientSlot] = []
_POOL_LOCK = asyncio.Lock()
_rr = 0  # round-robin індекс

# ---------- utils ----------
def session_name(client: TelegramClient) -> str:
    """
    Повертає ім'я сесії з пулу (для логів/статусів).
    Якщо не знайдено — пробуємо взяти з client.session.filename.
    """
    for s in _POOL:
        if s.client is client:
            return s.name
    try:
        fn = os.path.basename(client.session.filename)  # type: ignore[attr-defined]
        return fn
    except Exception:
        return "unknown.session"

def _find_slot(obj: Union[TelegramClient, ClientSlot]) -> Optional[ClientSlot]:
    if isinstance(obj, ClientSlot):
        return obj
    for s in _POOL:
        if s.client is obj:
            return s
    return None

def _set_ready_after(slot: ClientSlot, seconds: int) -> None:
    now = time.time()
    until = now + max(0, int(seconds))
    if until > slot.next_ready:
        slot.next_ready = until

def bump_cooldown(client: TelegramClient, seconds: int) -> None:
    """
    Короткий локальний кулдаун для клієнта (не FLOOD).
    """
    slot = _find_slot(client)
    if not slot: return
    _set_ready_after(slot, max(0, int(seconds)))
    log.debug("bump_cooldown: %s +%ss (ready @ %.0f)", slot.name, seconds, slot.next_ready)

def mark_flood(client: TelegramClient, seconds: int) -> None:
    """
    Позначає клієнт як "сплячий" через FLOOD_WAIT.
    """
    slot = _find_slot(client)
    if not slot: return
    _set_ready_after(slot, max(0, int(seconds)))
    log.warning("mark_flood: %s sleeps until %.0f (+%ss)", slot.name, slot.next_ready, seconds)

def mark_limit(client_or_slot: Union[TelegramClient, ClientSlot], days: int = 2) -> None:
    """
    Довгий "сон" при ліміті каналів (Too many channels).
    """
    slot = _find_slot(client_or_slot)
    if not slot: return
    seconds = int(days * 86400)
    _set_ready_after(slot, seconds)
    log.warning("mark_limit: %s sleeps until %.0f (+%ss, ~%d days)", slot.name, slot.next_ready, seconds, days)

async def _ensure_connected(slot: ClientSlot) -> None:
    """
    Переконуємось, що клієнт під'єднаний та авторизований.
    З ретраями від sqlite 'database is locked'.
    """
    retries = 5; delay = 0.6
    for attempt in range(retries):
        try:
            if not slot.client.is_connected():
                await slot.client.connect()
            if not await slot.client.is_user_authorized():
                await slot.client.start()
            return
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower() and attempt < retries-1:
                wait = delay * (attempt + 1)
                log.warning("sqlite locked for %s; retry in %.1fs", slot.name, wait)
                await asyncio.sleep(wait); continue
            raise
        except Exception as e:
            if attempt < retries-1:
                wait = delay * (attempt + 1)
                log.warning("connect failed for %s: %s; retry in %.1fs", slot.name, e, wait)
                await asyncio.sleep(wait); continue
            raise

async def start_pool() -> None:
    """
    Створює та піднімає клієнти для ACCOUNTS.
    PRIMARY (SESSION) не додаємо у пул.
    """
    global _POOL
    if not POOL_SESSIONS:
        log.info("Accounts pool is empty (ACCOUNTS not set)."); _POOL = []; return
    if not API_ID or not API_HASH:
        raise RuntimeError("API_ID/API_HASH must be set in .env for pool")

    pool: List[ClientSlot] = []
    for sess in POOL_SESSIONS:
        client = TelegramClient(sess, API_ID, API_HASH)
        slot = ClientSlot(name=sess, client=client)
        await _ensure_connected(slot)
        pool.append(slot)
        log.info("pool client ready: %s", sess)
    _POOL = pool
    log.info("account_pool started: %d clients", len(_POOL))

async def stop_pool() -> None:
    for s in _POOL:
        try: await s.client.disconnect()
        except Exception: pass
    _POOL.clear(); log.info("account_pool stopped")

def iter_pool_clients() -> List[ClientSlot]:
    """
    Повертає знімок слотів пулу (read-only).
    """
    return list(_POOL)

@asynccontextmanager
async def _lease_ctx(slot: ClientSlot):
    """
    Контекст для позначки busy під час короткої «оренди» клієнта.
    """
    slot.busy = True
    try: yield slot.client
    finally: slot.busy = False

async def lease() -> Optional[asyncio.AbstractAsyncContextManager]:
    """
    Видає async context manager з "найближчим" готовим клієнтом.
    Повертає None, якщо наразі *усі* сплять або зайняті.
    """
    if not _POOL: return None
    now = time.time()
    async with _POOL_LOCK:
        n = len(_POOL); global _rr
        for k in range(n):
            idx = (_rr + k) % n
            s = _POOL[idx]
            if s.busy: continue
            if s.next_ready > now: continue
            _rr = (idx + 1) % n
            return _lease_ctx(s)
    return None

async def is_already_subscribed(url: str) -> Optional[str]:
    """
    Перевіряє, чи хоча б один акаунт з пулу вже підписаний на канал (за url).
    Повертає session_name клієнта, якщо знайдено, інакше None.
    """
    if not _POOL: return None
    for slot in _POOL:
        try:
            client = slot.client
            entity = await client.get_entity(url)
            res = await client(GetParticipantRequest(entity, 'me'))
            if hasattr(res, "participant") and isinstance(res.participant, types.ChannelParticipant):
                return session_name(client)
        except Exception:
            continue
    return None