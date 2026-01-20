from difflib import SequenceMatcher
from typing import Optional
import re

ZERO_WIDTH = ("\u200b", "\u200e", "\u200f")
_URL_RE = re.compile(r"(https?://[^\s]+|tg://[^\s]+|t\.me/[^\s]+)", re.IGNORECASE)


def _strip_zw(s: str) -> str:
    for zw in ZERO_WIDTH:
        s = s.replace(zw, "")
    return s


def normalize_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = _strip_zw(s)
    return " ".join(s.strip().split())


def extract_links_norm(s: str) -> list[str]:
    return list({_canon_url(m.group(0)) for m in _URL_RE.finditer(s or "")})


def _canon_url(u: str) -> str:
    u = (u or "").strip().strip(" '\"<>")
    return u.lower()


def exact_match(a: str, b: str) -> bool:
    return normalize_text(a) == normalize_text(b)


def fuzzy_ratio(a: str, b: str) -> float:
    a_n = normalize_text(a)
    b_n = normalize_text(b)
    if not a_n and not b_n:
        return 1.0
    return SequenceMatcher(None, a_n, b_n).ratio()


def fuzzy_match(a: str, b: str, threshold: float = 0.70) -> bool:
    return fuzzy_ratio(a, b) >= threshold
