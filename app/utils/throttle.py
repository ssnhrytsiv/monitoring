# app/utils/throttle.py
import os
import random
import asyncio
import logging

log = logging.getLogger("utils.throttle")

def _f(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return float(default)

# --- затримки між спробами join (між лінками) ---
LINK_DELAY_PUBLIC_MIN = _f("LINK_DELAY_PUBLIC_MIN", "2")
LINK_DELAY_PUBLIC_MAX = _f("LINK_DELAY_PUBLIC_MAX", "4")
LINK_DELAY_INVITE_MIN = _f("LINK_DELAY_INVITE_MIN", "6")
LINK_DELAY_INVITE_MAX = _f("LINK_DELAY_INVITE_MAX", "10")

def _clamp_pair(lo: float, hi: float) -> tuple[float, float]:
    lo = max(lo, 0.0)
    if hi < lo:
        hi = lo
    return lo, hi

LINK_DELAY_PUBLIC_MIN, LINK_DELAY_PUBLIC_MAX = _clamp_pair(
    LINK_DELAY_PUBLIC_MIN, LINK_DELAY_PUBLIC_MAX
)
LINK_DELAY_INVITE_MIN, LINK_DELAY_INVITE_MAX = _clamp_pair(
    LINK_DELAY_INVITE_MIN, LINK_DELAY_INVITE_MAX
)

async def throttle_between_links(kind: str | None, url: str = ""):
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
    log.debug("throttle(%s): sleep %.2fs", label, delay)
    await asyncio.sleep(delay)

# --- НОВЕ: обережний throttle для probe_channel_id -----------------------------

# Легкий «обережний» профіль для пробних запитів (get_entity / CheckChatInviteRequest)
# Значення за замовчуванням м’які, щоб майже не впливати на швидкість,
# але різко зменшити burst при великих пакетах.
PROBE_DELAY_MIN = _f("PROBE_DELAY_MIN", "0.4")
PROBE_DELAY_MAX = _f("PROBE_DELAY_MAX", "1.1")
PROBE_DELAY_MIN, PROBE_DELAY_MAX = _clamp_pair(PROBE_DELAY_MIN, PROBE_DELAY_MAX)

async def throttle_probe(url: str = "") -> None:
    """
    Невелика випадкова затримка перед probe-запитами (get_entity / CheckChatInviteRequest),
    щоб не створювати піків трафіку при масових інвайтах/юзернеймах.
    """
    delay = random.uniform(PROBE_DELAY_MIN, PROBE_DELAY_MAX)
    log.debug("throttle(probe): sleep %.2fs  url=%s", delay, url)
    await asyncio.sleep(delay)