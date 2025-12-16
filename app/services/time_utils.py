from datetime import datetime
import pytz

MSK_TZ = pytz.timezone("Europe/Moscow")

def msk_now() -> datetime:
    """Datetime зараз у Europe/Moscow (tz-aware)."""
    return datetime.now(MSK_TZ)

def msk_timestamp() -> int:
    """Unix timestamp (int, сек) у Europe/Moscow."""
    return int(msk_now().timestamp())