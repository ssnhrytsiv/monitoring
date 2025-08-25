# app/utils/text_norm.py
import re
import unicodedata

def strip_invisible(s: str) -> str:
    if not s:
        return s or ""
    for ch in ["\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"]:
        s = s.replace(ch, "")
    return s.replace("\r\n", "\n").replace("\r", "\n")

def normalize_strict(s: str) -> str:
    if s is None:
        return ""
    s = strip_invisible(s)
    s = unicodedata.normalize("NFC", s)
    s = s.replace("\u00a0", " ")
    s = "\n".join(line.strip() for line in s.split("\n"))
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def normalize_soft(s: str) -> str:
    return normalize_strict(s)

def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()