# app/utils/notices.py

from __future__ import annotations
from app.config import CONTROL_PEER
from telethon import events

VERBOSE_NOTICES = False  # set True щоб бачити допоміжні нотифікації

async def notice(client, control_peer: str | int = CONTROL_PEER, text: str = ""):
    """Single point for auxiliary messages. Silent unless VERBOSE_NOTICES=True."""
    if VERBOSE_NOTICES and text:
        try:
            await client.send_message(control_peer, text)
        except Exception:
            pass

# --- ДОДАЙ ОЦЕ НИЖЧЕ: ---

async def reply_info(ev: events.NewMessage.Event, text: str):
    """
    Відповідь-нотіс з parse_mode=html у тому ж чаті.
    """
    await ev.reply(text, parse_mode="html")

async def reply_error(ev: events.NewMessage.Event, text: str):
    """
    Відповідь-помилка (з іконкою попередження) — також html.
    """
    await ev.reply(f"⚠️ {text}", parse_mode="html")