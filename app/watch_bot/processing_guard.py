import logging
from typing import Dict, Any

log = logging.getLogger("bot_processing_guard")

# зберігаємо не просто set, а словник з даними по користувачу
_processing_state: Dict[int, Dict[str, Any]] = {}


def is_processing(user_id: int) -> bool:
    data = _processing_state.get(user_id)
    return bool(data and data.get("processing"))


def set_processing(user_id: int, flag: bool, msg_id: int | None = None) -> None:
    data = _processing_state.get(user_id) or {}
    data["processing"] = flag
    if msg_id is not None:
        data["msg_id"] = msg_id
    _processing_state[user_id] = data

    log.info(
        "processing.set",
        extra={"user_id": user_id, "flag": flag, "msg_id": msg_id},
    )


def get_processing(user_id: int) -> dict | None:
    return _processing_state.get(user_id)