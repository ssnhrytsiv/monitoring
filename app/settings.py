import os
def _truthy(v: str | None) -> bool:
    if v is None: return False
    v = v.strip().lower()
    return v in {"1","true","yes","on"}

MONITOR_LINKS_V2 = _truthy(os.getenv("MONITOR_LINKS_V2", "0"))
MONITOR_LINKS_SHADOW = _truthy(os.getenv("MONITOR_LINKS_SHADOW", "0"))

# страховка від випадкових підписок генератором
EXCLUDE_SESSIONS_FROM_JOIN = os.getenv('EXCLUDE_SESSIONS_FROM_JOIN', 'tg_session_3')
