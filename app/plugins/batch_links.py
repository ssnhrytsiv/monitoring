import re
import asyncio
import logging
import time
from telethon import events
from telethon.tl import types as ttypes  # для перевірки entities/markup

from app.services.membership_db import init as memb_init
from app.services.link_queue import init as lq_init
from app.flows.batch_links import process_links, run_link_queue_worker
from app.utils.link_parser import extract_links  # щоб порахувати/перевірити URL перед відкладенням

log = logging.getLogger("plugin.batch_links")

_MONITOR_ENABLED = False
_MONITOR_CHAT_ID = None
_CONTROL_PEER_ID = None


def setup(client, control_peer=None, monitor_buffer=None, **kwargs):
    """
    ОНОВЛЕНА ЛОГІКА:
      - Повідомлення з посиланнями НЕ обробляється одразу.
      - Воно стає 'pending_batch' і чекає поки користувач надішле /owner_set ... (в іншому плагіні)
        або /owner_skip (обробити без owner) чи /batch_cancel (скасувати).
      - /monitor_links_status показує стан pending_batch та встановлений owner.
    """
    global _CONTROL_PEER_ID
    _CONTROL_PEER_ID = control_peer

    memb_init()  # читає DB_PATH із .env всередині модуля
    lq_init()

    # Гарантуємо необхідні атрибути у monitor_buffer
    if monitor_buffer is not None:
        if not hasattr(monitor_buffer, "owner_display"):
            monitor_buffer.owner_display = None
        if not hasattr(monitor_buffer, "owner_username"):
            monitor_buffer.owner_username = None
        if not hasattr(monitor_buffer, "pending_batch"):
            monitor_buffer.pending_batch = None

    log.info("batch_links: setup(control_peer=%s, monitor_buffer=%s)", control_peer, monitor_buffer)

    @client.on(events.NewMessage(pattern=r'^/monitor_links_on$'))
    async def _on(evt):
        if _CONTROL_PEER_ID is not None and evt.chat_id != _CONTROL_PEER_ID:
            return
        global _MONITOR_ENABLED, _MONITOR_CHAT_ID
        _MONITOR_ENABLED = True
        _MONITOR_CHAT_ID = evt.chat_id
        await evt.reply(
            "🟢 Режим додавання посилань увімкнено.\n"
            "Надішліть список t.me-посилань одним повідомленням.\n"
            "Після цього бот попросить задати owner (через /owner_set) перед обробкою."
        )

    @client.on(events.NewMessage(pattern=r'^/monitor_links_off$'))
    async def _off(evt):
        if _CONTROL_PEER_ID is not None and evt.chat_id != _CONTROL_PEER_ID:
            return
        global _MONITOR_ENABLED, _MONITOR_CHAT_ID
        _MONITOR_ENABLED = False
        _MONITOR_CHAT_ID = None
        # скасовуємо можливий відкладений пакет
        if monitor_buffer and getattr(monitor_buffer, "pending_batch", None):
            monitor_buffer.pending_batch = None
        await evt.reply("🔴 Режим додавання посилань вимкнено.")

    @client.on(events.NewMessage(pattern=r'^/monitor_links_status$'))
    async def _status(evt):
        if _CONTROL_PEER_ID is not None and evt.chat_id != _CONTROL_PEER_ID:
            return
        pending = bool(monitor_buffer and getattr(monitor_buffer, "pending_batch", None))
        owner_txt = getattr(monitor_buffer, "owner_display", None) if monitor_buffer else None
        await evt.reply(
            f"ℹ️ monitor_links: {'ON' if _MONITOR_ENABLED else 'OFF'}; "
            f"chat={_MONITOR_CHAT_ID}; "
            f"pending_batch={'yes' if pending else 'no'}; "
            f"owner={owner_txt or '—'}"
        )

    @client.on(events.NewMessage(pattern=r'^/batch_cancel$'))
    async def _batch_cancel(evt):
        """Скасувати відкладений пакет (якщо передумали)."""
        if _CONTROL_PEER_ID is not None and evt.chat_id != _CONTROL_PEER_ID:
            return
        if not _MONITOR_ENABLED or (_MONITOR_CHAT_ID is not None and evt.chat_id != _MONITOR_CHAT_ID):
            return
        if not monitor_buffer or not getattr(monitor_buffer, "pending_batch", None):
            await evt.reply("ℹ️ Немає відкладеного пакету.")
            return
        monitor_buffer.pending_batch = None
        await evt.reply("🛑 Відкладений пакет скасовано.")

    @client.on(events.NewMessage(pattern=r'^/owner_skip$'))
    async def _owner_skip(evt):
        """
        Запустити відкладений пакет без встановлення owner.
        (owner_display / owner_username обнуляємо перед запуском).
        """
        if _CONTROL_PEER_ID is not None and evt.chat_id != _CONTROL_PEER_ID:
            return
        if not monitor_buffer or not getattr(monitor_buffer, "pending_batch", None):
            await evt.reply("ℹ️ Немає відкладеного пакету.")
            return
        pb = monitor_buffer.pending_batch
        if pb.get("processing"):
            await evt.reply("⏳ Пакет уже обробляється.")
            return
        pb["processing"] = True
        monitor_buffer.owner_display = None
        monitor_buffer.owner_username = None
        await evt.reply("▶️ Запускаю обробку без owner...")
        try:
            await process_links(pb["message"], pb["text"])
        except Exception as e:
            log.exception("Deferred batch error (skip): %s", e)
            await evt.reply(f"⚠️ Помилка обробки: {e}")
        finally:
            monitor_buffer.pending_batch = None

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

        # 1) Посилання у тексті
        has_text_link = bool(
            re.search(r"https?://t\.me/", text, flags=re.IGNORECASE)
            or re.search(r"(?:^|\s)@[A-Za-z0-9_]{3,}", text)
        )

        # 2) Приховані посилання у entities
        ents = getattr(msg, "entities", None) or []
        has_entity_link = any(isinstance(e, ttypes.MessageEntityTextUrl) for e in ents)

        # 3) URL у кнопках
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
            pass  # не валимо хендлер на екзотиці

        if not (has_text_link or has_entity_link or has_markup_url):
            return  # не схоже на пакет посилань

        # --- ДОДАНО: екстракція прихованих t.me URL із entities та кнопок ---
        try:
            extra_links = []
            try:
                for e in ents:
                    if isinstance(e, ttypes.MessageEntityTextUrl):
                        u = getattr(e, "url", None)
                        if u and "t.me/" in u.lower():
                            extra_links.append(u.strip())
            except Exception:
                pass
            try:
                if isinstance(markup, (ttypes.ReplyInlineMarkup, ttypes.ReplyKeyboardMarkup)):
                    rows = getattr(markup, "rows", []) or []
                    for row in rows:
                        for btn in getattr(row, "buttons", []) or []:
                            if hasattr(btn, "url"):
                                u = getattr(btn, "url", None)
                                if u and "t.me/" in u.lower():
                                    extra_links.append(u.strip())
            except Exception:
                pass
            if extra_links:
                for u in extra_links:
                    if u not in text:
                        text += "\n" + u
        except Exception:
            pass
        # --- КІНЕЦЬ ДОДАНОГО БЛОКУ ---

        # Відкладене виконання: якщо вже є pending -> просимо завершити/скасувати
        if monitor_buffer and getattr(monitor_buffer, "pending_batch", None):
            await evt.reply(
                "⚠️ Попередній пакет ще очікує owner.\n"
                "Використай /owner_set ... (в іншому плагіні), /owner_skip або /batch_cancel."
            )
            return

        # Витягуємо посилання для кількості (можливі дублікат/фільтр усередині extract_links)
        links = extract_links(text)
        if not links:
            await evt.reply("❌ Не знайшов валідних t.me посилань у цьому повідомленні.")
            return

        # Зберігаємо відкладений пакет
        if monitor_buffer is not None:
            monitor_buffer.pending_batch = {
                "message": msg,
                "text": text,
                "links_count": len(links),
                "created_ts": time.time(),
                "processing": False
            }

        await evt.reply(
            f"📦 Отримав {len(links)} посилань.\n"
    "Введи ім’я або @username (без команди) — і запущу обробку.\n"
    "Або скористайся командами: /owner_set @username чи /owner_set Ім’я,\n"
    "/owner_skip — обробити без owner, /batch_cancel — скасувати."
        )

        # ВАЖЛИВО: НЕ викликаємо process_links тут — чекаємо /owner_set або /owner_skip.

    # воркер черги (логіка без змін)
    try:
        client.loop.create_task(run_link_queue_worker(client))
    except Exception:
        asyncio.create_task(run_link_queue_worker(client))

    log.info("batch_links plugin loaded (deferred-owner mode)")