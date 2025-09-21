import os
def _truthy(v: str | None) -> bool:
    if v is None: return False
    v = v.strip().lower()
    return v in {"1","true","yes","on"}

MONITOR_LINKS_V2 = _truthy(os.getenv("MONITOR_LINKS_V2", "0"))
MONITOR_LINKS_SHADOW = _truthy(os.getenv("MONITOR_LINKS_SHADOW", "0"))

CREATOR_SESSION_NAME = os.getenv('CREATOR_SESSION_NAME', 'tg_session_3')
SEED_TARGET = os.getenv('SEED_TARGET', 'tg_session')
SEED_DELAY_BETWEEN_CREATES = float(os.getenv('SEED_DELAY_BETWEEN_CREATES', '7.0'))
SEED_DELAY_BETWEEN_BATCHES = float(os.getenv('SEED_DELAY_BETWEEN_BATCHES', '20.0'))
SEED_JITTER_CREATE = os.getenv('SEED_JITTER_CREATE', '0.3,1.2')
SEED_MAX_PER_10_MIN = int(os.getenv('SEED_MAX_PER_10_MIN', '15'))

# страховка від випадкових підписок генератором
EXCLUDE_SESSIONS_FROM_JOIN = os.getenv('EXCLUDE_SESSIONS_FROM_JOIN', 'tg_session_3')