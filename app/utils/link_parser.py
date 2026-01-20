from __future__ import annotations
import re
from typing import Iterable, List, Union, Any
from urllib.parse import SplitResult, urlsplit, urlunsplit
import html as _html_mod

try:
    # Імпортимо типи тільки якщо є telethon (щоб утиліта жила і без нього)
    from telethon.tl import types as tg_types
    from telethon.tl.custom.message import Message as TgMessage
except Exception:  # pragma: no cover
    tg_types = None
    TgMessage = None  # type: ignore

try:
    from aiogram.types import Message as AiogramMessage  # type: ignore
except Exception:  # pragma: no cover
    AiogramMessage = None  # type: ignore

# --- Регулярки ---
# 1) Markdown: [label](https://t.me/...)
RE_MD_TG = re.compile(
    r"\[[^\]]+\]\(\s*(https?://t\.me/[^\s)]+)\s*\)",
    re.IGNORECASE,
)

# 2) HTML: <a href="https://t.me/..."> або одинарні лапки
RE_HTML_TG = re.compile(
    r"""<a\s+[^>]*href\s*=\s*(['"])(https?://t\.me/[^'"]+)\1""",
    re.IGNORECASE,
)

# 3) Сирі лінки та @username
#    група 1 — повний t.me-URL, група 2 — @username
RE_TG_RAW = re.compile(
    r"((?:https?://)?t\.me/[^\s<>'\")]+)|(@[A-Za-z0-9_]{3,})",
    re.IGNORECASE,
)

# Допоміжне: прибрати невидимі символи/окантовку і «хвости» пунктуації
_INVIS = ("\u200b", "\u200e", "\u200f")
_TRAIL_PUNCT = ".,;:)]}>"
_AI0G_LINK_RE = re.compile(r"(?i)\b((?:https?://|tg://|t\.me/)[^\s<>'\"\\]+)")
_AI0G_MENTION_RE = re.compile(r"@[\w\d_]{4,}")


def _clean(s: str) -> str:
    if not s:
        return s
    for ch in _INVIS:
        s = s.replace(ch, "")
    s = s.strip()
    # зняти зовнішні дужки, якщо вони «обгортають» лінк
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    # прибрати типові «хвости» пунктуації
    while s and s[-1] in _TRAIL_PUNCT:
        s = s[:-1]
    return s


def normalize(url: str) -> str:
    """
    Приводить url до стабільної форми:
    - видаляє невидимі символи та зайву окантовку
    - перетворює @username -> https://t.me/username
    - додає https:// якщо немає схеми / або починається з t.me/
    """
    url = _clean(url)

    if not url:
        return url

    if url.startswith("@"):
        return f"https://t.me/{url[1:]}"

    if url.startswith("t.me/"):
        return f"https://{url}"

    if not url.startswith("http"):
        return f"https://{url}"

    return url


