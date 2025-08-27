# app/plugins/batch_links.py
from __future__ import annotations

import logging
import time
from typing import Callable, Dict, Optional, Union, Awaitable

from telethon import events
from telethon.tl.custom.message import Message

from app.services.link_queue import (
    list_active as lq_list_active,
    count_active as lq_count_active,
)
from app.plugins.progress_live import DebouncedProgress
from app.utils.link_parser import extract_links_any
from app.utils.notices import reply_info, reply_error

log = logging.getLogger("plugin.batch_links")

# submitter-и за chat_id контрольного чату
_registered_submitters: Dict[int, Callable[[Union[str, Message]], Awaitable[None]]] = {}


# ---------- фабрика submitter-а ----------
def _make_submitter(client, control_peer: int, monitor_buffer):
    async def submit(msg_or_text: Union[str, Message]) -> None:
        # 1) Дістаємо текст і повідомлення для reply (якщо є)
        if isinstance(msg_or_text, Message):
            text = (msg_or_text.raw_text or "").strip()
            evt_for_reply: Optional[Message] = msg_or_text
        else:
            text = (msg_or_text or "").strip()
            evt_for_reply = None

        # 2) Витягуємо лінки
        links = extract_links_any(text)
        if not links:
            note = (
                "⚠️ Не знайдено жодного посилання. "
                "Надішліть список посилань в одному повідомленні."
            )
            if evt_for_reply is not None:
                await reply_info(evt_for_reply, note)
            else:
                await client.send_message(control_peer, note, link_preview=False)
            return

        # 3) Прогрес (debounce всередині)
        progress = DebouncedProgress(client, control_peer, "Пакет посилань", len(links))
        await progress.start()

        try:
            # 4) Запускаємо «двигун» обробки
            from app.flows.batch_links.process_links import process_links
            await process_links(
                links=links,
                progress=progress,
                monitor_buffer=monitor_buffer,
            )
        except Exception as e:
            await progress.finish(footer=f"❗️ Помилка: {e!r}")
            msg = f"Помилка обробки: {e!r}"
            if evt_for_reply is not None:
                await reply_error(evt_for_reply, msg)
            else:
                await client.send_message(control_peer, f"❗️ {msg}", link_preview=False)
            log.exception("plugin.batch_links: batch processing error")
            return

        await progress.finish()

    return submit


# ---------- публічний entry-point плагіна ----------
def setup(client, *, control_peer: int, monitor_buffer) -> None:
    """
    Викликається з app/telethon_client.py під час завантаження плагінів.
    """
    # Реєструємо submitter для контрольного чату
    submitter = _make_submitter(client, control_peer, monitor_buffer)
    _registered_submitters[control_peer] = submitter
    log.info("batch_links: submitter registered for chat %s", control_peer)

    # Команди вмикання/вимикання режиму прийому посилань
    client.add_event_handler(
        lambda e: _cmd_on(e, monitor_buffer, control_peer),
        events.NewMessage(chats=control_peer, pattern=r"^/monitor_links_on$")
    )
    client.add_event_handler(
        lambda e: _cmd_off(e, monitor_buffer, control_peer),
        events.NewMessage(chats=control_peer, pattern=r"^/monitor_links_off$")
    )

    # Команда статусу черги (короткий ETA + топ-10)
    client.add_event_handler(
        lambda e: _cmd_status(e, control_peer),
        events.NewMessage(chats=control_peer, pattern=r"^/status$")
    )

    # Утиліти черги
    client.add_event_handler(
        lambda e: _cmd_queue_status(e, control_peer),
        events.NewMessage(chats=control_peer, pattern=r"^/queue_status$")
    )
    client.add_event_handler(
        lambda e: _cmd_queue_clear_dryrun(e, control_peer),
        events.NewMessage(chats=control_peer, pattern=r"^/queue_clear_dryrun$")
    )
    client.add_event_handler(
        lambda e: _cmd_queue_clear(e, control_peer),
        events.NewMessage(chats=control_peer, pattern=r"^/queue_clear(?:\s+.*)?$")
    )

    # Обробка довільних повідомлень у контрольному чаті
    client.add_event_handler(
        lambda e: _on_msg(e, monitor_buffer, control_peer),
        events.NewMessage(chats=control_peer)
    )

    log.info("batch_links plugin loaded")


# ---------- команди ----------
async def _cmd_on(evt: Message, monitor_buffer, control_peer: int) -> None:
    if evt.chat_id != control_peer:
        return
    monitor_buffer.active = True
    if hasattr(monitor_buffer, "collected_links"):
        monitor_buffer.collected_links.clear()
    await reply_info(
        evt,
        "✅ Режим прийому посилань увімкнено.\n"
        "Надішліть ОДНИМ повідомленням список каналів/інвайтів/юзернеймів."
    )
    log.info("monitor links ON in chat %s", control_peer)


async def _cmd_off(evt: Message, monitor_buffer, control_peer: int) -> None:
    if evt.chat_id != control_peer:
        return
    monitor_buffer.active = False
    if hasattr(monitor_buffer, "collected_links"):
        monitor_buffer.collected_links.clear()
    await reply_info(evt, "⛔️ Режим прийому посилань вимкнено.")
    log.info("monitor links OFF in chat %s", control_peer)


