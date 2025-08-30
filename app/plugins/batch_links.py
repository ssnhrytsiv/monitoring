import re
import asyncio
import logging
from telethon import events
from telethon.tl import types as ttypes  # для перевірки entities/markup

from app.services.membership_db import init as memb_init
from app.services.link_queue import init as lq_init
from app.flows.batch_links import process_links, run_link_queue_worker

log = logging.getLogger("plugin.batch_links")

_MONITOR_ENABLED = False
_MONITOR_CHAT_ID = None
_CONTROL_PEER_ID = None


def setup(client, control_peer=None, monitor_buffer=None, **kwargs):
    global _CONTROL_PEER_ID
    _CONTROL_PEER_ID = control_peer

    memb_init()  # читає DB_PATH із .env всередині модуля
    lq_init()

    log.info("batch_links: setup(control_peer=%s, monitor_buffer=%s)", control_peer, monitor_buffer)

    @client.on(events.NewMessage(pattern=r'^/monitor_links_on$'))
    async def _on(evt):
        if _CONTROL_PEER_ID is not None and evt.chat_id != _CONTROL_PEER_ID:
            return
        global _MONITOR_ENABLED, _MONITOR_CHAT_ID
        _MONITOR_ENABLED = True
        _MONITOR_CHAT_ID = evt.chat_id
        await evt.reply("🟢 Режим додавання посилань увімкнено. Надішліть список t.me-посилань одним повідомленням.")

    @client.on(events.NewMessage(pattern=r'^/monitor_links_off$'))
    async def _off(evt):
        if _CONTROL_PEER_ID is not None and evt.chat_id != _CONTROL_PEER_ID:
            return
        global _MONITOR_ENABLED, _MONITOR_CHAT_ID
        _MONITOR_ENABLED = False
        _MONITOR_CHAT_ID = None
        await evt.reply("🔴 Режим додавання посилань вимкнено.")

    @client.on(events.NewMessage(pattern=r'^/monitor_links_status$'))
    async def _status(evt):
        if _CONTROL_PEER_ID is not None and evt.chat_id != _CONTROL_PEER_ID:
            return
        await evt.reply(f"ℹ️ monitor_links: {'ON' if _MONITOR_ENABLED else 'OFF'}; chat={_MONITOR_CHAT_ID}")

    @client.on(events.NewMessage())
    async def _msg(evt):
        # фільтри доступу/режиму
        if _CONTROL_PEER_ID is not None and evt.chat_id != _CONTROL_PEER_ID:
            return
        if not _MONITOR_ENABLED:
            return
        if _MONITOR_CHAT_ID is not None and evt.chat_id != _MONITOR_CHAT_ID:
            return

        msg = evt.message
        text = evt.raw_text or ""

        # 1) Посилання з тексту
        has_text_link = bool(
            re.search(r"https?://t\.me/", text, flags=re.IGNORECASE)
            or re.search(r"(?:^|\s)@[A-Za-z0-9_]{3,}", text)
        )

        # 2) Приховані посилання у гіпертексті (MessageEntityTextUrl)
        ents = getattr(msg, "entities", None) or []
        has_entity_link = any(isinstance(e, ttypes.MessageEntityTextUrl) for e in ents)

        # 3) URL у кнопках (inline/reply markup)
        markup = getattr(msg, "reply_markup", None)
        has_markup_url = False
        try:
            if isinstance(markup, (ttypes.ReplyInlineMarkup, ttypes.ReplyKeyboardMarkup)):
                rows = getattr(markup, "rows", []) or []
                for row in rows:
                    for btn in getattr(row, "buttons", []) or []:
                        if hasattr(btn, "url") and getattr(btn, "url", None):
                            has_markup_url = True
                            break
                    if has_markup_url:
                        break
        except Exception:
            # не валимо хендлер через екзотику в markup
            pass

        # Якщо взагалі немає жодного типу посилань — ігноруємо
        if not (has_text_link or has_entity_link or has_markup_url):
            return

        try:
            # Передаємо msg, щоб process_links мав доступ до entities/markup
            await process_links(msg, text)
        except Exception as e:
            log.exception("batch_links error: %s", e)
            await evt.reply(f"⚠️ Помилка обробки: {e}")

    # воркер черги
    try:
        client.loop.create_task(run_link_queue_worker(client))
    except Exception:
        asyncio.create_task(run_link_queue_worker(client))

    log.info("batch_links plugin loaded")