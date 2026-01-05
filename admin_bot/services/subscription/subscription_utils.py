from __future__ import annotations

from typing import List


def norm_keys(url: str) -> List[str]:
    keys = []
    if url:
        keys.append(url)
    try:
        from app.utils.tg_links import sanitize_link

        cleaned = sanitize_link(url) or url
        if cleaned and cleaned not in keys:
            keys.append(cleaned)
    except Exception:
        pass
    return keys


__all__ = ["norm_keys"]
