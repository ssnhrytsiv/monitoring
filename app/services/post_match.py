from difflib import SequenceMatcher

def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\u200b", "").replace("\u200e", "").replace("\u200f", "")
    return " ".join(s.strip().split())

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