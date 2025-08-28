import re
from urllib.parse import urlparse, parse_qs

# Регулярка ловить будь-які варіанти t.me посилань:
#   - https://t.me/....
#   - http://t.me/....
#   - t.me/....
#   - (https://t.me/...)
#   - з /+inviteHash
#   - з @username (можемо нормалізувати)
RE_TG = re.compile(
    r"(https?://)?t\.me/([^\s)]+)|(@[A-Za-z0-9_]{3,})",
    re.IGNORECASE
)

# Valid invite hash pattern: base64-like chars, 16-24 chars typically
RE_INVITE_HASH = re.compile(r'^[A-Za-z0-9_-]{16,24}$')

def extract_links(text: str) -> list[str]:
    """
    Витягує t.me посилання з довільного тексту.
    Повертає список нормалізованих URL у форматі 'https://t.me/...'
    """
    if not text:
        return []
    out = []
    for m in RE_TG.finditer(text):
        if m.group(2):
            url = "https://t.me/" + m.group(2).strip()
            out.append(normalize_url(url))  # Apply normalization
        elif m.group(3):
            # username без http
            uname = m.group(3).lstrip("@")
            url = "https://t.me/" + uname
            out.append(normalize_url(url))  # Apply normalization
    # Прибрати дублікати, зберігши порядок
    seen, res = set(), []
    for u in out:
        if u not in seen:
            res.append(u)
            seen.add(u)
    return res


def is_invite(url: str) -> bool:
    """
    Швидка перевірка: чи є лінк інвайтом (з +hash або joinchat).
    """
    return ("/+" in url) or ("joinchat" in url.lower())


def normalize_url(url: str) -> str:
    """
    Robust URL normalization to canonicalize t.me links:
    - joinchat/HASH -> +HASH
    - Strip query parameters and fragments
    - Strip punctuation from the end
    - Ensure https scheme
    - Lowercase usernames and invite hashes
    - Remove unnecessary whitespace and brackets
    """
    if not url:
        return ""
    
    # Remove whitespace and common wrapper chars
    url = url.strip("() \n\t\"'<>[]{}").strip()
    
    # Handle @username format
    if url.startswith("@"):
        username = url[1:].lower()
        return f"https://t.me/{username}"
    
    # Ensure proper scheme
    if not url.lower().startswith(("http://", "https://")):
        if url.lower().startswith("t.me") or url.lower().startswith("telegram.me"):
            url = "https://" + url
        else:
            url = "https://t.me/" + url.lstrip("/")
    
    # Parse URL to normalize components
    try:
        parsed = urlparse(url.lower())
        
        # Normalize domain
        domain = parsed.netloc
        if domain == "telegram.me":
            domain = "t.me"
        elif domain not in ("t.me",):
            # If not a telegram domain, return as-is but cleaned
            return url.strip()
            
        path = parsed.path.strip("/")
        
        # Handle joinchat -> + conversion
        if path.startswith("joinchat/"):
            invite_hash = path[9:]  # Remove "joinchat/"
            if invite_hash:
                return f"https://t.me/+{invite_hash.lower()}"
        
        # Handle +invite format
        if path.startswith("+"):
            invite_hash = path[1:]
            if invite_hash:
                return f"https://t.me/+{invite_hash.lower()}"
        
        # Handle regular usernames/channels
        if path:
            # Remove trailing punctuation that might have been captured
            path = path.rstrip(".,;:!?")
            return f"https://t.me/{path.lower()}"
        
        return f"https://t.me/"
        
    except Exception:
        # Fallback to basic normalization if URL parsing fails
        return normalize(url)


def normalize(url: str) -> str:
    """
    Legacy normalization function - kept for backward compatibility.
    Приводить url до стабільної форми:
    - без зайвих пробілів/дужок
    - завжди https://t.me/...
    """
    url = url.strip("() \n\t")
    if url.startswith("@"):
        url = "https://t.me/" + url[1:]
    if not url.startswith("http"):
        url = "https://" + url
    return url


def extract_invite_hash(url: str) -> str:
    """
    Extract invite hash from a Telegram invite URL.
    Returns empty string if not an invite URL or invalid format.
    """
    if not is_invite(url):
        return ""
    
    try:
        # Handle joinchat format
        if "joinchat" in url.lower():
            parts = url.split("/")
            for i, part in enumerate(parts):
                if part.lower() == "joinchat" and i + 1 < len(parts):
                    hash_part = parts[i + 1].strip()
                    # Clean up query parameters and fragments
                    hash_part = hash_part.split('?')[0].split('#')[0]
                    return hash_part
        
        # Handle +hash format
        if "/+" in url:
            hash_part = url.split("/+", 1)[1]
            # Remove any trailing junk including query params
            hash_part = hash_part.split('?')[0].split('#')[0].split()[0].rstrip(".,;:!?)")
            return hash_part
            
    except Exception:
        pass
    
    return ""


def is_valid_invite_hash(invite_hash: str) -> bool:
    """
    Local format validation for invite hashes.
    Checks length and character set without hitting Telegram API.
    """
    if not invite_hash:
        return False
    
    # Remove any whitespace
    invite_hash = invite_hash.strip()
    
    # Basic format check: typically 16-24 base64-like characters
    return bool(RE_INVITE_HASH.match(invite_hash))


def canonical_invite_url(invite_hash: str) -> str:
    """
    Convert invite hash to canonical URL format.
    """
    if not invite_hash:
        return ""
    
    invite_hash = invite_hash.strip().lower()
    return f"https://t.me/+{invite_hash}"