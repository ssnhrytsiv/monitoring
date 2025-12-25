from __future__ import annotations

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
        self.requested = 0
        self.bad = 0
        self.flood = 0
        self.current = ""
        self.actor = ""
        self.footer = ""
        self.msg_id: int | None = None

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
            f"✅ <b>Подписался:</b> {self.ok}   ☑️ <b>Был подписан:</b> {self.already}\n"
            f"✉️ <b>Заявки:</b> {self.requested}   ❌ <b>Невалидные/ошибки:</b> {self.bad}   ⏳ <b>Flood:</b> {self.flood}"
            f"{line_now}{footer}"
        )

    async def start(self) -> None:
        text = self._render(final=False)
        sent = await self.msg.answer(text, disable_web_page_preview=True)
        self.msg_id = sent.message_id

    async def update(self, status: str, current: str, actor: str | None) -> None:
        s = (status or "").lower()
        self.done += 1
        self.current = current
        self.actor = actor or ""
        if "joined" in s:
            self.ok += 1
        elif "already" in s:
            self.already += 1
        elif "requested" in s:
            self.requested += 1
        elif "flood" in s:
            self.flood += 1
        else:
            self.bad += 1
        if self.msg_id:
            try:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self.msg_id,
                    text=self._render(final=False),
                    disable_web_page_preview=True,
                    parse_mode="HTML",
                )
            except Exception:
                pass

    async def finish(self) -> None:
        if self.msg_id:
            try:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self.msg_id,
                    text=self._render(final=True),
                    disable_web_page_preview=True,
                    parse_mode="HTML",
                )
            except Exception:
                pass