def sanitize_link(u: str) -> str:
    """
    Нормалізує/«лікує» URL:
      - виправляє типові опечатки у схемі: tps://, htps://, https//, http//
      - tg://resolve?domain=foo  ->  https://t.me/foo
      - @username                ->  https://t.me/username
      - t.me/... без схеми       ->  https://t.me/...
      - прибирає «подвійну схему»: https://https://t.me/...
      - для t.me завжди ставить HTTPS
    Повертає стабільний рядок. Якщо не вдалось розпарсити — повертає виправлене «як є».
    """
    s = (u or "").strip()
    if not s:
        return s

    low = s.lower()

    # 1) tg://resolve?domain=foo -> https://t.me/foo
    if low.startswith("tg://resolve?domain="):
        name = s.split("=", 1)[-1].split("&", 1)[0].lstrip("@").strip()
        if name:
            s = f"https://t.me/{name}"
            low = s.lower()

    # 2) @username -> https://t.me/username
    if s.startswith("@"):
        s = f"https://t.me/{s[1:].strip()}"
        low = s.lower()

    # 3) Найчастіші опечатки/усічення схеми на початку
    fixes = (
        ("https//", "https://"),
        ("http//", "http://"),
        ("tps://", "https://"),
        ("htps://", "https://"),
        ("ttps://", "https://"),
        ("ps://", "https://"),
        ("s://", "https://"),
    )
    for bad, good in fixes:
        if s.startswith(bad):
            s = good + s[len(bad):]
            low = s.lower()
            break

    # 4) t.me/... без схеми -> https://t.me/...
    if low.startswith("t.me/"):
        s = "https://" + s
        low = s.lower()

    # 5) Прибрати «подвійну схему»: https://https://t.me/...
    m = re.match(r"^([a-zA-Z][a-zA-Z0-9+\-.]*://)(.+)$", s)
    if m:
        scheme = m.group(1)
        rest = re.sub(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", "", m.group(2))
        s = scheme + rest
        low = s.lower()

    # 6) Розбір URL та фінальне доведення до ладу
    try:
        p = urlsplit(s)
    except Exception:
        return s  # як є, якщо дуже криво

    if not p.scheme:
        s = "https://" + s.lstrip("/")
        p = urlsplit(s)

    if not p.netloc and p.path.startswith("t.me/"):
        s = "https://" + p.path
        p = urlsplit(s)

    if p.netloc.lower() == "t.me" and p.scheme != "https":
        p = SplitResult("https", p.netloc, p.path, p.query, p.fragment)

    return urlunsplit(p)


def extract_bot_username(u: str) -> str | None:
    """
    Витягує username бота, якщо посилання/рядок веде на бот (закінчується на bot/_bot).
    Повертає None, якщо не схоже на бота.
    """
    s = (u or "").strip()
    if not s:
        return None

    try:
        norm = sanitize_link(s)
    except Exception:
        norm = s

    if norm.startswith("@"):
        username = norm.lstrip("@")
    else:
        try:
            p = urlsplit(norm)
        except Exception:
            p = None
        if p and p.netloc.lower() in ("t.me", "telegram.me", "telegram.dog"):
            username = p.path.lstrip("/").split("?", 1)[0]
        else:
            username = None

    if not username:
        return None

    username = username.strip().strip(".,;:)]}>\"'")
    if not username:
        return None

    low = username.lower()
    if low.endswith("bot") or low.endswith("_bot"):
        return username
    return None


def is_invite(url: str) -> bool:
    """
    Швидка перевірка: чи є лінк інвайтом (з +hash або joinchat).
    """
    u = (url or "").lower()
    return ("/+" in u) or ("joinchat/" in u)


def extract_links(text: str) -> List[str]:
    """
    Витягує t.me посилання з довільного ТЕКСТУ (regex):
      • Markdown: [label](https://t.me/...)
      • HTML: <a href="https://t.me/...">
      • Сирі: https://t.me/..., t.me/..., @username

    Повертає список нормалізованих URL у форматі 'https://t.me/...'
    (для @username — 'https://t.me/<name>'), без дублікатів, у вихідному порядку.
    """
    if not text:
        return []

    candidates: List[str] = []

    # 1) Markdown
    for m in RE_MD_TG.finditer(text):
        candidates.append(m.group(1))

    # 2) HTML
    for m in RE_HTML_TG.finditer(text):
        candidates.append(m.group(2))

    # 3) Сирі URL/username
    for m in RE_TG_RAW.finditer(text):
        if m.group(1):  # повний t.me-URL
            candidates.append(m.group(1).strip())
        elif m.group(2):  # @username
            candidates.append(m.group(2))

    # Нормалізувати та прибрати дублі, зберігаючи порядок
    seen = set()
    out: List[str] = []
    for c in candidates:
        u = normalize(c)
        if not u:
            continue
        if u not in seen:
            out.append(u)
            seen.add(u)

    return out


def _extract_from_entities(text: str, entities: Iterable) -> List[str]:
    """
    Витягує t.me посилання із Telegram entities:
      • MessageEntityTextUrl: беремо e.url
      • MessageEntityUrl: беремо фрагмент тексту за offset/length
      • MessageEntityMention: '@name' -> https://t.me/name
    """
    if tg_types is None or not entities:
        return []

    links: List[str] = []
    for e in entities:
        try:
            if isinstance(e, tg_types.MessageEntityTextUrl):
                links.append(e.url)
            elif isinstance(e, tg_types.MessageEntityUrl):
                frag = text[e.offset : e.offset + e.length]
                links.append(frag)
            elif isinstance(e, tg_types.MessageEntityMention):
                frag = text[e.offset : e.offset + e.length]
                links.append(frag)  # це @username — normalize перетворить
        except Exception:
            continue

    # Нормалізація + унікальність із збереженням порядку
    seen = set()
    out: List[str] = []
    for raw in links:
        u = normalize(raw)
        if u and u not in seen:
            out.append(u)
            seen.add(u)
    return out


def extract_links_any(msg_or_text: Union[str, Any]) -> List[str]:
    """
    Універсальний витягувач:
      • якщо дали Telethon Message — бере і regex із тексту, і з entities
      • якщо дали рядок — працює як звичайний extract_links
    """
    # випадок Telethon Message
    if TgMessage and isinstance(msg_or_text, TgMessage):
        text = msg_or_text.raw_text or ""
        out = extract_links(text)
        # з entities добираємо приховані лінки
        ent_links = _extract_from_entities(text, msg_or_text.entities or [])
        # мержимо унікально, зберігаючи початковий порядок
        seen = set(out)
        for u in ent_links:
            if u not in seen:
                out.append(u)
                seen.add(u)
        return out

    # випадок звичайного тексту
    return extract_links(str(msg_or_text or ""))


def _clean_url_generic(u: str) -> str:
    """
    Санітує та обрізає хвости для aiogram-повідомлень.
    Використовує sanitize_link + прибирає хвости неприйнятних символів.
    """
    try:
        u = sanitize_link(u) or u
    except Exception:
        u = u
    u = (u or "").strip()
    # залишаємо лише ASCII-частину посилання (щоб обрізати випадкові кириличні символи вкінці)
    # ставимо "-" у кінці класу, щоб не ловити "bad character range"
    m = re.match(r"^((?:https?://|tg://|t\.me/)[A-Za-z0-9_.:/?&=#%+@-]+)", u)
    if m:
        u = m.group(1)
    # дефіс наприкінці, щоб уникнути діапазонів у [] для re
    u = re.sub(r"[^A-Za-z0-9_.:/?&=#%+@-]+$", "", u)
    u = u.rstrip(').,;\'"<>[]{}')
    return u


def extract_links_aiogram(msg: Any) -> List[str]:
    """
    Витягує всі лінки/mention з aiogram Message (text/caption + entities).
    Повертає унікальні нормалізовані URL у порядку появи.
    """
    if AiogramMessage is None or not isinstance(msg, AiogramMessage):
        return []

    urls: List[str] = []
    entities = msg.entities or msg.caption_entities or []
    txt = msg.text or msg.caption or ""

    for ent in entities:
        et = getattr(ent, "type", "")
        if et == "text_link":
            u = getattr(ent, "url", None)
            if u:
                urls.append(_clean_url_generic(u))
        elif et == "url":
            off = int(getattr(ent, "offset", 0))
            ln = int(getattr(ent, "length", 0))
            piece = txt[off : off + ln].strip()
            if piece:
                urls.append(_clean_url_generic(piece))
        elif et == "mention":  # @username
            off = int(getattr(ent, "offset", 0))
            ln = int(getattr(ent, "length", 0))
            piece = txt[off : off + ln].strip()
            if piece:
                urls.append(_clean_url_generic(piece))

    for m_ in _AI0G_LINK_RE.finditer(txt):
        urls.append(_clean_url_generic(m_.group(1)))
    for m_ in _AI0G_MENTION_RE.finditer(txt):
        urls.append(_clean_url_generic(m_.group(0)))

    cleaned = [_clean_url_generic(u) for u in urls if u]
    uniq = []
    seen = set()
    for u in cleaned:
        if not u:
            continue
        norm = sanitize_link(u)
        if norm and norm not in seen:
            uniq.append(norm)
            seen.add(norm)
    return uniq


def extract_links_norm(text: str) -> List[str]:
    """
    Витягує всі лінки з довільного нормалізованого тексту
    (http/https/tg/t.me та @mention) і повертає унікальні
    санітізовані URL у порядку появи.
    """
    if not text:
        return []

    raw: List[str] = []
    for m in _AI0G_LINK_RE.finditer(text):
        raw.append(m.group(1))
    for m in _AI0G_MENTION_RE.finditer(text):
        raw.append(m.group(0))

    seen = set()
    out: List[str] = []
    for u in raw:
        cleaned = _clean_url_generic(u)
        if not cleaned:
            continue
        norm = sanitize_link(cleaned)
        if norm and norm not in seen:
            out.append(norm)
            seen.add(norm)
    return out


def extract_links_from_html(html_text: str) -> List[str]:
    """
    Витягує унікальні посилання з HTML:
      • href із тегів <a>
      • голі URL/@mention з тексту після видалення тегів
    """
    if not html_text:
        return []

    seen = set()
    out: List[str] = []

    def _add(u_raw: str) -> None:
        u = sanitize_link(_clean_url_generic(u_raw))
        if u and u not in seen:
            seen.add(u)
            out.append(u)

    unescaped = _html_mod.unescape(html_text)
    for m_ in re.findall(r'href\s*=\s*(?:"|\')([^"\']+)(?:"|\')', unescaped, flags=re.IGNORECASE):
        _add(m_)

    plain = re.sub(r"<[^>]+>", " ", unescaped)
    for u in extract_links_norm(plain):
        _add(u)

    return out


async def collect_links(evt) -> List[str]:
    links: List[str] = []

    # 1) текст повідомлення
    text = getattr(evt, "raw_text", "") or ""
    if text:
        try:
            # якщо у файлі вже є extract_links(text) — використовуємо її
            links.extend(extract_links(text))  # type: ignore[name-defined]
        except NameError:
            # fallback: простий підхват t.me та @username
            import re
            links.extend(re.findall(r'(https?://t\.me/[^\s]+|t\.me/[^\s]+|@[\w\d_]+)', text))

    # 2) посилання в entities (наприклад, приховані URL)
    msg = getattr(evt, "message", None)
    entities = getattr(msg, "entities", None)
    if entities:
        for e in entities:
            u = getattr(e, "url", None)
            if u:
                links.append(u)

    # 3) посилання в кнопках reply_markup
    rm = getattr(msg, "reply_markup", None)
    if rm:
        for row in getattr(rm, "rows", []) or []:
            for btn in getattr(row, "buttons", []) or []:
                u = getattr(btn, "url", None)
                if u:
                    links.append(u)

    return links
