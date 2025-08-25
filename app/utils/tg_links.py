# app/utils/tg_links.py
import re
from typing import List

# characters that often stick to URLs
_TRIM_LEAD  = "(<[«\"' \u00A0\u200b\u200c\u200d\u2060"
_TRIM_TRAIL = ".,;:!?)]}>»\"' \u00A0\u200b\u200c\u200d\u2060"

def _fix_scheme(u: str) -> str:
    u = (u or "").strip()
    lu = u.lower()
    if lu.startswith("tps://"):   u = "h" + u
    elif lu.startswith("tp://"):  u = "ht" + u
    elif lu.startswith("ttp://"): u = "h" + u
    elif lu.startswith("www."):   u = "https://" + u
    elif lu.startswith("t.me") or lu.startswith("telegram.me"):
        u = "https://" + u
    if not u.lower().startswith(("http://", "https://")):
        u = "https://" + u.lstrip("/")
    return u

def _canon(u: str) -> str:
    u = _fix_scheme(u)
    # normalize domain + legacy path
    u = re.sub(r'^(https?://)telegram\.me', r'\1t.me', u, flags=re.IGNORECASE)
    u = re.sub(r'/joinchat/', '/', u, flags=re.IGNORECASE)
    return u

def sanitize_link(u: str) -> str:
    """Trim junk around and normalize to canonical t.me link."""
    u = (u or "").strip()
    u = u.strip(_TRIM_LEAD + _TRIM_TRAIL).lstrip("—–-•· ").strip()
    u = _canon(_fix_scheme(u))
    u = u.strip(_TRIM_LEAD + _TRIM_TRAIL)
    return u

_TG_RE = re.compile(
    r'((?:https?://|tps://|tp://|ttp://|www\.)?'
    r'(?:t\.me|telegram\.me)'
    r'/(?:\+[\w-]+|[A-Za-z0-9_]+(?:/\d+)?|c/\d+(?:/\d+)?))',
    re.IGNORECASE
)

def parse_links(text: str) -> List[str]:
    if not text:
        return []
    seen = {}
    for m in _TG_RE.finditer(text):
        raw = m.group(1)
        url = sanitize_link(raw)
        seen[url] = None
    return list(seen.keys())