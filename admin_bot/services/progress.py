from __future__ import annotations

import asyncio
import time

from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import Message


class Progress:
    """
    Легкий прогрес-бар для адмін-бота: показує бар, лічильники і поточний лінк/сесію.
    """

    def __init__(self, message: Message, total: int) -> None:
        self.msg = message
        self.bot = message.bot
        self.chat_id = message.chat.id
        self.total = total
        self.done = 0
        self.ok = 0
        self.already = 0
        self.left = 0
        self.requested = 0
        self.bad = 0
        self.flood = 0
        self.duplicates = 0
        self.current = ""
        self.actor = ""
        self.footer = ""
        self.msg_id: int | None = None
        self._last_sent_at: float | None = None
        self._last_text: str = ""

    @staticmethod
    def _bar(done: int, total: int, width: int = 20) -> str:
        if total <= 0:
            return "▱" * width
        k = max(0, min(width, round(width * done / total)))
        return "▰" * k + "▱" * (width - k)

    def _render(self, final: bool = False) -> str:
        bar = self._bar(self.done, self.total, width=20)
        line_now = ""
        if not final and self.current:
            who = f" • {self.actor}" if self.actor else ""
            line_now = f"\n🔄 Зараз: {self.current}{who}"
        footer = f"\n\n{self.footer}" if self.footer else ""
        return (
            f"📦 <b>Пакет посилань</b>\n"
            f"{bar}  {self.done}/{self.total}\n"
            f"✅ <b>Подписался:</b> {self.ok}   ☑️ <b>Был подписан:</b> {self.already}   ↩️ <b>Отписался:</b> {self.left}\n"
            f"✉️ <b>Заявки:</b> {self.requested}   ❌ <b>Невалидные/ошибки:</b> {self.bad}   ⏳ <b>Flood:</b> {self.flood}   🔁 <b>Дубликаты:</b> {self.duplicates}"
            f"{line_now}{footer}"
        )

    async def start(self) -> None:
        text = self._render(final=False)
        attempts = 2
        for attempt in range(attempts):
            try:
                sent = await self.msg.answer(text, disable_web_page_preview=True)
                self.msg_id = sent.message_id
                self._last_sent_at = time.monotonic()
                self._last_text = text
                return
            except TelegramRetryAfter as e:
                delay = max(1, int(getattr(e, "retry_after", 0)) or 1)
                if attempt + 1 >= attempts:
                    return
                await asyncio.sleep(delay + 0.5)

    async def update(self, status: str, current: str, actor: str | None) -> None:
        s = (status or "").lower()
        self.done += 1
        self.current = current
        self.actor = actor or ""
        if "duplicate" in s:
            self.duplicates += 1
        elif "joined" in s:
            self.ok += 1
        elif "already" in s:
            self.already += 1
        elif "left" in s or "отпис" in s or "unsubscribe" in s:
            self.left += 1
        elif "requested" in s:
            self.requested += 1
        elif "flood" in s or "wait of" in s:
            self.flood += 1
        else:
            self.bad += 1
        if self.msg_id:
            text = self._render(final=False)
            now = time.monotonic()
            if text == self._last_text:
                return
            if self._last_sent_at is not None and (now - self._last_sent_at) < 5:
                return
            try:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self.msg_id,
                    text=text,
                    disable_web_page_preview=True,
                    parse_mode="HTML",
                )
                self._last_text = text
                self._last_sent_at = now
            except Exception:
                pass

    async def finish(self) -> None:
        if self.msg_id:
            try:
                text = self._render(final=True)
                await self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self.msg_id,
                    text=text,
                    disable_web_page_preview=True,
                    parse_mode="HTML",
                )
                self._last_text = text
                self._last_sent_at = time.monotonic()
            except Exception:
                pass
