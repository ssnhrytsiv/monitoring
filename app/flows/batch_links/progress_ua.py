from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import List, Optional

from telethon import TelegramClient


def _esc(s: str) -> str:
    if not s:
        return ""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )


@dataclass
class DebouncedProgressUA:
    """
    «Живе» повідомлення з дебаунсом для пакетної обробки посилань.
    """
    client: TelegramClient
    chat_id: int
    message_id: int
    debounce_sec: float = 3.0

    processed: int = 0
    total: int = 0
    count_joined: int = 0
    count_already: int = 0
    count_bad: int = 0
    count_flood: int = 0

    flood_sleep_left: Optional[int] = None
    flood_session_name: Optional[str] = None

    tail_lines: List[str] = field(default_factory=list)
    _last_push_ts: float = 0.0

    def set_total(self, n: int) -> None:
        self.total = max(0, int(n))

    def step_processed(self, inc: int = 1) -> None:
        self.processed = min(self.total, self.processed + max(1, int(inc)))

    def bump(self, kind: str) -> None:
        if kind == "joined":
            self.count_joined += 1
        elif kind == "already":
            self.count_already += 1
        elif kind in ("invalid", "private", "error"):
            self.count_bad += 1
        elif kind == "flood":
            self.count_flood += 1

    def set_flood_sleep(self, seconds: int, session_name: Optional[str] = None) -> None:
        self.flood_sleep_left = max(0, int(seconds))
        self.flood_session_name = session_name or None

    def clear_flood_sleep(self) -> None:
        self.flood_sleep_left = None
        self.flood_session_name = None

    def append_tail(self, line: str) -> None:
        self.tail_lines.append(line)
        if len(self.tail_lines) > 12:
            self.tail_lines.pop(0)

    async def push_now(self) -> None:
        txt = self._render_html()
        await self.client.edit_message(self.chat_id, self.message_id, txt, parse_mode="html")
        self._last_push_ts = time.time()

    async def push_debounced(self) -> None:
        now = time.time()
        if now - self._last_push_ts >= self.debounce_sec:
            await self.push_now()

    def _render_html(self) -> str:
        head = (
            "📦 <b>Пакет посилань</b> — "
            f"{'обробляю…' if self.processed < self.total else 'готово ✅'}\n"
            f"{self._progress_bar()}  {self.processed}/{self.total}\n"
        )
        flood = ""
        if self.flood_sleep_left is not None:
            who = f" — {self._mono(self.flood_session_name)}" if self.flood_session_name else ""
            flood = f"⏳ <i>Сплю {self.flood_sleep_left} с{who}</i>\n"

        stats = (
            f"✅ <b>підписано:</b> {self.count_joined}    "
            f"🔁 <b>вже підписані:</b> {self.count_already}    "
            f"❌ <b>невалідні/приватні/помилка:</b> {self.count_bad}    "
            f"⏳ <b>flood:</b> {self.count_flood}\n"
        )

        tail = ""
        if self.tail_lines:
            tail = "\n🧾 <b>Підсумок (останні):</b>\n<pre>" + "\n".join(self.tail_lines) + "</pre>"

        return head + flood + stats + tail

    def _progress_bar(self, width: int = 24) -> str:
        total = max(1, self.total)
        done = min(total, self.processed)
        fill = int(width * done / total)
        return "▰" * fill + "▱" * max(0, width - fill)

    @staticmethod
    def _mono(s: Optional[str]) -> str:
        return f"<code>{_esc(s or '')}</code>"