from __future__ import annotations

import asyncio
import math
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from app.logging_json import get_logger
from app.services.account_pool import session_name
from app.services.joiner import ensure_join
from app.services import channel_maps
from app import settings as _S  # беремо з settings, але нижче маємо безпечні дефолти

log = get_logger("join_scheduler")

# -----------------------------------------------------------------------------
# Конфіги (із settings.py або дефолти)
# -----------------------------------------------------------------------------
MONITOR_LINKS_SHADOW: bool = bool(getattr(_S, "MONITOR_LINKS_SHADOW", False))

JOIN_LIMIT_WINDOW: int = int(getattr(_S, "JOIN_LIMIT_WINDOW", 600))  # 10 хв
JOIN_PUBLIC_CAP: int = int(getattr(_S, "JOIN_PUBLIC_CAP", 20))       # стартова місткість public
JOIN_PRIVATE_CAP: int = int(getattr(_S, "JOIN_PRIVATE_CAP", 8))      # стартова місткість private
JOIN_BURST: int = int(getattr(_S, "JOIN_BURST", 2))                  # стартовий запас токенів

JOIN_PUBLIC_MIN: int = int(getattr(_S, "JOIN_PUBLIC_MIN", 6))
JOIN_PUBLIC_MAX: int = int(getattr(_S, "JOIN_PUBLIC_MAX", 30))
JOIN_PRIVATE_MIN: int = int(getattr(_S, "JOIN_PRIVATE_MIN", 3))
JOIN_PRIVATE_MAX: int = int(getattr(_S, "JOIN_PRIVATE_MAX", 20))     # <-- як просив: MAX=20

JOIN_GOOD_STREAK: int = int(getattr(_S, "JOIN_GOOD_STREAK", 5))

# Додатковий hold після FloodWait
JOIN_AFTER_FLOOD_HOLD_PCT: float = float(getattr(_S, "JOIN_AFTER_FLOOD_HOLD_PCT", 0.10))  # 10% від W
JOIN_AFTER_FLOOD_HOLD_MIN: int = int(getattr(_S, "JOIN_AFTER_FLOOD_HOLD_MIN", 10))
JOIN_AFTER_FLOOD_HOLD_MAX: int = int(getattr(_S, "JOIN_AFTER_FLOOD_HOLD_MAX", 300))

# Джитери
JITTER_TOKEN_WAIT_RANGE: Tuple[float, float] = (0.2, 1.3)   # сек при очікуванні токена / cooldown
JITTER_IMMEDIATE_RANGE: Tuple[float, float] = (0.0, 0.25)   # сек коли токен є відразу
JITTER_AFTER_COOLDOWN_PCT: Tuple[float, float] = (0.05, 0.15)  # частка від FloodWait W


# -----------------------------------------------------------------------------
# Внутрішні структури
# -----------------------------------------------------------------------------
class TokenBucket:
    """Простий токен-бакет із лінійним поповненням."""
    __slots__ = ("cap", "tokens", "rate", "last_refill")

    def __init__(self, cap: int, window_sec: int, init_tokens: float):
        self.cap = max(1, int(cap))
        self.tokens = float(min(cap, max(0.0, init_tokens)))
        self.rate = float(cap) / float(max(1, window_sec))  # токенів/сек
        self.last_refill = time.monotonic()

    def update_cap(self, new_cap: int, window_sec: int):
        self.cap = max(1, int(new_cap))
        self.rate = float(self.cap) / float(max(1, window_sec))
        # не перезатираємо tokens, але тримаємо в межах нової місткості
        self.tokens = min(self.tokens, float(self.cap))

    def _refill(self):
        now = time.monotonic()
        dt = now - self.last_refill
        if dt <= 0:
            return
        self.tokens = min(float(self.cap), self.tokens + self.rate * dt)
        self.last_refill = now

    def need_wait_seconds_for_one(self) -> float:
        """Скільки потрібно чекати, щоб назбирати 1 токен (0 якщо вже є)."""
        self._refill()
        if self.tokens >= 1.0:
            return 0.0
        deficit = 1.0 - self.tokens
        return deficit / self.rate if self.rate > 0 else 1e6

    def consume_one(self):
        self._refill()
        if self.tokens < 1.0:
            # Викликати після очікування, тут просто коректність
            self.tokens = 0.0
        else:
            self.tokens -= 1.0


class SessionState:
    __slots__ = (
        "alias",
        "public_bucket",
        "private_bucket",
        "cooldown_until",
        "good_public",
        "good_private",
        "last_flood_w",
    )

    def __init__(self, alias: str):
        self.alias = alias
        self.public_bucket = TokenBucket(JOIN_PUBLIC_CAP, JOIN_LIMIT_WINDOW, JOIN_BURST)
        self.private_bucket = TokenBucket(JOIN_PRIVATE_CAP, JOIN_LIMIT_WINDOW, JOIN_BURST)
        self.cooldown_until = 0.0  # мон.час до якого спати
        self.good_public = 0
        self.good_private = 0
        self.last_flood_w = 0.0


