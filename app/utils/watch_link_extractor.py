from __future__ import annotations

import html as html_mod
import re
from typing import Iterable, List

from app.utils.link_parser import extract_links_any, sanitize_link

_LINK_RE = re.compile(r'(?i)\b((?:https?://|tg://|t\.me/)[^\s<>"\'\]\)]+)')
_HREF_RE = re.compile(r'href\s*=\s*(?:"|\')([^"\']+)(?:"|\')', re.IGNORECASE)


def _unique_preserve(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def normalize_link_for_watch(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""

    try:
        normalized = sanitize_link(normalized)
    except Exception:
        pass

    lower_value = normalized.lower()
    telegram_pos = lower_value.find("t.me/")
    if telegram_pos != -1:
        cut_pos = len(normalized)
        for tail_separator in ('"', "<"):
            index = normalized.find(tail_separator, telegram_pos)
            if index != -1:
                cut_pos = min(cut_pos, index)
        if cut_pos != len(normalized):
            normalized = normalized[:cut_pos].rstrip(".,;:)]}>")
            try:
                normalized = sanitize_link(normalized)
            except Exception:
                pass

    return normalized.strip()


def normalize_links_for_watch(values: Iterable[str]) -> List[str]:
    normalized_values: List[str] = []
    for value in values:
        normalized = normalize_link_for_watch(str(value or ""))
        if normalized:
            normalized_values.append(normalized)
    return _unique_preserve(normalized_values)


def extract_links_from_text_for_watch(text_or_html: str) -> List[str]:
    source_text = str(text_or_html or "")
    if not source_text:
        return []

    links: List[str] = []
    for href_value in _HREF_RE.findall(source_text):
        cleaned_href = html_mod.unescape(str(href_value or "")).strip()
        if cleaned_href:
            links.append(cleaned_href)

    plain_text = re.sub(r"<[^>]+>", " ", html_mod.unescape(source_text))
    for matched in _LINK_RE.finditer(plain_text):
        url_value = str(matched.group(1) or "").strip()
        if url_value:
            links.append(url_value)

    try:
        extra_links = extract_links_any(source_text) or []
    except Exception:
        extra_links = []

    if extra_links:
        merged_links: List[str] = list(_unique_preserve(links))
        for full_value in extra_links:
            full_link = str(full_value or "").strip()
            if not full_link:
                continue
            if full_link in merged_links:
                continue
            skip_longer_variant = False
            for existing_link in merged_links:
                if not existing_link:
                    continue
                if full_link.startswith(existing_link) and len(full_link) > len(existing_link):
                    skip_longer_variant = True
                    break
            if not skip_longer_variant:
                merged_links.append(full_link)
        links = merged_links

    return normalize_links_for_watch(links)
