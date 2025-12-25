from __future__ import annotations

import logging
import re
from typing import Any, Dict

from app.services.account_pool import (
    lease,
    session_name,
    mark_flood,
    mark_limit,
    bump_cooldown,
    iter_pool_clients,
    iter_ready_pool_clients,
)
from app.services.joiner import ensure_join

log = logging.getLogger("admin_bot.services.join_via_pool")


def _parse_flood_seconds(status: str) -> int:
    try:
        m = re.search(r"flood_wait_(\d+)", status)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


async def ensure_join_via_pool(url: str) -> Dict[str, Any]:
    """
    Підключає наявний пул акаунтів і викликає ensure_join на одному з них.
    Повертає словник з полями:
        status, title, kind, channel_id, invite_hash, session
        error (опційно)
    """
    ctx = await lease()
    if ctx is None:
        total = len(iter_pool_clients())
        ready = len(iter_ready_pool_clients())
        log.info(
            "ensure_join_via_pool: no client available (ready=%s total=%s) url=%s",
            ready,
            total,
            url,
        )
        return {
            "status": "no_client",
            "error": "Немає доступних клієнтів у пулі (busy/sleep). Переконайся, що account_pool запущений.",
            "session": None,
            "channel_id": None,
            "title": None,
            "kind": None,
            "invite_hash": None,
        }

    async with ctx as client:
        sess = session_name(client)
        try:
            status, title, kind, channel_id, invite_hash = await ensure_join(client, url)
        except Exception as e:
            log.exception("ensure_join_via_pool failed url=%s sess=%s", url, sess)
            return {"status": "error", "error": str(e), "session": sess, "channel_id": None, "title": None, "kind": None, "invite_hash": None}

    # Короткі кулдауни/маркування після виходу з контексту
    if status.startswith("flood_wait_"):
        secs = _parse_flood_seconds(status)
        if secs:
            mark_flood(client, secs)
    elif status == "too_many":
        mark_limit(client)
    else:
        bump_cooldown(client, 2)

    return {
        "status": status,
        "title": title,
        "kind": kind,
        "channel_id": channel_id,
        "invite_hash": invite_hash,
        "session": sess,
    }
