import logging
from html import escape as _escape
from telethon import events
from telethon.tl import types as ttypes

from app.services.post_watch_db import init as pt_init, add_template, list_templates

log = logging.getLogger("plugin.post_templates")

_CONTROL_PEER_ID = None


def _extract_message_html(msg) -> str:
    """
    Повертає caption/текст як HTML з урахуванням форматування та гіперпосилань.
    Коректно працює з офсетами Telethon (UTF-16) та емодзі.
    """
    from html import escape as _escape
    from telethon.tl import types as ttypes
    from telethon.utils import add_surrogate, del_surrogate

    if not msg:
        return ""
    raw = msg.message or ""
    if not raw:
        return ""

    # Робимо "сурогатний" рядок: індекси = UTF-16 code units, як у entities
    s = add_surrogate(raw)
    n = len(s)

    starts: dict[int, list[str]] = {}
    ends: dict[int, list[str]] = {}

    def add_span(off: int, ln: int, start_tag: str, end_tag: str):
        if off < 0 or ln <= 0:
            return
        starts.setdefault(off, []).append(start_tag)
        ends.setdefault(off + ln, []).append(end_tag)

    entities = getattr(msg, "entities", None) or []
    for e in entities:
        try:
            off = int(getattr(e, "offset", 0))
            ln  = int(getattr(e, "length", 0))

            if isinstance(e, ttypes.MessageEntityBold):
                add_span(off, ln, "<b>", "</b>")
            elif isinstance(e, ttypes.MessageEntityItalic):
                add_span(off, ln, "<i>", "</i>")
            elif isinstance(e, ttypes.MessageEntityUnderline):
                add_span(off, ln, "<u>", "</u>")
            elif isinstance(e, ttypes.MessageEntityStrike):
                add_span(off, ln, "<s>", "</s>")
            elif isinstance(e, ttypes.MessageEntitySpoiler):
                add_span(off, ln, '<span class="tg-spoiler">', "</span>")
            elif isinstance(e, ttypes.MessageEntityCode):
                add_span(off, ln, "<code>", "</code>")
            elif isinstance(e, ttypes.MessageEntityPre):
                lang = getattr(e, "language", None)
                lang_attr = f' language="{_escape(lang)}"' if lang else ""
                add_span(off, ln, f"<pre{lang_attr}>", "</pre>")
            elif isinstance(e, ttypes.MessageEntityTextUrl):
                href = _escape(getattr(e, "url", "") or "", quote=True)
                add_span(off, ln, f'<a href="{href}">', "</a>")
            elif isinstance(e, ttypes.MessageEntityUrl):
                vis = _escape(del_surrogate(s[off:off+ln]), quote=True)
                add_span(off, ln, f'<a href="{vis}">', "</a>")
            elif isinstance(e, ttypes.MessageEntityMention):
                uname = del_surrogate(s[off+1:off+ln])
                add_span(off, ln, f'<a href="https://t.me/{_escape(uname, True)}">', "</a>")
            elif isinstance(e, ttypes.MessageEntityMentionName):
                uid = getattr(e, "user_id", None)
                if uid is not None:
                    add_span(off, ln, f'<a href="tg://user?id={uid}">', "</a>")
            elif isinstance(e, ttypes.MessageEntityHashtag):
                tag = del_surrogate(s[off+1:off+ln])
                add_span(off, ln, f'<a href="https://t.me/s/{_escape(tag, True)}">', "</a>")
            elif isinstance(e, ttypes.MessageEntityCashtag):
                tag = del_surrogate(s[off+1:off+ln])
                add_span(off, ln, f'<a href="https://t.me/s/${_escape(tag, True)}">', "</a>")
            elif isinstance(e, ttypes.MessageEntityEmail):
                piece = del_surrogate(s[off:off+ln])
                add_span(off, ln, f'<a href="mailto:{_escape(piece, True)}">', "</a>")
            elif isinstance(e, ttypes.MessageEntityPhone):
                piece = del_surrogate(s[off:off+ln])
                add_span(off, ln, f'<a href="tel:{_escape(piece, True)}">', "</a>")
            elif isinstance(e, ttypes.MessageEntityCustomEmoji):
                ce_id = getattr(e, "document_id", None)
                if ce_id is not None:
                    add_span(off, ln, f'<span data-custom-emoji-id="{ce_id}">', "</span>")
        except Exception:
            continue

    # Допоміжні перевірки сурогатів
    def _is_high(c: str) -> bool:
        o = ord(c)
        return 0xD800 <= o <= 0xDBFF

    def _is_low(c: str) -> bool:
        o = ord(c)
        return 0xDC00 <= o <= 0xDFFF

    out_parts: list[str] = []
    i = 0
    while i < n:
        # Відкриваємо теги, що починаються на позиції i
        if i in starts:
            out_parts.extend(starts[i])

        # Додаємо один видимий символ: або BMP, або пара сурогатів
        if _is_high(s[i]) and i + 1 < n and _is_low(s[i + 1]):
            piece = s[i:i+2]             # пара
            vis = del_surrogate(piece)
            out_parts.append(_escape(vis))
            end_index = i + 2
            i += 2
        else:
            # звичайний символ або низький сурогат (рідко зустрічається — все одно відрендериться)
            vis = del_surrogate(s[i])
            out_parts.append(_escape(vis))
            end_index = i + 1
            i += 1

        # Закриваємо теги, що закінчуються ПІСЛЯ символа
        if end_index in ends:
            for tag in reversed(ends[end_index]):
                out_parts.append(tag)

    return "".join(out_parts)

