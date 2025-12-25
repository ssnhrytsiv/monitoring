from __future__ import annotations

import time
from typing import List, Optional

from app.services import link_queue


def enqueue_retry(
    urls: List[str],
    *,
    chat_id: Optional[int],
    msg_id: Optional[int],
    owner_display: Optional[str],
    owner_username: Optional[str],
) -> None:
    """
    Додає проблемні URL у link_queue для ретраю (flood/too_many/no_client).
    """
    if not urls:
        return
    batch_id = f"adminbot:{chat_id}:{int(time.time())}"
    link_queue.enqueue(
        urls,
        batch_id=batch_id,
        origin_chat=chat_id,
        origin_msg=msg_id,
        owner_display=owner_display,
        owner_username=owner_username,
    )
