from __future__ import annotations

import os
import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telethon import TelegramClient

def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v if v is not None else default

@dataclass
class DebouncedProgress:
    """
    Редагує службове повідомлення лише коли є зміни,
    і робить це із затримкою (debounce), щоб не ловити rate-limit.
    """
    client: "TelegramClient" | None
    peer: int | None
    title: str
    total: int
    debounce: float = field(default_factory=lambda: float(_env("PROGRESS_DEBOUNCE", "3")))
    bot: object | None = None
    chat_id: int | None = None

    msg_id: int | None = None

    # counters
    done: int = 0
    ok: int = 0            # joined
    requested: int = 0     # requested (окремо від already)
    already: int = 0
    bad: int = 0           # invalid/private/error/temp/other
    flood: int = 0
    current: str = ""      # current url
    actor: str = ""        # session/slot label
    footer: str = ""       # optional summary

    # internals
    _changed: bool = False
    _pending_task: asyncio.Task | None = None
    _last_render: str = ""
    _closed: bool = False

    # ---- public API ----
    async def start(self) -> None:
        text = self._render(header_suffix="— стартую…")
        if self.bot and self.chat_id:
            m = await self.bot.send_message(self.chat_id, text, link_preview=False)
            self.msg_id = m.message_id
        elif self.client and self.peer is not None:
            m = await self.client.send_message(self.peer, text, link_preview=False)
            self.msg_id = m.id
        self._last_render = text

    def set_current(self, url: str | None = None, actor: str | None = None) -> None:
        if url is not None:
            self.current = url
        if actor is not None:
            self.actor = actor
        self._mark_changed()

    def add_status(self, status: str) -> None:
        """
        status: 'joined' | 'requested' | 'already' | 'invalid' | 'private' | 'error' | 'flood_wait'
        """
        self.done += 1
        if status == "joined":
            self.ok += 1
        elif status == "requested":
            self.requested += 1
        elif status == "already":
            self.already += 1
        elif status == "flood_wait":
            self.flood += 1
        else:
            # все інше (invalid/private/error/temp/blocked/too_many/...) — у bad
            self.bad += 1
        self._mark_changed()

    def set_footer(self, text: str) -> None:
        self.footer = text
        self._mark_changed()

    async def finish(self, footer: str = "") -> None:
        self._closed = True
        if footer:
            self.footer = footer
        if self._pending_task and not self._pending_task.done():
            self._pending_task.cancel()
        await self._edit(final=True)

    # ---- debounce driver ----
    def _mark_changed(self) -> None:
        if self._closed:
            return
        self._changed = True
        if self._pending_task and not self._pending_task.done():
            self._pending_task.cancel()
        self._pending_task = asyncio.create_task(self._debounced_edit())

    async def _debounced_edit(self) -> None:
        try:
            await asyncio.sleep(self.debounce)
        except asyncio.CancelledError:
            return
        if not self._changed:
            return
        await self._edit(final=False)
        self._changed = False

    async def _edit(self, final: bool) -> None:
        if self.msg_id is None:
            return
        hdr_suffix = "— готово ✅" if final else "— обробляю…"
        text = self._render(header_suffix=hdr_suffix, final=final)
        if text == self._last_render:
            return
        try:
            if self.bot and self.chat_id:
                await self.bot.edit_message_text(text=text, chat_id=self.chat_id, message_id=self.msg_id,
                                                 disable_web_page_preview=True)
            elif self.client and self.peer is not None:
                await self.client.edit_message(self.peer, self.msg_id, text, link_preview=False)
            self._last_render = text
        except Exception:
            pass  # не зупиняємо весь процес

    # ---- render ----
    def _render(self, header_suffix: str, final: bool = False) -> str:
        bar = self._bar(self.done, self.total, width=20)
        line_now = ""
        if not final and self.current:
            who = f" • {self.actor}" if self.actor else ""
            line_now = f"\n🔄 Зараз: {self.current}{who}"
        footer = f"\n\n{self.footer}" if self.footer else ""

        return (
            f"📦 <b>{self.title}</b> {header_suffix}\n"
            f"{bar}  {self.done}/{self.total}\n"
            f"✅ <b>Подписался:</b> {self.ok}   🔁 <b>Был подписан:</b> {self.already}\n"
            f"📨 <b>Заявки:</b> {self.requested}\n"
            f"❌ <b>Невалидные/приватные/ошибки:</b> {self.bad}   ⏳ <b>Flood:</b> {self.flood}"
            f"{line_now}{footer}"
        )

    @staticmethod
    def _bar(done: int, total: int, width: int = 20) -> str:
        if total <= 0:
            return "▱" * width
        k = max(0, min(width, round(width * done / total)))
        return "▰" * k + "▱" * (width - k)