def setup(client, control_peer=None, **kwargs):
    global _CONTROL_PEER_ID
    _CONTROL_PEER_ID = control_peer

    pt_init()
    log.info("post_templates: setup(control_peer=%s)", control_peer)

    @client.on(events.NewMessage(pattern=r"^/add_post_template(?:\s+(exact|fuzzy)(?:\s+([01](?:\.\d+)?))?)?$"))
    async def _add_tmpl(evt):
        if _CONTROL_PEER_ID is not None and evt.chat_id != _CONTROL_PEER_ID:
            return

        if not evt.is_reply:
            await evt.reply(
                "ℹ️ Відповідайте командою на повідомлення з постом (картинка + опис або просто текст).\n"
                "Приклади:\n"
                "• /add_post_template\n"
                "• /add_post_template exact\n"
                "• /add_post_template fuzzy 0.70",
                parse_mode="html"
            )
            return

        src = await evt.get_reply_message()
        text_html = _extract_message_html(src)
        if not text_html:
            await evt.reply("❌ Не знайшов текст/опис у повідомленні (caption).", parse_mode="html")
            return

        mode = "exact"
        threshold = 1.0
        try:
            m = evt.pattern_match
            if m and m.group(1):
                mode = m.group(1).lower()
            if mode not in ("exact", "fuzzy"):
                mode = "exact"
            if mode == "fuzzy":
                threshold = 0.70
                if m and m.group(2):
                    threshold = float(m.group(2))
        except Exception:
            mode = "exact"
            threshold = 1.0

        try:
            # Зберігаємо готовий HTML (з форматуванням і гіперпосиланнями)
            tid = add_template(text_html, mode=mode, threshold=threshold)
        except Exception as e:
            log.exception("add_template failed: %s", e)
            await evt.reply(f"⚠️ Помилка збереження: {e}", parse_mode="html")
            return

        nice = "exact" if mode == "exact" else f"fuzzy (поріг {threshold:.2f})"
        # Підтвердження
        await evt.reply(f"✅ Зразок поста додано (id={tid}, режим {nice}).", parse_mode="html")

        # Повторне повне відтворення (медіа + HTML)
        try:
            if getattr(src, "media", None) and (getattr(src, "photo", None) or getattr(src, "document", None)):
                await client.send_file(
                    evt.chat_id,
                    src.media,
                    caption=text_html,           # HTML caption
                    parse_mode="html",
                    force_document=False
                )
            else:
                await client.send_message(
                    evt.chat_id,
                    text_html,
                    parse_mode="html"
                )
        except Exception as e:
            log.warning("Не вдалося відтворити пост: %s", e)

    @client.on(events.NewMessage(pattern=r"^/list_post_templates$"))
    async def _list(evt):
        if _CONTROL_PEER_ID is not None and evt.chat_id != _CONTROL_PEER_ID:
            return
        rows = list_templates(20)
        if not rows:
            await evt.reply("Поки що немає збережених зразків постів.", parse_mode="html")
            return
        await evt.reply("📚 Останні зразки постів (повністю):", parse_mode="html")
        for (tid, text, mode, thr, ts) in rows:
            extra = f"{mode}{' '+str(round(thr,2)) if mode=='fuzzy' else ''}"
            header = f"<b>#{tid}</b> <i>{extra}</i>\n\n"
            try:
                await client.send_message(evt.chat_id, header + text, parse_mode="html")
            except Exception as e:
                log.warning("Не вдалося відправити шаблон #%s: %s", tid, e)

    log.info("post_templates plugin loaded")