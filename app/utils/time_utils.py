from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
MOSCOW_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def moscow_now() -> datetime:
    """
    Повертає поточний час у часовій зоні Europe/Moscow (tz-aware).
    """
    return datetime.now(MOSCOW_TZ)


def moscow_now_str() -> str:
    """
    Повертає поточний час у форматі YYYY-MM-DD HH:MM:SS у часовій зоні Europe/Moscow.
    """
    return moscow_now().strftime(MOSCOW_TIME_FORMAT)


def moscow_timestamp() -> int:
    """
    Unix timestamp (секунди) для поточного часу в Europe/Moscow.
    """
    return int(moscow_now().timestamp())


def ensure_moscow_timezone(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Переводить datetime у часову зону Europe/Moscow.
    Якщо tzinfo відсутній — додає MOSCOW_TZ, якщо присутній — конвертує.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=MOSCOW_TZ)
    return dt.astimezone(MOSCOW_TZ)


# Сумісність зі старою назвою
msk_now = moscow_now
msk_timestamp = moscow_timestamp

__all__ = [
    "MOSCOW_TZ",
    "MOSCOW_TIME_FORMAT",
    "moscow_now",
    "moscow_now_str",
    "moscow_timestamp",
    "ensure_moscow_timezone",
    "msk_now",
    "msk_timestamp",
]
