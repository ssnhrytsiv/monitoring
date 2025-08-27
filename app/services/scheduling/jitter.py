import random

def add_jitter(base_seconds: float, low: float = -0.15, high: float = 0.25) -> float:
    """
    Повертає base_seconds * (1 + random.uniform(low, high)) для уникнення ритмічних патернів.
    """
    if base_seconds <= 0:
        return 0.0
    factor = 1 + random.uniform(low, high)
    return max(0.0, base_seconds * factor)