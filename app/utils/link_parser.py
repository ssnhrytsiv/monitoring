import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# Hosts that we consider equivalent / canonical for Telegram short links
T_ME_HOSTS = {"t.me", "telegram.me", "telegram.dog"}
# Parameters we strip because they are tracking / irrelevant for identity
URL_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "referral"
}

_INVITE_RE = re.compile(r"^(?:https?://)?(?:t\\.me|telegram\.(?:me|dog))/(?:joinchat/|\+)([A-Za-z0-9_-]{5,64})/?")


def normalize_url(url: str) -> str:
    """Return a canonical form for a Telegram channel/invite URL.

    Rules (conservative so we don't accidentally merge distinct resources):
    - Trim surrounding whitespace
    - Ensure scheme is https://
    - Lowercase the host
    - Only keep path + (filtered) query params
    - Remove known tracking query parameters (utm_*, ref, referral)
    - Remove trailing slash in path (except root)
    - For t.me invite forms like t.me/+HASH or t.me/joinchat/HASH keep as https://t.me/+HASH
    """
    if not url:
        return url
    raw = url.strip()
    # Fast path: if already looks like a bare invite hash prefix we still run parse
    if not raw.startswith("http://") and not raw.startswith("https://"):
        if raw.startswith("t.me/") or raw.startswith("telegram.me/") or raw.startswith("telegram.dog/"):
            raw = "https://" + raw
        else:
            raw = "https://" + raw  # fallback – will parse whatever is there
    p = urlparse(raw)
    host = p.netloc.lower()
    if host in T_ME_HOSTS:
        host = "t.me"
    path = p.path or ""
    # Collapse multiple slashes
    while '//' in path:
        path = path.replace('//', '/')
    # Special handling for legacy joinchat style -> unify to /+HASH
    m = re.match(r"/(?:joinchat/)?\+?([A-Za-z0-9_-]{5,64})/?$", path)
    if m:
        path = "/+" + m.group(1)
    # Remove trailing slash (except root)
    if path.endswith('/') and path != '/':
        path = path[:-1]
    # Filter query params
    if p.query:
        kept = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k not in URL_TRACKING_PARAMS]
    else:
        kept = []
    query = urlencode(kept, doseq=True)
    new_parts = ("https", host, path, "", query, "")
    out = urlunparse(new_parts)
    # Drop ? if query empty
    if out.endswith('?'):
        out = out[:-1]
    return out


def is_invite_link(url: str) -> bool:
    """Heuristic to detect if URL points to an invite hash (joinchat/+ forms)."""
    if not url:
        return False
    return "+" in url or "joinchat" in url or extract_invite_hash(url) is not None


def extract_invite_hash(url: str):
    """Extract invite hash from a Telegram invite URL, if present; else None."""
    if not url:
        return None
    m = _INVITE_RE.match(url.strip())
    if m:
        return m.group(1)
    # Fallback simple split logic
    if "/+" in url:
        tail = url.rsplit("/", 1)[-1]
        return tail.lstrip('+') or None
    if "joinchat/" in url:
        tail = url.rsplit("/", 1)[-1]
        return tail or None
    return None