# Глобальні структури воркера
_SESSIONS: List[Any] = []
_QUEUES: List[asyncio.Queue] = []
_STATE: List[SessionState] = []
_ALIAS_TO_IDX: Dict[str, int] = {}
_STARTED = False


# -----------------------------------------------------------------------------
# Допоміжні утиліти
# -----------------------------------------------------------------------------
def _pick_idx_by_alias(alias: Optional[str]) -> Optional[int]:
    if not alias:
        return None
    return _ALIAS_TO_IDX.get(alias)


def _pick_idx_hash(channel_id: int) -> int:
    n = max(1, len(_SESSIONS))
    return abs(int(channel_id)) % n


def _classify_kind(invite_or_username: Optional[str]) -> str:
    # PRIVATE, якщо інвайт вигляду +hash
    if invite_or_username and isinstance(invite_or_username, str) and invite_or_username.startswith("+"):
        return "private"
    return "public"


def _rand_uniform(a: float, b: float) -> float:
    return random.uniform(a, b)


def _now() -> float:
    return time.monotonic()


def _clamp(v: float, vmin: float, vmax: float) -> float:
    return max(vmin, min(v, vmax))


def _parse_flood_wait_seconds(err) -> Optional[int]:
    """
    Пробуємо витягнути FloodWait W (секунди) з помилки.
    Підтримуємо обидва варіанти: err як Exception або як текст.
    """
    # Прямий атрибут, якщо exception від Telethon
    sec = getattr(err, "seconds", None)
    if isinstance(sec, int) and sec > 0:
        return sec

    # Пробуємо рядок
    s = str(err) if err is not None else ""
    # Поширені формати:
    # "A wait of 123 seconds is required (caused by ...)"
    # "FloodWaitError: (123 seconds)"
    import re
    m = re.search(r"(\d+)\s*seconds", s)
    if m:
        try:
            w = int(m.group(1))
            return w if w > 0 else None
        except Exception:
            return None
    return None


# -----------------------------------------------------------------------------
# Rate control (очікування токена + cooldown)
# -----------------------------------------------------------------------------
async def _rate_wait_session(idx: int, kind: str):
    """
    Чекає завершення cooldown (якщо є), і чекає токен з відповідного бакета.
    Логує очікування (час, капасіті, токени тощо).
    """
    st = _STATE[idx]
    after_cooldown = 0

    # Спершу перевіряємо cooldown
    now = _now()
    if st.cooldown_until > now:
        sleep_s = (st.cooldown_until - now)
        # невеликий джитер, щоб не вистрілювати синхронно
        sleep_s += _rand_uniform(*JITTER_TOKEN_WAIT_RANGE)
        log.debug(
            "B-6 join.rate.wait",
            extra={
                "subsys": "join_scheduler",
                "step": "B-6",
                "session": st.alias,
                "kind": kind,
                "reason": "cooldown",
                "wait_ms": int(sleep_s * 1000),
                "cooldown_until_ts": st.cooldown_until,
            },
        )
        await asyncio.sleep(sleep_s)
        after_cooldown = 1

    # Вибираємо бакет
    bucket = st.public_bucket if kind == "public" else st.private_bucket
    need_wait = bucket.need_wait_seconds_for_one()

    # Коли токен є одразу — все одно додаємо невеличкий джитер (0..250мс)
    if need_wait <= 0:
        jitter = _rand_uniform(*JITTER_IMMEDIATE_RANGE)
        if jitter > 0:
            log.debug(
                "B-6 join.rate.wait",
                extra={
                    "subsys": "join_scheduler",
                    "step": "B-6",
                    "session": st.alias,
                    "kind": kind,
                    "reason": "immediate_jitter",
                    "wait_ms": int(jitter * 1000),
                    "cap": bucket.cap,
                    "tokens_left": round(bucket.tokens, 2),
                    "after_cooldown": after_cooldown,
                },
            )
            await asyncio.sleep(jitter)
        bucket.consume_one()
        return

    # Якщо треба чекати доки з’явиться 1 токен — додаємо невеликий джитер
    jitter = _rand_uniform(*JITTER_TOKEN_WAIT_RANGE)
    total_wait = need_wait + jitter
    log.debug(
        "B-6 join.rate.wait",
        extra={
            "subsys": "join_scheduler",
            "step": "B-6",
            "session": st.alias,
            "kind": kind,
            "reason": "token_wait",
            "wait_ms": int(total_wait * 1000),
            "cap": bucket.cap,
            "tokens_left": round(bucket.tokens, 2),
            "after_cooldown": after_cooldown,
        },
    )
    await asyncio.sleep(total_wait)
    bucket.consume_one()


