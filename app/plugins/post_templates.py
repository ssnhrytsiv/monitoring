import logging
import json
import os
import re
from html import escape as _escape
from telethon import events
from telethon.tl import types as ttypes
from telethon.utils import add_surrogate, del_surrogate

from app.DAL.post_templates_operations import add_template, list_templates

log = logging.getLogger("plugin.post_templates")

_CONTROL_PEER_ID = None

# --------- META (звідки брати медіа оригіналу) ---------
_META_PATH = "data/post_templates_meta.json"
_meta_cache = None

def _load_meta():
    global _meta_cache
    if _meta_cache is not None:
        return _meta_cache
    if not os.path.exists(_META_PATH):
        _meta_cache = {}
        return _meta_cache
    try:
        with open(_META_PATH, "r", encoding="utf-8") as f:
            _meta_cache = json.load(f)
    except Exception:
        _meta_cache = {}
    return _meta_cache

def _save_meta():
    if _meta_cache is None:
        return
    os.makedirs(os.path.dirname(_META_PATH), exist_ok=True)
    tmp = _META_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_meta_cache, f, ensure_ascii=False)
    os.replace(tmp, _META_PATH)

def _record_meta(tid: int, chat_id: int, message_id: int, has_media: bool):
    meta = _load_meta()
    meta[str(tid)] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "has_media": bool(has_media),
    }
    _save_meta()

# --------- Витяг посилань ---------
_LINK_RE = re.compile(
    r'(?i)\b((?:https?://|tg://|t\.me/)[^\s<>"\'\]\)]+)'
)

def _collect_links(msg, html_text: str) -> list:
    links = []
    seen = set()
    raw = msg.message or ""
    entities = getattr(msg, "entities", None) or []
    for e in entities:
        try:
            if isinstance(e, ttypes.MessageEntityTextUrl):
                u = getattr(e, "url", "") or ""
                if u and u not in seen:
                    seen.add(u)
                    links.append(u)
            elif isinstance(e, ttypes.MessageEntityUrl):
                off = int(getattr(e, "offset", 0))
                ln = int(getattr(e, "length", 0))
                piece = raw[off:off+ln].strip()
                if piece and piece not in seen:
                    seen.add(piece)
                    links.append(piece)
        except Exception:
            continue
    for m in _LINK_RE.finditer(raw):
        u = m.group(1)
        if u and u not in seen:
            seen.add(u)
            links.append(u)
    for m in _LINK_RE.finditer(html_text):
        u = m.group(1)
        if u and u not in seen:
            seen.add(u)
            links.append(u)
    return links

# --------- Витяг заголовка (автоматичний) ---------
_TAG_RE = re.compile(r"<[^>]+>")

def _extract_title(html_text: str) -> str:
    plain = _TAG_RE.sub("", html_text)
    plain = plain.replace("&nbsp;", " ")
    lines = [l.strip() for l in plain.splitlines()]
    first = ""
    for l in lines:
        if l:
            first = l
            break
    candidate = first or plain.strip()
    candidate = candidate[:80].strip()
    return candidate or None

# --------- HTML екстракція ---------
def _extract_message_html(msg) -> str:
    if not msg:
        return ""
    raw = msg.message or ""
    if not raw:
        return ""
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

    def _is_high(c: str) -> bool:
        o = ord(c)
        return 0xD800 <= o <= 0xDBFF
    def _is_low(c: str) -> bool:
        o = ord(c)
        return 0xDC00 <= o <= 0xDFFF

    out_parts: list[str] = []
    i = 0
    while i < n:
        if i in starts:
            out_parts.extend(starts[i])
        if _is_high(s[i]) and i + 1 < n and _is_low(s[i + 1]):
            piece = s[i:i+2]
            vis = del_surrogate(piece)
            out_parts.append(_escape(vis))
            end_index = i + 2
            i += 2
        else:
            vis = del_surrogate(s[i])
            out_parts.append(_escape(vis))
            end_index = i + 1
            i += 1
        if end_index in ends:
            for tag in reversed(ends[end_index]):
                out_parts.append(tag)
    return "".join(out_parts)

# --------- Парсер аргументів /add_post_template з підтримкою «…» або "…" ---------
def _parse_add_args(arg_str: str):
    """
    Допускає синтаксис:
      /add_post_template
      /add_post_template exact
      /add_post_template fuzzy 0.7
      /add_post_template «Мій заголовок»
      /add_post_template «Мій заголовок» fuzzy 0.72
      /add_post_template «Мій заголовок» exact
      /add_post_template "Мій заголовок" fuzzy 0.72
    Повертає (title_explicit_or_None, mode_or_None, threshold_or_None)
    """
    if not arg_str:
        return None, None, None
    rest = arg_str.strip()
    title = None

    if rest:
        first = rest[0]
        if first in ('«', '"'):
            if first == '«':
                closer = '»'
                allow_escape = False
            else:
                closer = '"'
                allow_escape = True
            i = 1
            buf = []
            closed = False
            while i < len(rest):
                ch = rest[i]
                if allow_escape and ch == '\\' and i + 1 < len(rest):
                    buf.append(rest[i+1])
                    i += 2
                    continue
                if ch == closer:
                    closed = True
                    i += 1
                    break
                buf.append(ch)
                i += 1
            if closed:
                title_candidate = "".join(buf).strip()
                title = title_candidate or None
                while i < len(rest) and rest[i].isspace():
                    i += 1
                rest = rest[i:]

    tokens = rest.split() if rest else []
    mode = None
    thr = None
    if tokens:
        if tokens[0].lower() in ("exact", "fuzzy"):
            mode = tokens[0].lower()
            tokens = tokens[1:]
            if mode == "fuzzy" and tokens:
                try:
                    thr = float(tokens[0])
                except Exception:
                    thr = None
    return title, mode, thr

# --------- SETUP ---------
def setup(client, control_peer=None, **kwargs):
    global _CONTROL_PEER_ID
    _CONTROL_PEER_ID = control_peer

    log.info("post_templates: setup(control_peer=%s)", control_peer)

    log.info("post_templates plugin loaded")
