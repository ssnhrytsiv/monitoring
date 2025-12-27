"""
Слухач для ботів: коли будь-який акаунт із пулу отримує повідомлення від бота,
фіксуємо це в bot_links (status=bot_message) і намагаємось заматчити очікувані повідомлення з bot_watch.
"""

import logging
from telethon import events
from telethon.tl.types import Message

from app.services.account_pool import iter_pool_clients, session_name
from app.utils.tg_links import extract_bot_username
from app.services import channel_db
from app.services import bot_watch_db, bot_template_db
from app.utils.html_normalize import normalize_html_full

log = logging.getLogger("plugin.bot_watch_listener")


def _attach_listener_for_client(cli):
    sess = session_name(cli)

    @cli.on(events.NewMessage)
    async def _on_new_message(ev: events.NewMessage.Event):
        try:
            sender = await ev.get_sender()
            username = getattr(sender, "username", None)
            if not username:
                return
            bot_user = extract_bot_username(username)
            if not bot_user:
                return

            # Лог у bot_links
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

            # Спроба заматчити очікувані повідомлення цього бота
            pending = bot_watch_db.list_pending_for_username(bot_user)
            if not pending:
                return

            msg: Message = ev.message
            msg_html = msg.message or ""
            try:
                msg_norm = normalize_html_full(msg_html)
            except Exception:
                msg_norm = msg_html or ""

            matched_any = False
            for row in pending:
                wid = row["id"]
                expected_norm = row.get("expected_norm") or ""
                if not expected_norm:
                    continue
                log.debug(
                    "bot_watch_listener: try match wid=%s bot=%s session=%s expected=%.120s got=%.120s",
                    wid,
                    bot_user,
                    sess,
                    expected_norm,
                    msg_norm,
                )
                if msg_norm == expected_norm:
                    bot_watch_db.mark_matched(wid, msg.id, sess)
                    log.info("bot_watch_listener: matched wid=%s bot=%s session=%s", wid, bot_user, sess)
                    matched_any = True
            if matched_any:
                # оновлюємо статус у bot_links
                channel_db.upsert_bot_link(
                    username=bot_user,
                    raw_url=f"https://t.me/{bot_user}",
                    status="bot_matched",
                    session=sess,
                    title=getattr(sender, "first_name", None),
                    owner_display=None,
                    owner_username=None,
                    batch_id=None,
                    error=None,
                )
        except Exception as e:
            log.debug("bot_watch_listener: handler failed: %s", e)

    log.info("bot_watch_listener: attached listener to %s", sess)


def setup(**_):
    bot_watch_db.init()
    bot_template_db.init()
    for slot in iter_pool_clients():
        try:
            _attach_listener_for_client(slot.client)
        except Exception as e:
            log.debug("bot_watch_listener: failed to attach for %s: %s", slot, e)
