# app/utils/notices.py
from app.config import CONTROL_PEER
VERBOSE_NOTICES = False  # set True to see debug notices

async def notice(client, control_peer: str | int = CONTROL_PEER, text: str = ""):
    """Single point for auxiliary messages. Silent unless VERBOSE_NOTICES=True."""
    if VERBOSE_NOTICES and text:
        try:
            await client.send_message(control_peer, text)
        except Exception:
            pass