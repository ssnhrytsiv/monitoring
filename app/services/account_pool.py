from __future__ import annotations

import os
import time
import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional, List, Union

from telethon import TelegramClient, errors
from telethon.tl import types, functions
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.network.connection import ConnectionTcpAbridged

log = logging.getLogger("services.account_pool")

# ---------- env helpers ----------
def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v if v is not None else default

API_ID   = int(_env("API_ID", "0") or "0")
API_HASH = _env("API_HASH", "")

# Людські імена акаунтів (для логів/діагностики). Оновлюється на старті пулу через get_me.
SESSION_DISPLAY: dict[str, str] = {
    "tg_session": "Покупаю Рекламу (@ludoman_buying)",
    "tg_session_2": "Владислав (@leorandor)",
    "tg_session_3": "Дон (@doncorleon2309)",
    "tg_session_4": "D",
    "tg_session_5": "М М (@kurasow)",
}

def _parse_accounts_env() -> List[str]:
    """
    ACCOUNTS=tg_session_2,tg_session_3
    Прибираємо пробіли й дублікати.
    """
    raw = _env("ACCOUNTS")
    names = [x.strip() for x in raw.split(",") if x.strip()]
    seen, out = set(), []
    for n in names:
        if n not in seen:
            out.append(n)
            seen.add(n)
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
    human_display: Optional[str] = None

_POOL: List[ClientSlot] = []
_POOL_LOCK = asyncio.Lock()
_rr = 0  # round-robin індекс
_limits_checker_task: Optional[asyncio.Task] = None
_health_checker_task: Optional[asyncio.Task] = None

# ---------- utils ----------
def _normalize_session_name(name: str) -> str:
    return name[:-8] if name.endswith(".session") else name

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

def session_display(name: str) -> str:
    base = _normalize_session_name(name)
    return SESSION_DISPLAY.get(base) or SESSION_DISPLAY.get(name) or name

def _set_session_display(name: str, display: str) -> None:
    try:
        if display:
            SESSION_DISPLAY[_normalize_session_name(name)] = display
            SESSION_DISPLAY[name] = display
    except Exception:
        pass

def _find_slot(obj: Union[TelegramClient, ClientSlot]) -> Optional[ClientSlot]:
    if isinstance(obj, ClientSlot):
        return obj
    for s in _POOL:
        if s.client is obj:
            return s
    return None

def find_slot_by_session_name(name: str) -> Optional[ClientSlot]:
    """
    Знаходить слот у пулі за exact-іменем сесії (як у ACCOUNTS).
    """
    for s in _POOL:
        if s.name == name:
            return s
    return None

def get_client_by_session_name(name: str) -> Optional[TelegramClient]:
    """
    Повертає TelegramClient із пулу за ім’ям сесії, або None якщо не знайдено/не в пулі.
    """
    slot = find_slot_by_session_name(name)
    return slot.client if slot else None

def list_session_names() -> List[str]:
    """
    Знімок імен усіх сесій у пулі (для діагностики/логів).
    """
    return [s.name for s in _POOL]

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
    if not slot:
        return
    _set_ready_after(slot, max(0, int(seconds)))
    log.debug("bump_cooldown: %s +%ss (ready @ %.0f)", slot.name, seconds, slot.next_ready)

def mark_flood(client: TelegramClient, seconds: int) -> None:
    """
    Позначає клієнт як "сплячий" через FLOOD_WAIT.
    """
    slot = _find_slot(client)
    if not slot:
        return
    _set_ready_after(slot, max(0, int(seconds)))
    log.warning("mark_flood: %s sleeps until %.0f (+%ss)", slot.name, slot.next_ready, seconds)

def mark_limit(client_or_slot: Union[TelegramClient, ClientSlot], days: int = 2) -> None:
    """
    Довгий "сон" при ліміті каналів (Too many channels).
    """
    slot = _find_slot(client_or_slot)
    if not slot:
        return
    seconds = int(days * 86400)
    _set_ready_after(slot, seconds)
    log.warning("mark_limit: %s sleeps until %.0f (+%ss, ~%d days)", slot.name, slot.next_ready, seconds, days)


