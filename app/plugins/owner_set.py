import logging
from telethon import events
from app.flows.batch_links import process_links

log = logging.getLogger("plugin.owner_set")


def setup(client, control_peer=None, monitor_buffer=None, **kwargs):
    """
    Плагін для встановлення owner перед запуском відкладеного пакету посилань.
    Команди:
      /owner_set <ім'я | @username>
      /owner_clear
    Також можна просто написати ім'я або @username у чаті після "📦 Отримав …".
    """
    log.info(
        "owner_set plugin loaded (control_peer=%s, buffer_id=%s)",
        control_peer,
        id(monitor_buffer) if monitor_buffer else None,
    )

    # ---- helper: парсер вільного вводу owner
    def _parse_owner_freeform(raw: str):
        """
        Повертає (owner_display, owner_username) або (None, None), якщо не схоже на ім'я.
        """
        if not raw:
            return (None, None)
        s = raw.strip()
        if not s or s.startswith("/"):
            return (None, None)
        low = s.lower()
        if "http://" in low or "https://" in low or "t.me/" in low:
            return (None, None)
        if len(s) > 20:
            return (None, None)

        if s.startswith("@"):
            uname = s.lstrip("@")
            return (uname, uname) if uname else (None, None)

        if s.isascii() and " " not in s:
            return (s, s)

        return (s, None)

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
            if raw.isascii() and " " not in raw:
                owner_username = raw

        if monitor_buffer:
            monitor_buffer.owner_display = owner_display
            monitor_buffer.owner_username = owner_username
            log.debug(
                "owner_set: stored owner_display=%r owner_username=%r buffer_id=%s",
                owner_display,
                owner_username,
                id(monitor_buffer),
            )

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
                        owner_username=monitor_buffer.owner_username,
                    )
                except Exception as e:
                    log.exception("Error processing deferred batch with owner: %s", e)
                    await event.reply(f"⚠️ Помилка обробки пакету: {e}")
                finally:
                    monitor_buffer.pending_batch = None
                return

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

    # ---- вільний ввід owner без команди
    @client.on(events.NewMessage())
    async def _on_owner_freeform(event):
        log.info(
            "WE ARE IN OWNER")
        if control_peer is not None and event.chat_id != control_peer:
            return
        if not (monitor_buffer and getattr(monitor_buffer, "pending_batch", None)):
            return

        txt = (event.raw_text or "").strip()
        if not txt or txt.startswith("/"):
            return

        owner_display, owner_username = _parse_owner_freeform(txt)
        if not owner_display and not owner_username:
            return

        pb = monitor_buffer.pending_batch
        if pb.get("processing"):
            return

        monitor_buffer.owner_display = owner_display
        monitor_buffer.owner_username = owner_username
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
                owner_username=monitor_buffer.owner_username,
            )
        except Exception as e:
            log.exception("Error processing deferred batch (freeform): %s", e)
            await event.reply(f"⚠️ Помилка обробки пакету: {e}")
        finally:
            monitor_buffer.pending_batch = None