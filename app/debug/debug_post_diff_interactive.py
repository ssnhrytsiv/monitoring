import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, List, Optional

from telethon import TelegramClient, events
from telethon.tl.types import (
    Message,
    MessageEntityTextUrl,
    MessageEntityUrl,
    MessageEntityCustomEmoji,
)

from app.plugins.posts_watch_listener import _normalize_html_links
from app.services.html_match import exact_html_equal

log = logging.getLogger("two_forwards_html_diff_local")
logging.basicConfig(level=logging.INFO)


@dataclass
class MsgSnapshot:
    msg_id: int
    raw_text: str
    entities: List[dict]
    media_type: str
    media_id: Optional[int]
    reply_markup: Any
    html: str
    html_norm: str


def _entity_repr(text: str, e: Any) -> dict:
    frag = ""
    try:
        frag = text[e.offset : e.offset + e.length]
    except Exception:
        pass

    base = {
        "type": type(e).__name__,
        "offset": getattr(e, "offset", None),
        "length": getattr(e, "length", None),
        "frag": frag,
    }
    if isinstance(e, MessageEntityTextUrl):
        base["url"] = e.url
    if isinstance(e, MessageEntityUrl):
        base["url_frag"] = frag
    if isinstance(e, MessageEntityCustomEmoji):
        base["doc_id"] = getattr(e, "document_id", None)
    return base


def _render_html(msg: Message) -> str:
    """
    Використовуємо той самий пайплайн, що й у posts_watch_listener._init_html_renderer.
    """
    # спроба 1 – post_templates
    try:
        from app.plugins.post_templates import _extract_message_html as _rh  # type: ignore
        return _rh(msg)
    except Exception:
        pass

    # спроба 2 – html_render
    try:
        from app.services.html_render import render_html as _rh2  # type: ignore
        return _rh2(msg)
    except Exception:
        pass

    # fallback – сирий текст як HTML
    txt = getattr(msg, "message", "") or ""
    return txt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _snapshot_from_msg(msg: Message) -> MsgSnapshot:
    raw_text = msg.raw_text or ""

    entities: List[dict] = []
    for e in msg.entities or []:
        entities.append(_entity_repr(raw_text, e))

    media = msg.media
    media_type = type(media).__name__ if media is not None else "None"
    media_id = (
        getattr(getattr(media, "photo", None), "id", None)
        or getattr(getattr(media, "document", None), "id", None)
    )

    html = _render_html(msg) or ""
    html_norm = _normalize_html_links(html)

    return MsgSnapshot(
        msg_id=int(msg.id),
        raw_text=raw_text,
        entities=entities,
        media_type=media_type,
        media_id=media_id,
        reply_markup=msg.reply_markup,
        html=html,
        html_norm=html_norm,
    )


def _print_diff(label: str, a: Any, b: Any):
    if a == b:
        print(f"{label}: OK (identical)")
        return
    print(f"{label}: DIFF")
    print("  A:", repr(a))
    print("  B:", repr(b))


def _print_entities_diff(a: List[dict], b: List[dict]):
    if a == b:
        print("entities: OK (identical)")
        return
    print("entities: DIFF")
    print("  A:", json.dumps(a, ensure_ascii=False, indent=2))
    print("  B:", json.dumps(b, ensure_ascii=False, indent=2))


async def _compare_two(first: MsgSnapshot, second: MsgSnapshot):
    print("=" * 80)
    print(f"==== FIRST  (mid={first.msg_id}) VS SECOND (mid={second.msg_id}) ====")

    print("\n[FIRST raw_text]:")
    print(repr(first.raw_text))
    print("\n[SECOND raw_text]:")
    print(repr(second.raw_text))

    print("\n----- DIFF (plain text) -----")
    _print_diff("raw_text", first.raw_text, second.raw_text)

    print("\n----- DIFF (entities) -----")
    _print_entities_diff(first.entities, second.entities)

    print("\n[FIRST HTML RAW]:")
    print(first.html)
    print("\n[SECOND HTML RAW]:")
    print(second.html)

    print("\n[FIRST HTML NORM]:")
    print(first.html_norm)
    print("\n[SECOND HTML NORM]:")
    print(second.html_norm)

    print("\n----- DIFF (html_norm + exact_html_equal) -----")
    _print_diff("html_norm", first.html_norm, second.html_norm)
    try:
        ok_html = exact_html_equal(first.html_norm, second.html_norm)
    except Exception as e:
        ok_html = False
        print(f"exact_html_equal raised: {e!r}")
    print("exact_html_equal(html_norm):", ok_html)

    print("\n----- DIFF (media / reply_markup) -----")
    _print_diff("media_type", first.media_type, second.media_type)
    _print_diff("media_id", first.media_id, second.media_id)
    _print_diff("reply_markup", first.reply_markup, second.reply_markup)

    print("=" * 80)
    print("Можеш знову надіслати перший пост для нового порівняння.\n")


async def main():
    # TODO: свої дані
    api_id = 23138928
    api_hash = "969a05668d0fd9bff53937329f2c0dd3"
    session = "tg_session_3"

    client = TelegramClient(session, api_id, api_hash)
    await client.start()
    print("Клієнт запущено.")
    print("1) У Telegram відкрий діалог із цим акаунтом.")
    print("2) Перешли (forward) СЮДИ ПЕРШИЙ пост.")
    print("3) Потім перешли (forward) СЮДИ ДРУГИЙ пост.")
    print("   Після другого форварду побачиш diff, включно з html_norm та exact_html_equal.\n")

    state = {"first": None}

    @client.on(events.NewMessage)
    async def handler(evt: events.NewMessage.Event):
        msg = evt.message
        if msg.raw_text and msg.raw_text.startswith("/"):
            return

        try:
            if state["first"] is None:
                state["first"] = msg
                print(f"[INFO] Перший форвард збережено (mid={msg.id}). Тепер надішли другий форвард.\n")
            else:
                first_msg: Message = state["first"]
                second_msg: Message = msg
                state["first"] = None

                print(f"[INFO] Отримано другий форвард (mid={msg.id}). Порівнюю...\n")

                first_snap = _snapshot_from_msg(first_msg)
                second_snap = _snapshot_from_msg(second_msg)
                await _compare_two(first_snap, second_snap)
        except Exception as e:
            log.exception("compare failed: %r", e)
            print(f"[ERROR] {e}\n")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())