from telethon import events


def setup(client, control_peer, monitor_buffer):
    dec_filter = {}
    if control_peer:
        dec_filter = dict(from_users=control_peer)

    @client.on(events.NewMessage(pattern=r'^/needle_clear$', **dec_filter))
    async def needle_clear(event):
        monitor_buffer.needle = None
        await event.reply("🧹 Needle очищено.")

    @client.on(events.NewMessage(pattern=r'^/needle_show$', **dec_filter))
    async def needle_show(event):
        if monitor_buffer.needle:
            await event.reply(f"🔍 Поточний needle:\n<code>{monitor_buffer.needle}</code>", parse_mode="html")
        else:
            await event.reply("ℹ️ Needle ще не задано.")

    @client.on(events.NewMessage(pattern=r'^/needle_from_reply$', **dec_filter))
    async def needle_from_reply(event):
        if not event.is_reply:
            await event.reply("❗ Зроби reply на повідомлення з текстом.")
            return
        reply = await event.get_reply_message()
        monitor_buffer.needle = reply.raw_text or ""
        await event.reply(f"✅ Needle взято з reply:\n<code>{monitor_buffer.needle}</code>", parse_mode="html")