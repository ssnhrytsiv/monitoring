"""
Утиліти для нормалізації HTML/тексту повідомлень під подальше порівняння.
Скопійовано/спрощено з posts_watch_listener, щоб можна було перевикористовувати без циклічних імпортів.
"""

import re
import html as _html

_A_TAG_RE = re.compile(
    r'<a\s+href=(?P<q1>"|\')(?P<href>.+?)(?P=q1)>(?P<body>.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)


def _strip_simple_tags(html_fragment: str) -> str:
    html_fragment = re.sub(r"<(/)?(b|strong)>", "", html_fragment, flags=re.IGNORECASE)
    html_fragment = re.sub(r"<(/)?(i|em)>", "", html_fragment, flags=re.IGNORECASE)
    html_fragment = re.sub(r"<(/)?(u|ins)>", "", html_fragment, flags=re.IGNORECASE)
    html_fragment = re.sub(r"<(/)?(s|del)>", "", html_fragment, flags=re.IGNORECASE)
    return html_fragment


def _normalize_html_links(html: str) -> str:
    """
    Приводить <a href="X">X</a> -> X для стабільного порівняння.
    """

    def _replace_a(m: re.Match) -> str:
        href = m.group("href") or ""
        body = m.group("body") or ""
        href = href.strip()
        body = body.strip()
        if href == body:
            return href
        return m.group(0)

    return _A_TAG_RE.sub(_replace_a, html)


def normalize_html_full(html_text: str) -> str:
    """
    Розширена нормалізація:
      - _normalize_html_links (a href="X" vs X)
      - html.unescape (&quot; vs ")
      - видаляємо прості теги <b>/<i>/<u>/<s>
      - прибираємо зайві пробіли/переноси
    """
    if not html_text:
        return ""
    html = _normalize_html_links(html_text)
    html = _html.unescape(html)
    html = _strip_simple_tags(html)

    html = re.sub(r"\s+", " ", html, flags=re.MULTILINE).strip()
    html = re.sub(r">\s+([^<])", r">\1", html)  # <a ...>  X -> <a ...>X
    html = re.sub(r"([^>])\s+</a>", r"\1</a>", html)  # X  </a> -> X</a>

    return html
