"""
Простий кеш результатів process_batch за batch_id, щоб рефреш міг
підтягнути фактичні статуси (включно з owner_conflict).
"""

from __future__ import annotations

from typing import Dict, List, Optional

_CACHE: Dict[str, Dict] = {}


def register(batch_id: str, items: List[Dict], original_urls: Optional[List[str]] = None) -> None:
    _CACHE[batch_id] = {"items": items, "original_urls": original_urls or []}


def pop(batch_id: str) -> Optional[Dict]:
    return _CACHE.pop(batch_id, None)


__all__ = ["register", "pop"]