async def _cmd_status(evt: Message, control_peer: int) -> None:
    """
    /status — показує короткий стан черги:
      • кількість queued/processing
      • приблизний ETA з урахуванням next_try_ts
      • список перших 10 посилань (із причиною/очікуванням)
    """
    if evt.chat_id != control_peer:
        return

    queued, processing, total = lq_count_active()
    if total == 0:
        await evt.reply("✅ Черга порожня. Немає активних завдань.")
        return

    items = lq_list_active(limit=100)
    now = int(time.time())

    # Груба оцінка часу на 1 лінк (секунди).
    AVG_PER_ITEM_SEC = 7

    # ETA: враховуємо next_try_ts + послідовну обробку кожного айтема
    current_time = now
    for it in items:
        available = max(it["next_try_ts"], current_time)
        finish = available + AVG_PER_ITEM_SEC
        current_time = finish
    eta_sec = max(0, current_time - now)

    def _fmt_sec(s: int) -> str:
        h = s // 3600
        m = (s % 3600) // 60
        ss = s % 60
        if h > 0:
            return f"{h:02d}:{m:02d}:{ss:02d}"
        return f"{m:02d}:{ss:02d}"

    # перші 10 рядків
    lines = []
    show = min(10, len(items))
    for i in range(show):
        it = items[i]
        wait = max(0, it["next_try_ts"] - now)
        tag = "⏳" if it["state"] == "queued" else "⚙️"
        reason = f" (_{it['reason']}_) " if it.get("reason") else ""
        wait_str = f" · wait ~{wait}s" if wait > 0 else ""
        lines.append(f"{i+1}. {tag} {it['url']}{reason}{wait_str}")

    more = f"\n… та ще {len(items) - show} записів" if len(items) > show else ""

    text = (
        "📊 *Статус черги*\n"
        f"• queued: *{queued}*\n"
        f"• processing: *{processing}*\n"
        f"• active: *{total}*\n"
        f"• ETA (≈): *{_fmt_sec(eta_sec)}*\n\n"
        + "\n".join(lines) + more
    )
    await evt.reply(text, parse_mode="markdown", link_preview=False)


# ---- утиліти черги ----
async def _cmd_queue_status(evt: Message, control_peer: int) -> None:
    if evt.chat_id != control_peer:
        return
    try:
        from app.utils.queue_cleanup import count_pending, list_pending
    except Exception:
        await evt.reply("❗️ Модуль `app.utils.queue_cleanup` не знайдено.")
        return

    n = count_pending()
    sample = list_pending(limit=15)
    head = "\n".join(f"• {u} [{st} t={tr}]" for _, u, st, tr in sample)
    more = "" if n <= 15 else f"\n… ще {n-15} у черзі"
    msg = f"📦 Черга (queued|processing): *{n}*\n"
    if sample:
        msg += f"Перші {min(n,15)}:\n{head}{more}"
    else:
        msg += "Черга порожня."
    await evt.reply(msg, parse_mode="markdown", link_preview=False)


async def _cmd_queue_clear_dryrun(evt: Message, control_peer: int) -> None:
    if evt.chat_id != control_peer:
        return
    try:
        from app.utils.queue_cleanup import clear_pending
    except Exception:
        await evt.reply("❗️ Модуль `app.utils.queue_cleanup` не знайдено.")
        return

    n = clear_pending(dry_run=True)
    await evt.reply(f"🧪 Dry-run: буде видалено {n} записів (queued|processing).", link_preview=False)


async def _cmd_queue_clear(evt: Message, control_peer: int) -> None:
    if evt.chat_id != control_peer:
        return
    # простий safeguard: вимагаємо явне підтвердження "/queue_clear YES"
    text = (evt.raw_text or "").strip()
    if text != "/queue_clear YES":
        await evt.reply(
            "⚠️ Ця команда видаляє ВСІ queued|processing з черги безповоротно.\n"
            "Якщо впевнений, надішли: `/queue_clear YES`",
            link_preview=False
        )
        return

    try:
        from app.utils.queue_cleanup import clear_pending
    except Exception:
        await evt.reply("❗️ Модуль `app.utils.queue_cleanup` не знайдено.")
        return

    n = clear_pending(dry_run=False)
    await evt.reply(f"🧹 Видалено {n} записів із черги (queued|processing).", link_preview=False)


# ---------- прийом повідомлень з лінками ----------
async def _on_msg(evt: events.NewMessage.Event, monitor_buffer, control_peer: int) -> None:
    """
    Обробник вхідних повідомлень у режимі /monitor_links_on.
    НЕ витягуємо посилання тут — submitter зробить це сам.
    """
    try:
        if evt.chat_id != control_peer:
            return
        if not getattr(monitor_buffer, "active", False):
            return

        # Ігноруємо службові/порожні/командні повідомлення
        text = (evt.raw_text or "").strip() if getattr(evt, "raw_text", None) else ""
        if not text or text.startswith("/"):
            return

        submitter = _registered_submitters.get(control_peer)
        if submitter is None:
            submitter = _make_submitter(evt.client, control_peer, monitor_buffer)
            _registered_submitters[control_peer] = submitter

        # Передаємо саме повідомлення — submitter сам витягне текст і посилання
        await submitter(evt.message)

    except Exception as e:
        await reply_error(evt, f"Помилка обробки: {e!s}")
        log.exception("plugin.batch_links: batch processing error")