# -----------------------------------------------------------------------------
# Воркери
# -----------------------------------------------------------------------------
async def _worker(idx: int):
    q = _QUEUES[idx]
    st = _STATE[idx]
    log.info(
        "B-5 worker.start",
        extra={"subsys": "join_scheduler", "step": "B-5", "session": st.alias, "idx": idx},
    )

    while True:
        task = await q.get()
        channel_id = int(task.get("channel_id"))
        invite_or_username = task.get("invite_or_username")
        source_url = task.get("source_url")
        kind = _classify_kind(invite_or_username)  # "public" | "private"

        # Rate-control
        await _rate_wait_session(idx, kind)

        ok = False
        err = None
        flood_wait_s: Optional[int] = None
        try:
            if not MONITOR_LINKS_SHADOW:
                ok, err = await ensure_join(_SESSIONS[idx], invite_or_username)
        except Exception as e:
            # На випадок, якщо ensure_join кидає, а не повертає (підстрахуємо)
            ok = False
            err = e

        # Аналіз результату
        if not ok:
            flood_wait_s = _parse_flood_wait_seconds(err)

        # Оновлення БД (subscriptions)
        try:
            await channel_maps.upsert_subscription_joined(channel_id, bool(ok), st.alias, None if ok else str(err))
        except Exception:
            # Базу не валимо — просто залогуємо
            log.exception(
                "B-6 sub.update.fail",
                extra={
                    "subsys": "join_scheduler",
                    "step": "B-6",
                    "session": st.alias,
                    "channel_id": channel_id,
                    "ok": bool(ok),
                },
            )

        # Лог результату
        log.info(
            "B-5 join.result",
            extra={
                "subsys": "join_scheduler",
                "step": "B-5",
                "session": st.alias,
                "channel_id": channel_id,
                "kind": kind,
                "ok": bool(ok),
                "err": None if ok else str(err),
                "flood_wait_s": flood_wait_s,
            },
        )

        # Адаптація лімітів і cooldown
        _adapt_limits_and_cooldown(st, kind, ok, flood_wait_s)

        q.task_done()


def _adapt_limits_and_cooldown(st: SessionState, kind: str, ok: bool, flood_wait_s: Optional[int]):
    """Адаптуємо місткості бакетів і керуємо cooldown-ом сесії."""
    bucket = st.public_bucket if kind == "public" else st.private_bucket

    cap_old = bucket.cap
    cap_new = cap_old

    if ok:
        if kind == "public":
            st.good_public += 1
            st.good_private = 0 if st.good_private > 0 else st.good_private
            if st.good_public >= JOIN_GOOD_STREAK:
                cap_new = min(cap_old + 1, JOIN_PUBLIC_MAX)
                st.good_public = 0
        else:
            st.good_private += 1
            st.good_public = 0 if st.good_public > 0 else st.good_public
            if st.good_private >= JOIN_GOOD_STREAK:
                cap_new = min(cap_old + 1, JOIN_PRIVATE_MAX)
                st.good_private = 0

        if cap_new != cap_old:
            bucket.update_cap(cap_new, JOIN_LIMIT_WINDOW)
            log.info(
                "B-6 limits.update",
                extra={
                    "subsys": "join_scheduler",
                    "step": "B-6",
                    "session": st.alias,
                    "kind": kind,
                    "reason": "good_streak",
                    "cap_old": cap_old,
                    "cap_new": cap_new,
                },
            )
        return

    # not ok
    st.good_public = 0
    st.good_private = 0

    if flood_wait_s and flood_wait_s > 0:
        # зменшуємо місткість бакету в 2 рази (але не нижче мінімуму)
        if kind == "public":
            cap_new = max(math.floor(cap_old * 0.5), JOIN_PUBLIC_MIN)
        else:
            cap_new = max(math.floor(cap_old * 0.5), JOIN_PRIVATE_MIN)

        if cap_new != cap_old:
            bucket.update_cap(cap_new, JOIN_LIMIT_WINDOW)

        # глобальний cooldown = W + HOLD
        W = float(flood_wait_s)
        hold_base = _clamp(W * float(JOIN_AFTER_FLOOD_HOLD_PCT), float(JOIN_AFTER_FLOOD_HOLD_MIN), float(JOIN_AFTER_FLOOD_HOLD_MAX))
        hold_jitter = W * _rand_uniform(*JITTER_AFTER_COOLDOWN_PCT)
        extra_hold = hold_base + hold_jitter

        st.last_flood_w = W
        st.cooldown_until = _now() + W + extra_hold

        log.warning(
            "B-6 limits.update",
            extra={
                "subsys": "join_scheduler",
                "step": "B-6",
                "session": st.alias,
                "kind": kind,
                "reason": "flood",
                "flood_wait_s": int(W),
                "extra_hold_s": int(extra_hold),
                "cooldown_until_ts": st.cooldown_until,
                "cap_old": cap_old,
                "cap_new": cap_new,
            },
        )
    else:
        # Інші помилки — не чіпаємо cap/cooldown
        pass


