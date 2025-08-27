import time
from typing import Optional, Dict

class TokenBucket:
    def __init__(self, rate: float, capacity: int):
        self.rate = rate
        self.capacity = capacity
        self.tokens = float(capacity)
        self.last_refill = time.time()

    def _refill(self):
        now = time.time()
        elapsed = now - self.last_refill
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_refill = now

    def acquire(self, cost: float = 1.0) -> bool:
        self._refill()
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False

class RateLimiterService:
    """
    Глобальні ліміти (per action_type) + базові пер-акаунтні.
    global_limits: {"join": {"rate":0.3,"capacity":2}, ...}
    account_limits: {"default":{"rate":0.1,"capacity":1}}
    """
    def __init__(self,
                 global_limits: Dict[str, Dict[str, float]],
                 account_limits: Dict[str, Dict[str, float]]):
        self.global_buckets: Dict[str, TokenBucket] = {
            name: TokenBucket(cfg["rate"], cfg["capacity"])
            for name, cfg in global_limits.items()
        }
        self.account_template = account_limits.get("default", {"rate": 0.2, "capacity": 1})
        self.account_buckets: Dict[str, TokenBucket] = {}

    def _get_account_bucket(self, account: str) -> TokenBucket:
        if account not in self.account_buckets:
            cfg = self.account_template
            self.account_buckets[account] = TokenBucket(cfg["rate"], cfg["capacity"])
        return self.account_buckets[account]

    def can_proceed(self, action_type: str, account: Optional[str]) -> bool:
        gb = self.global_buckets.get(action_type)
        if gb and not gb.acquire(1.0):
            return False
        if account:
            ab = self._get_account_bucket(account)
            if not ab.acquire(1.0):
                return False
        return True