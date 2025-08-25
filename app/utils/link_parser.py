import re

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
            out.append(url)
        elif m.group(3):
            # username без http
            uname = m.group(3).lstrip("@")
            url = "https://t.me/" + uname
            out.append(url)
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
    return ("/+" in url) or ("joinchat" in url)


def normalize(url: str) -> str:
    """
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