async def _count_memberships(slot: ClientSlot) -> int:
    """
    Рахує кількість каналів/супергруп для сесії.
    """
    total = 0
    try:
        async for dlg in slot.client.iter_dialogs():
            ent = dlg.entity
            if isinstance(ent, types.Channel):
                total += 1
    except Exception as e:
        log.warning("count_memberships failed for %s: %s", slot.name, e)
    return total


async def _check_pool_limits(reason: str = "periodic") -> None:
    """
    Якщо total > 498 — ставимо слот у sleep на добу.
    """
    if not _POOL:
        return
    for slot in _POOL:
        try:
            total = await _count_memberships(slot)
            if total > 498:
                mark_limit(slot, days=1)
                log.warning(
                    "limit_check: %s marked sleep (channels=%d) reason=%s",
                    slot.name,
                    total,
                    reason,
                )
            else:
                log.debug("limit_check: %s ok (channels=%d) reason=%s", slot.name, total, reason)
        except Exception as e:
            log.warning("limit_check failed for %s: %s", slot.name, e)


async def _limits_checker_loop() -> None:
    while True:
        await _check_pool_limits(reason="daily")
        await asyncio.sleep(86400)


async def _health_checker_loop() -> None:
    """
    Періодично перевіряє стан сесій у пулі:
    - якщо next_ready в минулому і клієнт відвалився – пробуємо перепідключити
    - якщо клієнт не авторизований – стартуємо
    Робимо це обережно, щоб не пересікатися з робочими операціями (busy/next_ready).
    """
    while True:
        now = time.time()
        for slot in list(_POOL):
            if slot.busy:
                continue
            if slot.next_ready > now:
                continue
            try:
                # Коротка перевірка конекту; якщо ні – перепідключаємо
                if not slot.client.is_connected():
                    log.debug("health: reconnecting %s", slot.name)
                    await _ensure_connected(slot)
                    continue
                # Переконуємось, що сесія авторизована
                if not await slot.client.is_user_authorized():
                    log.debug("health: re-auth %s", slot.name)
                    await slot.client.start()
            except Exception as e:
                log.debug("health: check failed for %s: %s", slot.name, e)
        await asyncio.sleep(60)

async def _ensure_connected(slot: ClientSlot) -> None:
    """
    Переконуємось, що клієнт під'єднаний та авторизований.
    З ретраями від sqlite 'database is locked'.
    """
    retries = 5
    delay = 0.6
    connected = False
    for attempt in range(retries):
        try:
            if not slot.client.is_connected():
                await slot.client.connect()
            if not await slot.client.is_user_authorized():
                await slot.client.start()
            connected = True
            break
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower() and attempt < retries - 1:
                wait = delay * (attempt + 1)
                log.warning("sqlite locked for %s; retry in %.1fs", slot.name, wait)
                await asyncio.sleep(wait)
                continue
            raise
        except Exception as e:
            if attempt < retries - 1:
                wait = delay * (attempt + 1)
                log.warning("connect failed for %s: %s; retry in %.1fs", slot.name, e, wait)
                await asyncio.sleep(wait)
                continue
            raise

    if not connected:
        return

    # Спробуємо один раз підтягнути людське ім'я акаунта (first/last/username)
    try:
        # Спершу беремо з мапи, якщо вона є
        disp_map = SESSION_DISPLAY.get(slot.name)
        if disp_map:
            slot.human_display = disp_map
        me = await slot.client.get_me()
        if me:
            first = getattr(me, "first_name", None) or ""
            last = getattr(me, "last_name", None) or ""
            username = getattr(me, "username", None) or ""
            parts = [p for p in (first, last) if p]
            disp = " ".join(parts).strip()
            if not disp and username:
                disp = f"@{username}"
            if disp:
                slot.human_display = disp
        if slot.human_display:
            _set_session_display(slot.name, slot.human_display)
            try:
                setattr(slot.client, "_human_display", slot.human_display)
            except Exception:
                pass
    except Exception as e:
        log.debug("get_me failed for %s: %s", slot.name, e)

