from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Optional, Any, Dict

class ActionType(str, Enum):
    JOIN = "join"
    RESOLVE = "resolve"
    FETCH_INFO = "fetch_info"
    OTHER = "other"

@dataclass
class ScheduledTask:
    """
    Одна планована дія.
    priority: менше число = вищий пріоритет
    not_before: epoch seconds – час, раніше якого виконувати не можна
    """
    id: str
    action_type: ActionType
    payload: Dict[str, Any]
    priority: int = 100
    not_before: float = 0.0
    created_ts: float = field(default_factory=lambda: time.time())

    def ready(self, now: Optional[float] = None) -> bool:
        now = now or time.time()
        return now >= self.not_before