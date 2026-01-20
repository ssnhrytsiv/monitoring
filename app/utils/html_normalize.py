from __future__ import annotations

import html as _html_mod
import re

# Регулярка для <a href="...">...</a>
_A_TAG_RE = re.compile(r'<a\s+href=(?P<q1>"|\')(?P<href>.+?)(?P=q1)>(?P<body>.*?)</a>', re.DOTALL | re.IGNORECASE)

# Хештег реклами, який треба ігнорувати при порівняннях
_AD_TAG_RE = re.compile(r"(?:\s*(?:<br\s*/?>|\n)?\s*#реклама\b\.?)+\s*$", re.IGNORECASE)


def strip_simple_tags(html_fragment: str) -> str:
    """
    Видаляє прості теги форматування (<b>, <u>, <i>, <strong>, <em>) з фрагмента,
    залишаючи тільки текст усередині.
    """
    return re.sub(r"</?(?:b|u|i|strong|em)>", "", html_fragment, flags=re.IGNORECASE)


def normalize_html_links(html: str) -> str:
    """
    Нормалізує посилання у HTML:
      - якщо <a href="X">X</a> (або X з простими тегами усередині) — розкриває в plain текст (href)
      - декодує ентіті
    """

    def _replace_a(m: re.Match) -> str:
        href = m.group("href")
        body = m.group("body")

        href_stripped = href.strip()
        body_plain = strip_simple_tags(body)
        body_plain_unescaped = _html_mod.unescape(body_plain)
        body_plain_stripped = body_plain_unescaped.strip()
        body_plain_stripped = body_plain_stripped.replace("\n", " ")

        if body_plain_stripped == href_stripped:
            return href_stripped
        return m.group(0)

    html = _html_mod.unescape(html or "")
    html = _A_TAG_RE.sub(_replace_a, html)
    return html


def _drop_ad_tag(text: str) -> str:
    """
    Прибирає завершаючий #реклама (у різному регістрі, з можливими <br>/переносами)
    з кінця рядка, щоб він не впливав на порівняння.
    """
    return _AD_TAG_RE.sub("", text or "")


def normalize_html_full(html_text: str) -> str:
    """
    Розширена нормалізація HTML для вотчів:
      - застосовує normalize_html_links (розкриває <a>, приводить &amp; -> &);
      - декодує HTML-ентіті;
      - прибирає службові символи/zero-width/variation selectors;
      - конвертує <br>/<p> у переводи рядків;
      - трохи чистить пробіли/переводи рядків.
    """
    if not html_text:
        return ""

    html_text = html_text.replace("\r\n", "\n")
    html_text = normalize_html_links(html_text)
    html_text = _html_mod.unescape(html_text)

    # NBSP -> звичайний пробіл
    html_text = html_text.replace("\u00a0", " ")
    html_text = re.sub(r"\u200b|\u200c|\u200d|\ufeff|\ufe0f", "", html_text)
    html_text = re.sub(r"<\s*br\s*/?>", "\n", html_text, flags=re.IGNORECASE)
    html_text = re.sub(r"<\s*/?p\s*>", "\n", html_text, flags=re.IGNORECASE)
    # Прибираємо пробіли безпосередньо перед закриттям базових тегів
    html_text = re.sub(r"\s+(</(?:b|i|u|s|strong|em|code|pre|blockquote|span|a)>)", r"\1", html_text, flags=re.IGNORECASE)
    html_text = re.sub(r"\s+", " ", html_text)
    html_text = re.sub(r"\n\s*\n+", "\n", html_text)
    html_text = html_text.strip()
    html_text = _drop_ad_tag(html_text)
    return html_text


def normalize_html_for_edit(html_text: str) -> str:
    """
    Більш строга нормалізація для перевірки редагувань: мінімум допусків.
    """
    if not html_text:
        return ""
    s = html_text.replace("\r\n", "\n")
    s = normalize_html_links(s)
    s = _html_mod.unescape(s)
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\u200b|\u200c|\u200d|\ufeff|\ufe0f", "", s)
    s = re.sub(r"<\s*br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+(</(?:b|i|u|s|strong|em|code|pre|blockquote|span|a)>)", r"\1", s, flags=re.IGNORECASE)
    s = re.sub(r"[ \t]*\n[ \t]*", "\n", s)
    # Згортаємо лише пробіли/таби, зберігаючи переноси рядків як маркер структури.
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ \t]*\n+", "\n", s)
    s = s.strip()
    s = _drop_ad_tag(s)
    return s


def strip_tags_to_text(html_text: str) -> str:
    """
    Грубо прибирає всі HTML-теги, декодує ентіті та чистить пробіли.
    Використовується для plain-порівняння.
    """
    if not html_text:
        return ""
    s = _html_mod.unescape(html_text)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()