async def start_pool() -> None:
    """
    Створює та піднімає клієнти для ACCOUNTS.
    """
    global _POOL, _limits_checker_task
    if not POOL_SESSIONS:
        log.info("Accounts pool is empty (ACCOUNTS not set).")
        _POOL = []
        return
    if not API_ID or not API_HASH:
        raise RuntimeError("API_ID/API_HASH must be set in .env for pool")

    pool: List[ClientSlot] = []
    for sess in POOL_SESSIONS:
        client = TelegramClient(sess, API_ID, API_HASH,connection=ConnectionTcpAbridged)
        slot = ClientSlot(name=sess, client=client, human_display=SESSION_DISPLAY.get(sess))
        await _ensure_connected(slot)
        pool.append(slot)
        log.info("pool client ready: %s (%s)", sess, slot.human_display or sess)
    _POOL = pool
    log.info("account_pool started: %d clients", len(_POOL))
    # Перевірка лімітів на старті
    await _check_pool_limits(reason="startup")
    # Плановий щоденний чекер
    if _limits_checker_task is None:
        _limits_checker_task = asyncio.create_task(_limits_checker_loop())
    # Періодичний health-check
    global _health_checker_task
    if _health_checker_task is None:
        _health_checker_task = asyncio.create_task(_health_checker_loop())

async def stop_pool() -> None:
    global _limits_checker_task, _health_checker_task
    if _limits_checker_task:
        _limits_checker_task.cancel()
        try:
            await _limits_checker_task
        except Exception:
            pass
        _limits_checker_task = None
    if _health_checker_task:
        _health_checker_task.cancel()
        try:
            await _health_checker_task
        except Exception:
            pass
        _health_checker_task = None
    for s in _POOL:
        try:
            await s.client.disconnect()
        except Exception:
            pass
    _POOL.clear()
    log.info("account_pool stopped")

def iter_pool_clients() -> List[ClientSlot]:
    """
    Повертає знімок слотів пулу (read-only), без фільтрації стану.
    Використовуйте iter_ready_pool_clients() там, де потрібно уникати FLOOD/cooldown/busy.
    """
    return list(_POOL)

def iter_ready_pool_clients() -> List[ClientSlot]:
    """
    Повертає лише ті слоти, що готові до використання прямо зараз:
      - не busy
      - next_ready <= now
    """
    now = time.time()
    return [s for s in _POOL if (not s.busy) and (s.next_ready <= now)]

@asynccontextmanager
async def _lease_ctx(slot: ClientSlot):
    """
    Контекст для позначки busy під час короткої «оренди» клієнта.
    """
    slot.busy = True
    try:
        yield slot.client
    finally:
        slot.busy = False

async def lease() -> Optional[asyncio.AbstractAsyncContextManager]:
    """
    Видає async context manager з "найближчим" готовим клієнтом.
    Повертає None, якщо наразі *усі* сплять або зайняті.
    """
    if not _POOL:
        return None
    now = time.time()
    async with _POOL_LOCK:
        n = len(_POOL)
        global _rr
        for k in range(n):
            idx = (_rr + k) % n
            s = _POOL[idx]
            if s.busy:
                continue
            if s.next_ready > now:
                continue
            _rr = (idx + 1) % n
            return _lease_ctx(s)
    return None

async def is_already_subscribed(url: str) -> Optional[str]:
    """
    Перевіряє, чи хоча б один акаунт з пулу вже підписаний на канал (за url).
    Повертає session_name клієнта, якщо знайдено, інакше None.
    """
    if not _POOL:
        return None
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


async def leave_channels(session_name: str, channel_ids: List[int]) -> dict:
    """
    Відписує пуловий клієнт від переданих channel_ids.
    Повертає лічильники успішних/помилкових виходів.
    """
    slot = find_slot_by_session_name(session_name)
    if not slot:
        return {"session": session_name, "left": 0, "errors": len(channel_ids), "reason": "session_not_in_pool"}

    client = slot.client
    left, errors_cnt = 0, 0
    for cid in channel_ids:
        try:
            ent = await client.get_entity(cid)
            await client(functions.channels.LeaveChannelRequest(ent))
            left += 1
            bump_cooldown(client, 2)
        except (errors.UserNotParticipantError, errors.ChannelPrivateError):
            errors_cnt += 1
        except Exception as e:
            errors_cnt += 1
            log.warning("leave_channels: %s failed for cid=%s: %s", slot.name, cid, e)
    return {"session": session_name, "left": left, "errors": errors_cnt}
