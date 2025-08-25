from telethon import events
import re


def setup(client, control_peer, monitor_buffer):
    dec_filter = {}
    if control_peer:
        dec_filter = dict(from_users=control_peer)

    @client.on(events.NewMessage(pattern=r'^/mon_new (.+)$', **dec_filter))
    async def mon_new(event):
        m = re.match(r"^/mon_new (.+)$", event.raw_text.strip())
        if not m:
            await event.reply("❗ Формат: /mon_new owner=@user cpm=123")
            return
        args = m.group(1)
        monitor_buffer.monitors.append({"args": args})
        await event.reply(f"✅ Новий монітор додано: <code>{args}</code>", parse_mode="html")

    @client.on(events.NewMessage(pattern=r'^/mon_status$', **dec_filter))
    async def mon_status(event):
        if not monitor_buffer.monitors:
            await event.reply("ℹ️ Активних моніторів немає.")
            return
        lines = []
        for i, mon in enumerate(monitor_buffer.monitors, 1):
            lines.append(f"{i}. {mon['args']}")
        await event.reply("📊 Монітори:\n" + "\n".join(lines))

    @client.on(events.NewMessage(pattern=r'^/mon_start$', **dec_filter))
    async def mon_start(event):
        if not monitor_buffer.monitors:
            await event.reply("ℹ️ Спершу створи монітор через /mon_new ...")
            return
        await event.reply("▶️ Моніторинг запущено (умовно).")