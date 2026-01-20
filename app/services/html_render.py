# app/services/html_render.py
from __future__ import annotations

import html
import re
from typing import Any, Iterable, List, Tuple

from telethon.tl.types import (
    Message,
    MessageEntityBold,
    MessageEntityItalic,
    MessageEntityUnderline,
    MessageEntityStrike,
    MessageEntityCode,
    MessageEntityPre,
    MessageEntityBlockquote,
    MessageEntitySpoiler,
    MessageEntityTextUrl,
    MessageEntityUrl,
    MessageEntityMentionName,
)

def _escape(s: str) -> str:
    return html.escape(s, quote=False)

def _tag_for_entity(e) -> Tuple[str, str]:
    """
    Повертає (open_tag, close_tag) для сутності.
    """
    if isinstance(e, MessageEntityBold):
        return "<b>", "</b>"
    if isinstance(e, MessageEntityItalic):
        return "<i>", "</i>"
    if isinstance(e, MessageEntityUnderline):
        return "<u>", "</u>"
    if isinstance(e, MessageEntityStrike):
        return "<s>", "</s>"
    if isinstance(e, MessageEntityCode):
        return "<code>", "</code>"
    if isinstance(e, MessageEntityPre):
        return "<pre>", "</pre>"
    if isinstance(e, MessageEntityBlockquote):
        return "<blockquote>", "</blockquote>"
    if isinstance(e, MessageEntitySpoiler):
        return "<span class=\"tg-spoiler\">", "</span>"
    if isinstance(e, MessageEntityTextUrl):
        href = html.escape(e.url or "", quote=True)
        return f"<a href=\"{href}\">", "</a>"
    if isinstance(e, MessageEntityUrl):
        # Сам текст містить URL; просто обгортаємо його <a href="...">
        # Сам href підставимо при побудові (бо потрібен сам фрагмент тексту).
        return "<a href=\"__AUTOURL__\">", "</a>"
    if isinstance(e, MessageEntityMentionName):
        # посилання на користувача
        href = f"tg://user?id={int(getattr(e, 'user_id', 0) or 0)}"
        href = html.escape(href, quote=True)
        return f"<a href=\"{href}\">", "</a>"
    # за замовчуванням – без тегів
    return "", ""

def _tag_for_generic_entity(e: Any) -> Tuple[str, str]:
    """
    Дає open/close тег для сутності (Telethon або Aiogram).
    Працює через duck-typing: для Aiogram використовує .type, для Telethon — isinstance.
    """
    etype = getattr(e, "type", None)

    # Aiogram string-based types
    if isinstance(etype, str):
        t = etype.lower()
        if t == "bold":
            return "<b>", "</b>"
        if t == "italic":
            return "<i>", "</i>"
        if t in {"underline", "text_underline"}:
            return "<u>", "</u>"
        if t in {"strikethrough", "text_strikethrough"}:
            return "<s>", "</s>"
        if t in {"spoiler"}:
            return '<span class="tg-spoiler">', "</span>"
        if t in {"code"}:
            return "<code>", "</code>"
        if t in {"pre"}:
            return "<pre>", "</pre>"
        if t in {"blockquote"}:
            return "<blockquote>", "</blockquote>"
        if t == "text_link":
            href = html.escape(getattr(e, "url", "") or "", quote=True)
            return f'<a href="{href}">', "</a>"
        if t in {"url"}:
            return '<a href="__AUTOURL__">', "</a>"
        if t in {"text_mention"}:
            uid = getattr(e, "user", None)
            uid_val = None
            if uid is not None:
                uid_val = getattr(uid, "id", None)
            uid_val = uid_val if uid_val is not None else getattr(e, "user_id", None)
            href = f"tg://user?id={int(uid_val or 0)}"
            return f'<a href="{html.escape(href, quote=True)}">', "</a>"

    # Telethon classes (fallback)
    try:
        return _tag_for_entity(e)
    except Exception:
        return "", ""


def render_html_generic(text: str, entities: Iterable[Any] | None = None) -> str:
    """
    Побудова HTML з plain-text + колекції сутностей (Telethon або Aiogram).
    """
    txt = text or ""
    ents = list(entities or [])
    if not txt:
        return ""

    opens: List[Tuple[int, int, int, str]] = []
    closes: List[Tuple[int, int, int, str]] = []
    url_ranges = {}

    for e in ents:
        try:
            off = int(getattr(e, "offset", 0) or 0)
            ln = int(getattr(e, "length", 0) or 0)
            if ln <= 0:
                continue
            start = max(0, off)
            end = max(start, off + ln)
        except Exception:
            continue

        open_tag, close_tag = _tag_for_generic_entity(e)
        # Особливий випадок авто-URL
        if (isinstance(getattr(e, "type", None), str) and getattr(e, "type").lower() == "url") or isinstance(e, MessageEntityUrl):
            frag = txt[start:end]
            url_ranges[(start, end)] = frag

        opens.append((start, 0, 1, open_tag))
        closes.append((end, 1, 0, close_tag))

    events_all = opens + closes
    events_all.sort(key=lambda x: (x[0], x[1], x[2]))

    out = []
    cur = 0
    for pos, is_close, _, tag in events_all:
        pos = max(0, min(len(txt), pos))
        if pos > cur:
            out.append(_escape(txt[cur:pos]))
            cur = pos

        if tag:
            if is_close:
                out.append(tag)
            else:
                if tag.startswith('<a href="__AUTOURL__"'):
                    end_pos = None
                    for (s, e) in url_ranges.keys():
                        if s == pos:
                            end_pos = e
                            frag = url_ranges[(s, e)]
                            href = html.escape(frag, quote=True)
                            out.append(f'<a href="{href}">')
                            break
                    if end_pos is None:
                        out.append('<a href="#">')
                else:
                    out.append(tag)

    if cur < len(txt):
        out.append(_escape(txt[cur:]))

    html_out = "".join(out)
    html_out = html_out.replace("\n", "<br>")
    html_out = re.sub(r"\s+(</(?:b|i|u|s|code|pre|blockquote|span|a)>)", r"\1", html_out, flags=re.IGNORECASE)
    return html_out


def render_html_from_aiogram(msg: Any) -> str:
    """
    Рендер для aiogram-повідомлення через універсальний рендер.
    """
    text = (getattr(msg, "text", None) or getattr(msg, "caption", None) or "") or ""
    entities = getattr(msg, "entities", None) or getattr(msg, "caption_entities", None) or []
    return render_html_generic(text, entities)


def render_html(msg: Any) -> str:
    """
    Єдиний публічний рендер: приймає або Telethon Message, або Aiogram Message,
    підтягує текст/ентіті й будує HTML через render_html_generic.
    """
    # Telethon Message: .message + .entities
    if isinstance(msg, Message):
        text = (getattr(msg, "message", "") or "")
        entities = getattr(msg, "entities", None) or []
        return render_html_generic(text, entities)

    # Aiogram-like
    text = (getattr(msg, "text", None) or getattr(msg, "caption", None) or "") or ""
    entities = getattr(msg, "entities", None) or getattr(msg, "caption_entities", None) or []
    return render_html_generic(text, entities)
