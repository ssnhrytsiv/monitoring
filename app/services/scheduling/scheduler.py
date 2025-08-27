import heapq
import time
from typing import List, Optional
from .models import ScheduledTask
from .rate_limiter import RateLimiterService

class TaskScheduler:
    """
    Пріоритетна черга (heap) із підтримкою not_before часу.
    """
    def __init__(self):
        self._heap: List[tuple[int, float, int, str, ScheduledTask]] = []
        self._seq = 0

    def add_task(self, task: ScheduledTask):
        self._seq += 1
        heapq.heappush(self._heap, (task.priority, task.not_before, self._seq, task.id, task))

    def pop_ready(self, rate_limiter: RateLimiterService) -> Optional[ScheduledTask]:
        now = time.time()
        while self._heap:
            priority, not_before, seq, _id, task = self._heap[0]
            if not_before > now:
                return None
            account = task.payload.get("account")
            if rate_limiter.can_proceed(task.action_type.value, account):
                heapq.heappop(self._heap)
                return task
            return None
        return None

    def size(self) -> int:
        return len(self._heap)

    def peek_delay(self) -> Optional[float]:
        if not self._heap:
            return None
        _, not_before, *_ = self._heap[0]
        delta = not_before - time.time()
        return delta if delta > 0 else 0.0