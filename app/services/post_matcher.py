# app/services/post_matcher.py
from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional, List, Tuple

log = logging.getLogger("services.post_matcher")

_ZERO_WIDTH = ("\u200b", "\u200e", "\u200f")

def _strip_zw(s: str) -> str:
    for z in _ZERO_WIDTH:
        s = s.replace(z, "")
    return s

def normalize_text(s: Optional[str]) -> str:
    """
    Нормалізація: прибрати zero-width, \r, зайві пробіли, trim.
    (Без lower() — щоб не ловити false-positive).
    """
    if not s:
        return ""
    x = _strip_zw(s)
    x = x.replace("\r", "")
    x = " ".join(x.split())  # компактуємо пробіли/переноси
    return x.strip()

def _canon_url(u: str) -> str:
    # Проста канонізація для t.me-посилань: обрізаємо слеші, видаляємо zero-width, trim
    if not u:
        return ""
    u = _strip_zw(u).strip()
    # можна додати додаткову канонізацію (scheme, lower host, тощо) — поки мінімально
    return u

def extract_links_norm(s: str) -> List[str]:
    """
    Дістаємо URL-и з тексту — якщо у вас вже є свій парсер, використайте його тут.
    Тут — простий евристичний варіант (регулярка).
    """
    import re
    out: List[str] = []
    if not s:
        return out
    # дуже проста регулярка; за потреби підмінити на ваш extract_links
    for m in re.finditer(r"https?://\S+|t\.me/\S+", s):
        out.append(_canon_url(m.group(0)))
    out = list(dict.fromkeys(out))  # дедуп з збереженням порядку
    out.sort()
    return out

def build_text_fingerprint(s: Optional[str]) -> Tuple[str, int, str]:
    """
    -> (sha256_hex, norm_len, links_json_sorted)
    """
    norm = normalize_text(s or "")
    links = extract_links_norm(norm)
    links_json = json.dumps(links, ensure_ascii=False, separators=(",", ":"))
    h = hashlib.sha256(norm.encode("utf-8")).hexdigest()
    log.debug("[matcher] text fp: len=%s links=%s sha256=%s...", len(norm), len(links), h[:8])
    return h, len(norm), links_json

def build_media_fingerprint(msg) -> Optional[str]:
    """
    Мінімальний фп для медіа: тип + (w×h) + duration (якщо є).
    Для фото/відео/доків. Без md5 контенту (дорого).
    """
    try:
        # Telethon message: msg.photo / msg.video / msg.document ...
        if getattr(msg, "photo", None):
            ph = msg.photo
            w = getattr(ph, "w", None) or getattr(ph, "width", None)
            h = getattr(ph, "h", None) or getattr(ph, "height", None)
            fp = {"kind": "photo", "w": int(w or 0), "h": int(h or 0)}
            j = json.dumps(fp, sort_keys=True, separators=(",", ":"))
            log.debug("[matcher] media fp: %s", j)
            return j

        if getattr(msg, "video", None) or (getattr(msg, "document", None) and "video" in str(msg.document)):
            # грубо: якщо документ з типом video
            d = getattr(msg, "document", None)
            w = getattr(d, "w", 0) if d else 0
            h = getattr(d, "h", 0) if d else 0
            dur = getattr(d, "duration", 0) if d else 0
            fp = {"kind": "video", "w": int(w or 0), "h": int(h or 0), "dur": int(dur or 0)}
            j = json.dumps(fp, sort_keys=True, separators=(",", ":"))
            log.debug("[matcher] media fp: %s", j)
            return j

        # інші типи можна додати за потреби
    except Exception as e:
        log.debug("[matcher] media fp error: %s", e)

    return None

def is_match_message(
    msg,
    expected_text_hash: Optional[str],
    expected_text_norm_len: Optional[int],
    expected_links_json: Optional[str],
    expected_media_fingerprint: Optional[str],
) -> bool:
    """
    Перевірка чи msg — той самий пост (строга відповідність).
    """
    try:
        # текст
        if expected_text_hash or expected_text_norm_len or expected_links_json:
            h, ln, links_json = build_text_fingerprint(getattr(msg, "message", None))
            if expected_text_hash and h != expected_text_hash:
                log.debug("[matcher] text hash mismatch: got=%s exp=%s", h[:8], expected_text_hash[:8])
                return False
            if expected_text_norm_len is not None and int(ln) != int(expected_text_norm_len):
                log.debug("[matcher] text len mismatch: got=%s exp=%s", ln, expected_text_norm_len)
                return False
            if expected_links_json and links_json != expected_links_json:
                log.debug("[matcher] links json mismatch")
                return False

        # медіа
        if expected_media_fingerprint:
            got_fp = build_media_fingerprint(msg) or ""
            if got_fp != expected_media_fingerprint:
                log.debug("[matcher] media fp mismatch")
                return False

        # якщо були очікування — і не впали на перевірках — це матч
        if (expected_text_hash or expected_media_fingerprint):
            log.debug("[matcher] MATCH ok")
            return True

        # якщо очікувань не було — вчимося бути строгими: не матч
        log.debug("[matcher] no expectations -> not a match")
        return False
    except Exception as e:
        log.debug("[matcher] is_match error: %s", e)
        return False