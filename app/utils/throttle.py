# app/utils/throttle.py
import os
import random
import asyncio
import logging
from typing import Tuple

log = logging.getLogger("utils.throttle")

def _f(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return float(default)

def _clamp_pair(lo: float, hi: float) -> Tuple[float, float]:
    lo = max(lo, 0.0)
    if hi < lo:
        hi = lo
    return lo, hi

# ---- налаштування затримок (ENV) ----
# легкі "проби" (CheckChatInviteRequest / get_entity при пробі)
PROBE_DELAY_MIN = _f("PROBE_DELAY_MIN", "0.45")
PROBE_DELAY_MAX = _f("PROBE_DELAY_MAX", "1.10")

# "важкі" дії (імпорт інвайту/джойн) — вже були у тебе як LINK_DELAY_*
LINK_DELAY_PUBLIC_MIN = _f("LINK_DELAY_PUBLIC_MIN", "2")
LINK_DELAY_PUBLIC_MAX = _f("LINK_DELAY_PUBLIC_MAX", "4")
LINK_DELAY_INVITE_MIN = _f("LINK_DELAY_INVITE_MIN", "6")
LINK_DELAY_INVITE_MAX = _f("LINK_DELAY_INVITE_MAX", "10")

PROBE_DELAY_MIN, PROBE_DELAY_MAX = _clamp_pair(PROBE_DELAY_MIN, PROBE_DELAY_MAX)
LINK_DELAY_PUBLIC_MIN, LINK_DELAY_PUBLIC_MAX = _clamp_pair(LINK_DELAY_PUBLIC_MIN, LINK_DELAY_PUBLIC_MAX)
LINK_DELAY_INVITE_MIN, LINK_DELAY_INVITE_MAX = _clamp_pair(LINK_DELAY_INVITE_MIN, LINK_DELAY_INVITE_MAX)

# ---- нові зручні корутини ----
async def throttle_probe(url: str = "") -> None:
    """
    Коротка пауза перед дешевими перевірками (probe):
    - CheckChatInviteRequest (якщо це саме "проба")
    - легкі get_entity
    """
    delay = random.uniform(PROBE_DELAY_MIN, PROBE_DELAY_MAX)
    if url:
        log.debug("throttle(probe): sleep %.2fs  url=%s", delay, url)
    else:
        log.debug("throttle(probe): sleep %.2fs", delay)
    await asyncio.sleep(delay)

async def throttle_invite() -> None:
    """
    Пауза перед важкими діями (імпорт інвайту/приєднання).
    """
    delay = random.uniform(LINK_DELAY_INVITE_MIN, LINK_DELAY_INVITE_MAX)
    log.debug("throttle(invite): sleep %.2fs", delay)
    await asyncio.sleep(delay)

async def throttle_public() -> None:
    """
    Пауза між обробкою публічних посилань/юзернеймів.
    """
    delay = random.uniform(LINK_DELAY_PUBLIC_MIN, LINK_DELAY_PUBLIC_MAX)
    log.debug("throttle(public): sleep %.2fs", delay)
    await asyncio.sleep(delay)

# ---- наявна у тебе функція (залишаємо для зворотної сумісності) ----
async def throttle_between_links(kind: str | None, url: str = "") -> None:
    """
    kind: 'invite' | 'public' | None
    Якщо kind None — визначаємо за url ('/+' або 'joinchat' => invite).
    """
    is_inv = (kind == "invite") or ("/+" in (url or "")) or ("joinchat" in (url or ""))
    if is_inv:
        lo, hi = LINK_DELAY_INVITE_MIN, LINK_DELAY_INVITE_MAX
        label = "invite"
    else:
        lo, hi = LINK_DELAY_PUBLIC_MIN, LINK_DELAY_PUBLIC_MAX
        label = "public"

    delay = random.uniform(lo, hi)
    if url:
        log.debug("throttle(%s): sleep %.2fs  url=%s", label, delay, url)
    else:
        log.debug("throttle(%s): sleep %.2fs", label, delay)
    await asyncio.sleep(delay)