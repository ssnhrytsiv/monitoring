import logging
from telethon import events
from app.flows.batch_links import process_links

log = logging.getLogger("plugin.owner_set")


def setup(client, control_peer=None, monitor_buffer=None, **kwargs):
    """
    Плагін для встановлення owner перед запуском відкладеного пакету посилань.
    Команда:
      /owner_set <ім'я | @username>
    Необов'язкове: /owner_clear (скинути поточний owner у буфері).
    """
    log.info("owner_set plugin loaded (control_peer=%s, buffer_id=%s)", control_peer, id(monitor_buffer) if monitor_buffer else None)

    @client.on(events.NewMessage(pattern=r"^/owner_set(?:@\w+)?"))
    async def _on_owner_set(event):
        if control_peer is not None and event.chat_id != control_peer:
            return

        parts = event.raw_text.strip().split(maxsplit=1)
        if len(parts) < 2:
            await event.reply("⚠️ Використання: /owner_set <ім'я або @username>")
            return

        raw = parts[1].strip()
        if raw.startswith("@"):
            owner_username = raw.lstrip("@")
            owner_display = owner_username
        else:
            owner_display = raw
            owner_username = None
            # Евристика: якщо без пробілів і ASCII — вважаємо username-варіант
            if raw.isascii() and " " not in raw:
                owner_username = raw

        if monitor_buffer:
            monitor_buffer.owner_display = owner_display
            monitor_buffer.owner_username = owner_username
            log.debug(
                "owner_set: stored owner_display=%r owner_username=%r buffer_id=%s",
                owner_display, owner_username, id(monitor_buffer)
            )

        # Якщо є відкладений пакет — запускаємо
        if monitor_buffer and getattr(monitor_buffer, "pending_batch", None):
            pb = monitor_buffer.pending_batch
            if not pb.get("processing"):
                pb["processing"] = True
                await event.reply(
                    f"✅ Owner встановлено: {owner_display}"
                    + (f" (username: @{owner_username})" if owner_username else "")
                    + "\n🟦 Починаю обробку пакету..."
                )
                try:
                    await process_links(
                        pb["message"],
                        pb["text"],
                        owner_display=monitor_buffer.owner_display,
                        owner_username=monitor_buffer.owner_username
                    )
                except Exception as e:
                    log.exception("Error processing deferred batch with owner: %s", e)
                    await event.reply(f"⚠️ Помилка обробки пакету: {e}")
                finally:
                    monitor_buffer.pending_batch = None
                return

        # Немає відкладеного пакету
        await event.reply(
            f"✅ Owner встановлено: {owner_display}"
            + (f" (username: @{owner_username})" if owner_username else "")
            + "\n(Немає відкладеного пакету для запуску)"
        )

    @client.on(events.NewMessage(pattern=r"^/owner_clear$"))
    async def _on_owner_clear(event):
        if control_peer is not None and event.chat_id != control_peer:
            return
        if not monitor_buffer:
            await event.reply("ℹ️ Немає активного буфера.")
            return
        monitor_buffer.owner_display = None
        monitor_buffer.owner_username = None
        await event.reply("♻️ Owner скинуто (поля owner_display / owner_username очищені).")