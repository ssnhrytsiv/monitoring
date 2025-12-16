# app/services/html_render.py
from __future__ import annotations

import html
from typing import List, Tuple

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

def render_html(msg: Message) -> str:
    """
    Будує HTML із врахуванням entities (жирний, курсив, підкреслення, лінки, код, цитати, спойлери).
    Емодзі зберігаються як є (це звичайні Юнікод-символи).
    Переноси рядків -> <br>.
    """
    text = (getattr(msg, "message", "") or "")
    if not text:
        return ""

    entities = getattr(msg, "entities", None) or []
    # boundaries: список подій відкриття/закриття тегів
    # Кожна подія: (pos, is_close, priority, html)
    # priority робимо так, щоб закриття відбувалось ПЕРЕД відкриттям на тій самій позиції
    opens: List[Tuple[int, int, int, str]] = []
    closes: List[Tuple[int, int, int, str]] = []

    # Заздалегідь збережемо фрагменти для URL-авто
    url_ranges = {}

    for e in entities:
        try:
            off = int(getattr(e, "offset", 0) or 0)
            ln = int(getattr(e, "length", 0) or 0)
            if ln <= 0:
                continue
            start = max(0, off)
            end = max(start, off + ln)
        except Exception:
            continue

        open_tag, close_tag = _tag_for_entity(e)

        # Особливий випадок авто-URL: треба знати сам фрагмент щоб підставити href
        if isinstance(e, MessageEntityUrl):
            frag = text[start:end]
            url_ranges[(start, end)] = frag

        # open: is_close=0; close: is_close=1
        # Для сортування: закриття має пріоритет перед відкриттям (priority: close=0, open=1)
        opens.append((start, 0, 1, open_tag))
        closes.append((end, 1, 0, close_tag))

    events_all = opens + closes
    # Сортуємо: за позицією; далі за is_close (щоб закриття ішло першим); далі за priority
    events_all.sort(key=lambda x: (x[0], x[1], x[2]))

    out = []
    cur = 0
    for pos, is_close, _, tag in events_all:
        pos = max(0, min(len(text), pos))
        if pos > cur:
            out.append(_escape(text[cur:pos]))
            cur = pos

        if tag:
            if is_close:
                out.append(tag)
            else:
                # якщо це авто-URL, треба підставити правильний href (фрагмент від [pos .. next close])
                if tag.startswith("<a href=\"__AUTOURL__\""):
                    # шукаємо відповідне закриття, щоб зрозуміти кінцеву позицію
                    # спростимо: в url_ranges вже є (start,end) для такого шматка
                    # знаходимо range із start==pos
                    end_pos = None
                    for (s, e) in url_ranges.keys():
                        if s == pos:
                            end_pos = e
                            frag = url_ranges[(s, e)]
                            href = html.escape(frag, quote=True)
                            out.append(f"<a href=\"{href}\">")
                            break
                    if end_pos is None:
                        # не знайшли – підставимо пустий href
                        out.append("<a href=\"#\">")
                else:
                    out.append(tag)

    if cur < len(text):
        out.append(_escape(text[cur:]))

    html_out = "".join(out)
    # Переноси рядків => <br>
    html_out = html_out.replace("\n", "<br>")
    return html_out