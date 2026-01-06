# app/utils/throttle.py
import os
import random
import asyncio
import logging
import inspect
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
PROBE_DELAY_MIN = _f("PROBE_DELAY_MIN", "2.45")
PROBE_DELAY_MAX = _f("PROBE_DELAY_MAX", "4.10")

# "важкі" дії (імпорт інвайту/джойн) — вже були у тебе як LINK_DELAY_*
LINK_DELAY_PUBLIC_MIN = _f("LINK_DELAY_PUBLIC_MIN", "35")
LINK_DELAY_PUBLIC_MAX = _f("LINK_DELAY_PUBLIC_MAX", "50")
LINK_DELAY_INVITE_MIN = _f("LINK_DELAY_INVITE_MIN", "35")
LINK_DELAY_INVITE_MAX = _f("LINK_DELAY_INVITE_MAX", "50")
LINK_DELAY_BOT_MIN = _f("LINK_DELAY_BOT_MIN", "5")
LINK_DELAY_BOT_MAX = _f("LINK_DELAY_BOT_MAX", "8")
# окремий троттл для CheckChatInviteRequest (peek)
INVITE_PEEK_DELAY = _f("INVITE_PEEK_DELAY", "30")

PROBE_DELAY_MIN, PROBE_DELAY_MAX = _clamp_pair(PROBE_DELAY_MIN, PROBE_DELAY_MAX)
LINK_DELAY_PUBLIC_MIN, LINK_DELAY_PUBLIC_MAX = _clamp_pair(LINK_DELAY_PUBLIC_MIN, LINK_DELAY_PUBLIC_MAX)
LINK_DELAY_INVITE_MIN, LINK_DELAY_INVITE_MAX = _clamp_pair(LINK_DELAY_INVITE_MIN, LINK_DELAY_INVITE_MAX)
INVITE_PEEK_DELAY = max(0.0, INVITE_PEEK_DELAY)


def _log_caller(kind: str, url: str = "") -> None:
    """Debug helper: log who triggered throttle (always on)."""
    try:
        # беремо перший фрейм поза цим модулем
        caller = "unknown"
        for frame_info in inspect.stack()[2:]:
            fname = frame_info.filename or ""
            if "utils/throttle.py" not in fname:
                caller = f"{os.path.basename(fname)}:{frame_info.function}"
                break
        if url:
            log.debug("throttle(%s): caller=%s url=%s", kind, caller, url)
        else:
            log.debug("throttle(%s): caller=%s", kind, caller)
    except Exception:
        pass


# ---- нові зручні корутини ----
async def throttle_probe(url: str = "") -> None:
    """
    Коротка пауза перед дешевими перевірками (probe):
    - CheckChatInviteRequest (якщо це саме "проба")
    - легкі get_entity
    """
    delay = random.uniform(PROBE_DELAY_MIN, PROBE_DELAY_MAX)
    _log_caller("probe", url)
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
    _log_caller("invite")
    log.debug("throttle(invite): sleep %.2fs", delay)
    await asyncio.sleep(delay)

async def throttle_public() -> None:
    """
    Пауза між обробкою публічних посилань/юзернеймів.
    """
    delay = random.uniform(LINK_DELAY_PUBLIC_MIN, LINK_DELAY_PUBLIC_MAX)
    _log_caller("public")
    log.debug("throttle(public): sleep %.2fs", delay)
    await asyncio.sleep(delay)

async def throttle_bot() -> None:
    """
    Пауза між /start ботам.
    """
    delay = random.uniform(LINK_DELAY_BOT_MIN, LINK_DELAY_BOT_MAX)
    _log_caller("bot")
    log.debug("throttle(bot): sleep %.2fs", delay)
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
    _log_caller(label, url)
    if url:
        log.debug("throttle(%s): sleep %.2fs  url=%s", label, delay, url)
    else:
        log.debug("throttle(%s): sleep %.2fs", label, delay)
    await asyncio.sleep(delay)


async def throttle_invite_peek() -> None:
    """
    Пауза перед CheckChatInviteRequest (peek). Окремо від ImportChatInviteRequest.
    """
    delay = INVITE_PEEK_DELAY
    _log_caller("invite_peek")
    log.debug("throttle(invite_peek): sleep %.2fs", delay)
    await asyncio.sleep(delay)
