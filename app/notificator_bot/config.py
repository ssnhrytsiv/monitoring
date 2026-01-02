from __future__ import annotations

import os
from typing import List


def _parse_ids(val: str | None) -> List[int]:
    if not val:
        return []
    out: List[int] = []
    for part in val.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except Exception:
            continue
    return out


NOTIFIER_BOT_TOKEN: str | None = os.getenv("NOTIFIER_BOT_TOKEN")
NOTIFIER_TARGET_IDS: List[int] = _parse_ids(os.getenv("NOTIFIER_TARGET_IDS"))
NOTIFIER_POLL_INTERVAL_SEC: int = int(os.getenv("NOTIFIER_POLL_INTERVAL_SEC", "25"))
