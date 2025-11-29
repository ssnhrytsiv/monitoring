import asyncio
import json
from typing import Any, Dict

from aiogram import Bot

from app.services.posts_watch_result_db import (
    fetch_unsent_events,
    mark_event_sent,
    get_watch_created_by,
)

def _parse_payload(payload_json: str) -> Dict[str, Any]:
    try:
        p = json.loads(payload_json or "{}")
        return p if isinstance(p, dict) else {}
    except Exception:
        return {}

def _event_text(event_type: str, payload_json: str, created_at: str, watch_id: int) -> str:
    payload = _parse_payload(payload_json)
    wid = payload.get("watch_id") or watch_id

    if event_type == "matched":
        mid = payload.get("message_id")
        cid = payload.get("channel_id")
        return (
            "✅ MATCH\n"
            f"watch_id: {wid}\n"
            f"channel_id: {cid or '—'}\n"
            f"msg_id: {mid or '—'}\n"
            f"коли: {created_at}"
        )

    if event_type == "views":
        v = payload.get("views")
        return (
            "👀 Перегляди знято\n"
            f"watch_id: {wid}\n"
            f"views: {v if v is not None else '—'}\n"
            f"коли: {created_at}"
        )

    if event_type == "deleted":
        return (
            "🗑️ Пост видалено\n"
            f"watch_id: {wid}\n"
            f"коли: {created_at}"
        )

    if event_type == "expired":
        return (
            "⏳ Не вийшов (expired)\n"
            f"watch_id: {wid}\n"
            f"коли: {created_at}"
        )

    if event_type == "edited_other":
        return (
            "✏️ Відредаговано, інший пост\n"
            f"watch_id: {wid}\n"
            f"коли: {created_at}"
        )

    return (
        f"ℹ️ Подія {event_type}\n"
        f"watch_id: {wid}\n"
        f"коли: {created_at}"
    )

async def notifier_loop(bot: Bot, tick_sec: float = 5.0):
    while True:
        try:
            events = fetch_unsent_events(200)
            for event_id, watch_id, event_type, payload_json, created_at in events:
                uid = get_watch_created_by(watch_id)
                if not uid:
                    mark_event_sent(event_id, 0)
                    continue

                text = _event_text(event_type, payload_json, created_at, watch_id)
                try:
                    await bot.send_message(int(uid), text)
                    mark_event_sent(event_id, int(uid))
                except Exception:
                    pass
        except Exception:
            pass

        await asyncio.sleep(tick_sec)