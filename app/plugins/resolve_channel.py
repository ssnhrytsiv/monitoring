# app/plugins/resolve_channel.py
from __future__ import annotations

from telethon import events
from app.telethon_client import client
from app.logging_json import get_logger

log = get_logger("plugin.resolve_channel")

def setup(control_peer=None, monitor_buffer=None, **kwargs):
    @client.on(events.NewMessage(pattern=r"^/resolve_channel$"))
    async def _(ev: events.NewMessage.Event):
        if not ev.is_reply:
            await ev.reply("⚠️ Зроби <b>reply</b> на будь-яке повідомлення в каналі й надішли /resolve_channel")
            return

        msg = await ev.get_reply_message()
        chat = await msg.get_chat()

        out = []
        out.append(f"chat.__class__ = {chat.__class__.__name__}")
        out.append(f"chat.id = {getattr(chat, 'id', None)}")
        out.append(f"chat.username = {getattr(chat, 'username', None)}")
        out.append(f"chat.title = {getattr(chat, 'title', None)}")
        out.append(f"chat.megagroup = {getattr(chat, 'megagroup', None)}")
        out.append(f"chat.broadcast = {getattr(chat, 'broadcast', None)}")

        out.append(f"msg.id = {msg.id}")
        out.append(f"msg.chat_id = {getattr(msg, 'chat_id', None)}")
        out.append(f"msg.peer_id = {getattr(msg, 'peer_id', None)}")

        text = "\n".join(map(str, out))
        await ev.reply(f"<pre>{text}</pre>")
        log.info("resolve_channel:\n%s", text)