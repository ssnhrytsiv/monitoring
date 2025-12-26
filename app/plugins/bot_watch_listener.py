"""
Слухач для ботів: коли будь-який акаунт із пулу отримує повідомлення від бота,
фіксуємо це в bot_links (status=bot_message) і логах.

Це легкий аналог posts_watch_listener, але тільки для ботів.
"""

import logging
from telethon import events

from app.services.account_pool import iter_pool_clients, session_name
from app.utils.tg_links import extract_bot_username
from app.services import channel_db

log = logging.getLogger("plugin.bot_watch_listener")


def _attach_listener_for_client(cli):
    sess = session_name(cli)

    @cli.on(events.NewMessage)
    async def _on_new_message(ev):
        try:
            sender = await ev.get_sender()
            username = getattr(sender, "username", None)
            if not username:
                return
            bot_user = extract_bot_username(username)
            if not bot_user:
                return

            channel_db.upsert_bot_link(
                username=bot_user,
                raw_url=f"https://t.me/{bot_user}",
                status="bot_message",
                session=sess,
                title=getattr(sender, "first_name", None),
                owner_display=None,
                owner_username=None,
                batch_id=None,
                error=None,
            )
            log.info("bot_watch_listener: message from bot=%s session=%s", bot_user, sess)
        except Exception as e:
            log.debug("bot_watch_listener: handler failed: %s", e)

    log.info("bot_watch_listener: attached listener to %s", sess)


def setup(**_):
    for slot in iter_pool_clients():
        try:
            _attach_listener_for_client(slot.client)
        except Exception as e:
            log.debug("bot_watch_listener: failed to attach for %s: %s", slot, e)
