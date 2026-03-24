from __future__ import annotations

import os
import time
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Dict, Optional, List, Set, Tuple, Union

from telethon import TelegramClient, errors
from telethon.tl import types, functions
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.network.connection import ConnectionTcpAbridged

from app.DAL import channel_subscription_audit_operations
from app.utils.time_utils import MOSCOW_TIME_FORMAT, moscow_now

log = logging.getLogger("services.account_pool")

# ---------- env helpers ----------
def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v if v is not None else default

API_ID   = int(_env("API_ID", "0") or "0")
API_HASH = _env("API_HASH", "")
PRIMARY  = _env("SESSION") or _env("SESSION_NAME") or "tg_session"

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
SUBSCRIPTION_AUDIT_REFRESH_MIN_INTERVAL_SECONDS = max(
    0,
    int(_env("SUBSCRIPTION_AUDIT_REFRESH_MIN_INTERVAL_SECONDS", "90") or "90"),
)
SUBSCRIPTION_AUDIT_REFRESH_ON_STARTUP = _env(
    "SUBSCRIPTION_AUDIT_REFRESH_ON_STARTUP",
    "0",
).strip().lower() not in ("0", "false", "no", "off", "")
SUBSCRIPTION_AUDIT_DAILY_HOUR_MSK = min(
    23,
    max(0, int(_env("SUBSCRIPTION_AUDIT_DAILY_HOUR_MSK", "4") or "4")),
)
SUBSCRIPTION_AUDIT_DAILY_MINUTE_MSK = min(
    59,
    max(0, int(_env("SUBSCRIPTION_AUDIT_DAILY_MINUTE_MSK", "0") or "0")),
)

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
_subscription_audit_refresh_lock = asyncio.Lock()
_subscription_audit_last_started_at_epoch_seconds: float = 0.0

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
    (PRIMARY тут недоступний, він не є частиною пулу.)
    """
    slot = find_slot_by_session_name(name)
    return slot.client if slot else None

def list_session_names() -> List[str]:
    """
    Знімок імен усіх сесій у пулі (для діагностики/логів).
    """
    return [s.name for s in _POOL]


def is_subscription_audit_refresh_running() -> bool:
    return _subscription_audit_refresh_lock.locked()


def get_subscription_audit_refresh_seconds_until_next_allowed() -> int:
    if SUBSCRIPTION_AUDIT_REFRESH_MIN_INTERVAL_SECONDS <= 0:
        return 0
    seconds_since_last_refresh_start = int(
        time.time() - _subscription_audit_last_started_at_epoch_seconds
    )
    remaining_seconds = (
        SUBSCRIPTION_AUDIT_REFRESH_MIN_INTERVAL_SECONDS
        - seconds_since_last_refresh_start
    )
    return max(0, int(remaining_seconds))

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


async def _collect_subscribed_channel_identifier_set(slot: ClientSlot) -> set[int]:
    """
    Збирає channel_id каналів/супергруп, на які підписана сесія.
    """
    subscribed_channel_identifier_set: set[int] = set()
    try:
        async for dlg in slot.client.iter_dialogs():
            ent = dlg.entity
            if isinstance(ent, types.Channel):
                subscribed_channel_identifier_set.add(int(ent.id))
    except Exception as e:
        log.warning("collect_subscribed_channel_identifier_set failed for %s: %s", slot.name, e)
        raise
    return subscribed_channel_identifier_set


async def _count_memberships(slot: ClientSlot) -> int:
    """
    Рахує кількість каналів/супергруп для сесії.
    """
    subscribed_channel_identifier_set = await _collect_subscribed_channel_identifier_set(slot)
    return len(subscribed_channel_identifier_set)


def _build_union_channel_identifier_set(
    session_channel_identifier_map: Dict[str, Set[int]],
) -> Set[int]:
    union_channel_identifier_set: Set[int] = set()
    for channel_identifier_set in session_channel_identifier_map.values():
        union_channel_identifier_set.update(channel_identifier_set)
    return union_channel_identifier_set


async def _collect_pool_session_channel_identifier_map(
    *,
    skip_busy_or_locked_slot: bool,
) -> Tuple[Dict[str, Set[int]], List[str]]:
    session_channel_identifier_map: Dict[str, Set[int]] = {}
    failed_session_name_list: List[str] = []
    for slot in _POOL:
        if skip_busy_or_locked_slot and (slot.busy or slot.lock.locked()):
            failed_session_name_list.append(slot.name)
            continue
        try:
            if skip_busy_or_locked_slot:
                async with slot.lock:
                    subscribed_channel_identifier_set = (
                        await _collect_subscribed_channel_identifier_set(slot)
                    )
            else:
                subscribed_channel_identifier_set = (
                    await _collect_subscribed_channel_identifier_set(slot)
                )
            session_channel_identifier_map[slot.name] = subscribed_channel_identifier_set
        except Exception as error:
            failed_session_name_list.append(slot.name)
            log.warning(
                "subscription audit scan failed for session=%s reason=%s",
                slot.name,
                error,
            )
    return session_channel_identifier_map, failed_session_name_list


async def _check_pool_limits(reason: str = "periodic") -> None:
    """
    Якщо total > 498 — ставимо слот у sleep на добу.
    """
    if not _POOL:
        try:
            channel_subscription_audit_operations.refresh_channel_subscription_audit_snapshot_from_session_map(
                session_channel_identifier_map={},
                failed_session_name_list=["pool_empty"],
                audit_reason=reason,
            )
        except Exception as e:
            log.warning("subscription_audit refresh failed with empty pool: %s", e)
        return
    (
        session_channel_identifier_map,
        failed_session_name_list,
    ) = await _collect_pool_session_channel_identifier_map(
        skip_busy_or_locked_slot=False,
    )
    for slot in _POOL:
        if slot.name in failed_session_name_list:
            continue
        subscribed_channel_identifier_set = session_channel_identifier_map.get(
            slot.name, set()
        )
        total = len(subscribed_channel_identifier_set)
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
    try:
        channel_subscription_audit_operations.refresh_channel_subscription_audit_snapshot_from_session_map(
            session_channel_identifier_map=session_channel_identifier_map,
            failed_session_name_list=failed_session_name_list,
            audit_reason=reason,
        )
    except Exception as e:
        log.warning("subscription_audit refresh failed reason=%s: %s", reason, e)


async def refresh_channel_subscription_audit_snapshot_now(
    audit_reason: str = "manual",
) -> Dict[str, object]:
    if _subscription_audit_refresh_lock.locked():
        return {
            "session_count": len(_POOL),
            "failed_session_name_list": [],
            "subscribed_channel_count": 0,
            "is_skipped_due_to_running_refresh": True,
            "is_skipped_due_to_cooldown": False,
            "seconds_until_next_allowed": get_subscription_audit_refresh_seconds_until_next_allowed(),
        }

    seconds_until_next_allowed = get_subscription_audit_refresh_seconds_until_next_allowed()
    if seconds_until_next_allowed > 0:
        return {
            "session_count": len(_POOL),
            "failed_session_name_list": [],
            "subscribed_channel_count": 0,
            "is_skipped_due_to_running_refresh": False,
            "is_skipped_due_to_cooldown": True,
            "seconds_until_next_allowed": seconds_until_next_allowed,
        }

    async with _subscription_audit_refresh_lock:
        global _subscription_audit_last_started_at_epoch_seconds
        _subscription_audit_last_started_at_epoch_seconds = time.time()

        if not _POOL:
            channel_subscription_audit_operations.refresh_channel_subscription_audit_snapshot_from_session_map(
                session_channel_identifier_map={},
                failed_session_name_list=["pool_empty"],
                audit_reason=audit_reason,
            )
            return {
                "session_count": 0,
                "failed_session_name_list": ["pool_empty"],
                "subscribed_channel_count": 0,
                "is_skipped_due_to_running_refresh": False,
                "is_skipped_due_to_cooldown": False,
                "seconds_until_next_allowed": get_subscription_audit_refresh_seconds_until_next_allowed(),
            }

        (
            session_channel_identifier_map,
            failed_session_name_list,
        ) = await _collect_pool_session_channel_identifier_map(
            skip_busy_or_locked_slot=True,
        )
        all_subscribed_channel_identifier_set = _build_union_channel_identifier_set(
            session_channel_identifier_map
        )

        channel_subscription_audit_operations.refresh_channel_subscription_audit_snapshot_from_session_map(
            session_channel_identifier_map=session_channel_identifier_map,
            failed_session_name_list=failed_session_name_list,
            audit_reason=audit_reason,
        )
        return {
            "session_count": len(_POOL),
            "failed_session_name_list": failed_session_name_list,
            "subscribed_channel_count": len(all_subscribed_channel_identifier_set),
            "is_skipped_due_to_running_refresh": False,
            "is_skipped_due_to_cooldown": False,
            "seconds_until_next_allowed": get_subscription_audit_refresh_seconds_until_next_allowed(),
        }


def _get_next_subscription_audit_run_at_msk(
    now_value: datetime | None = None,
) -> datetime:
    current_moscow_datetime = now_value or moscow_now()
    next_run_datetime = current_moscow_datetime.replace(
        hour=SUBSCRIPTION_AUDIT_DAILY_HOUR_MSK,
        minute=SUBSCRIPTION_AUDIT_DAILY_MINUTE_MSK,
        second=0,
        microsecond=0,
    )
    if next_run_datetime <= current_moscow_datetime:
        next_run_datetime += timedelta(days=1)
    return next_run_datetime


def _get_seconds_until_next_subscription_audit_run(
    now_value: datetime | None = None,
) -> float:
    current_moscow_datetime = now_value or moscow_now()
    next_run_datetime = _get_next_subscription_audit_run_at_msk(current_moscow_datetime)
    seconds_until_next_run = (
        next_run_datetime - current_moscow_datetime
    ).total_seconds()
    return max(0.0, float(seconds_until_next_run))


async def _limits_checker_loop() -> None:
    while True:
        next_run_datetime = _get_next_subscription_audit_run_at_msk()
        seconds_until_next_run = _get_seconds_until_next_subscription_audit_run()
        log.info(
            "subscription audit scheduled next run at %s (in %.0fs)",
            next_run_datetime.strftime(MOSCOW_TIME_FORMAT),
            seconds_until_next_run,
        )
        await asyncio.sleep(seconds_until_next_run)
        await _check_pool_limits(reason="daily_0400_msk")


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
    retries = 5; delay = 0.6
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
    PRIMARY (SESSION) не додаємо у пул.
    """
    global _POOL, _limits_checker_task
    if not POOL_SESSIONS:
        log.info("Accounts pool is empty (ACCOUNTS not set)."); _POOL = []; return
    if not API_ID or not API_HASH:
        raise RuntimeError("API_ID/API_HASH must be set in .env for pool")
    if PRIMARY in POOL_SESSIONS:
        log.warning("PRIMARY session %s присутня в ACCOUNTS — це може викликати блокування .session. Рекомендується використовувати окремі файли сесій для пулу.", PRIMARY)

    pool: List[ClientSlot] = []
    for sess in POOL_SESSIONS:
        client = TelegramClient(sess, API_ID, API_HASH,connection=ConnectionTcpAbridged)
        slot = ClientSlot(name=sess, client=client, human_display=SESSION_DISPLAY.get(sess))
        await _ensure_connected(slot)
        pool.append(slot)
        log.info("pool client ready: %s (%s)", sess, slot.human_display or sess)
    _POOL = pool
    log.info("account_pool started: %d clients", len(_POOL))
    if SUBSCRIPTION_AUDIT_REFRESH_ON_STARTUP:
        await _check_pool_limits(reason="startup")
    else:
        log.info("subscription audit on startup is disabled")
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
        try: await s.client.disconnect()
        except Exception: pass
    _POOL.clear(); log.info("account_pool stopped")

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


async def leave_channels(session_name: str, channel_ids: List[int]) -> dict:
    """
    Відписує пуловий клієнт від переданих channel_ids.
    Повертає лічильники успішних/пропущених/помилкових виходів.
    """
    slot = find_slot_by_session_name(session_name)
    if not slot:
        return {
            "session": session_name,
            "left": 0,
            "skipped": len(channel_ids),
            "errors": 0,
            "reason": "session_not_in_pool",
        }

    client = slot.client
    left, skipped_cnt, errors_cnt = 0, 0, 0
    for cid in channel_ids:
        try:
            ent = await client.get_entity(cid)
            await client(functions.channels.LeaveChannelRequest(ent))
            left += 1
            bump_cooldown(client, 2)
        except (errors.UserNotParticipantError, errors.ChannelPrivateError):
            skipped_cnt += 1
        except Exception as e:
            errors_cnt += 1
            log.warning("leave_channels: %s failed for cid=%s: %s", slot.name, cid, e)
    return {"session": session_name, "left": left, "skipped": skipped_cnt, "errors": errors_cnt}