# -----------------------------------------------------------------------------
# API
# -----------------------------------------------------------------------------
async def setup_join_scheduler(sessions: List[Any]):
    """Ініціалізація: один воркер на кожну сесію."""
    global _SESSIONS, _QUEUES, _ALIAS_TO_IDX, _STATE, _STARTED

    if _STARTED:
        return
    _SESSIONS = sessions or []
    if not _SESSIONS:
        return

    _QUEUES = [asyncio.Queue() for _ in _SESSIONS]
    _STATE = []

    _ALIAS_TO_IDX = {}
    for i, s in enumerate(_SESSIONS):
        try:
            alias = session_name(s)
        except Exception:
            alias = f"session_{i}"
        _ALIAS_TO_IDX[alias] = i
        st = SessionState(alias)
        _STATE.append(st)
        log.debug("B-5 session.map", extra={"subsys": "join_scheduler", "step": "B-5", "alias": alias, "idx": i})

    for i in range(len(_SESSIONS)):
        asyncio.create_task(_worker(i))

    _STARTED = True
    log.info("B-5 scheduler.ready", extra={"subsys": "join_scheduler", "step": "B-5", "sessions": len(_SESSIONS)})


async def enqueue_join(channel_id: int, invite_or_username: Optional[str], source_url: Optional[str]):
    """
    Додаємо завдання в чергу конкретної сесії:
      - якщо вже є запис у subscriptions з alias і joined=True -> скіпаємо;
      - якщо в subscriptions є alias, але не joined -> використовуємо той же alias;
      - інакше — рівномірно розподіляємо по сесіях (хеш від channel_id).
    """
    # У тіньовому режимі не ставимо в чергу реальних join, але лог лишаємо.
    if MONITOR_LINKS_SHADOW:
        log.debug(
            "B-5 join.enqueue.shadow",
            extra={"subsys": "join_scheduler", "step": "B-5", "channel_id": int(channel_id), "url": source_url},
        )
        return

    if not _SESSIONS:
        return

    # Якщо вже є запис у subscriptions
    try:
        sub = await channel_maps.get_subscription(int(channel_id))
    except Exception:
        sub = None

    if sub:
        joined = bool(sub[1])
        alias = sub[2]
        if joined:
            log.debug(
                "B-5 join.skip.joined",
                extra={"subsys": "join_scheduler", "step": "B-5", "channel_id": int(channel_id)},
            )
            return
        idx_alias = _pick_idx_by_alias(alias)
        idx = idx_alias if idx_alias is not None else _pick_idx_hash(channel_id)
    else:
        idx = _pick_idx_hash(channel_id)

    await _QUEUES[idx].put(
        {
            "channel_id": int(channel_id),
            "invite_or_username": invite_or_username,
            "source_url": source_url,
        }
    )
    log.debug(
        "B-5 join.enqueue",
        extra={
            "subsys": "join_scheduler",
            "step": "B-5",
            "channel_id": int(channel_id),
            "queue_idx": idx,
            "queued_total": _QUEUES[idx].qsize(),
        },
    )


def join_status() -> Dict[str, int]:
    if not _SESSIONS:
        return {"sessions": 0, "queued": 0}
    return {"sessions": len(_SESSIONS), "queued": sum(q.qsize() for q in _QUEUES)}

# --- DEBUG / INSPECT ---------------------------------------------------------
def snapshot() -> Dict[str, Any]:
    """
    Повертає детальний стан по кожній сесії для дебагу адаптивних лімітів:
    - alias, cooldown_until (monotonic), last_flood_w
    - public/private: cap, tokens(≈), rate(tok/s), good_streak лічильники
    - queue_size
    """
    out = {
        "sessions": len(_SESSIONS),
        "total_queued": sum(q.qsize() for q in _QUEUES) if _QUEUES else 0,
        "items": [],
    }
    for i, st in enumerate(_STATE or []):
        pub = st.public_bucket
        prv = st.private_bucket
        out["items"].append({
            "idx": i,
            "alias": st.alias,
            "cooldown_until": st.cooldown_until,   # monotonic timestamp
            "last_flood_w": st.last_flood_w,       # сек
            "public": {
                "cap": pub.cap,
                "tokens": round(pub.tokens, 2),
                "rate": round(pub.rate, 4),
                "good_streak": st.good_public,
            },
            "private": {
                "cap": prv.cap,
                "tokens": round(prv.tokens, 2),
                "rate": round(prv.rate, 4),
                "good_streak": st.good_private,
            },
            "queue_size": _QUEUES[i].qsize() if i < len(_QUEUES) else 0,
        })
    return out