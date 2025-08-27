# app/plugins/progress_live.py
from __future__ import annotations

import os
import asyncio
from dataclasses import dataclass, field

def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v if v is not None else default


@dataclass
class DebouncedProgress:
    """
    «Живе» службове повідомлення з дебаунсом редагувань.
    Текст відправляємо в HTML-режимі; переноси — через '\n'.
    """
    client: "TelegramClient"
    peer: int
    title: str
    total: int
    debounce: float = field(default_factory=lambda: float(_env("PROGRESS_DEBOUNCE", "3")))

    msg_id: int | None = None

    # counters
    done: int = 0
    ok: int = 0          # joined
    already: int = 0
    bad: int = 0         # invalid/private/error
    flood: int = 0
    current: str = ""    # current url
    actor: str = ""      # session/slot label
    footer: str = ""     # optional HTML summary (із fmt_summary)

    # internals
    _changed: bool = False
    _pending_task: asyncio.Task | None = None
    _last_render: str = ""
    _closed: bool = False

    # ---- public API ----
    async def start(self) -> None:
        text = self._render(header_suffix="— стартую…")
        m = await self.client.send_message(
            self.peer,
            text,
            link_preview=False,
            parse_mode="HTML",   # важливо: HTML-режим
        )
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
        status: 'joined' | 'already' | 'invalid' | 'private' | 'error' | 'flood_wait'
        """
        self.done += 1
        if status == "joined":
            self.ok += 1
        elif status == "already":
            self.already += 1
        elif status == "flood_wait":
            self.flood += 1
        else:
            self.bad += 1
        self._mark_changed()

    def set_footer(self, text: str) -> None:
        # text — це HTML з переносами '\n' (наприклад, із fmt_summary)
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
            await self.client.edit_message(
                self.peer,
                self.msg_id,
                text,
                link_preview=False,
                parse_mode="HTML",  # важливо: HTML-режим
            )
            self._last_render = text
        except Exception:
            # не валимо весь процес через помилку редагування
            pass

    # ---- render ----
    def _render(self, header_suffix: str, final: bool = False) -> str:
        bar = self._bar(self.done, self.total, width=20)

        # Верхня частина (рахунки) — звичайний текст із '\n'
        header = (
            f"📦 <b>{self.title}</b> {header_suffix}\n"
            f"{bar}  {self.done}/{self.total}\n"
            f"✔ <b>joined:</b> {self.ok}    "
            f"🔁 <b>already:</b> {self.already}\n"
            f"❌ <b>invalid/private/error:</b> {self.bad}    "
            f"⏳ <b>flood:</b> {self.flood}"
        )

        line_now = ""
        if not final and self.current:
            who = f" • {self.actor}" if self.actor else ""
            line_now = f"\n🔄 Зараз: {self.current}{who}"

        # footer — це HTML-табличка-список, у якій рядки розділені '\n'
        footer = f"\n\n{self.footer}" if self.footer else ""

        # Без <pre> і без <br/> — усе працює через '\n' + parse_mode="HTML"
        return f"{header}{line_now}{footer}"

    @staticmethod
    def _bar(done: int, total: int, width: int = 20) -> str:
        if total <= 0:
            return "▱" * width
        k = max(0, min(width, round(width * done / total)))
        return "▰" * k + "▱" * (width - k)