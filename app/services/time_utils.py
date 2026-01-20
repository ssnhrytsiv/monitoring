from __future__ import annotations

# ruff: noqa: E402

"""
Сумісний шар: усі функції роботи з московським часом винесені в app.utils.time_utils.
Не додавайте нову логіку сюди, використовуйте time_utils як єдине джерело.
"""

from app.utils.time_utils import (  # noqa: F401
    MOSCOW_TZ,
    MOSCOW_TIME_FORMAT,
    ensure_moscow_timezone,
    moscow_now,
    moscow_now_str,
    moscow_timestamp,
    msk_now,
    msk_timestamp,
)

__all__ = [
    "MOSCOW_TZ",
    "MOSCOW_TIME_FORMAT",
    "ensure_moscow_timezone",
    "moscow_now",
    "moscow_now_str",
    "moscow_timestamp",
    "msk_now",
    "msk_timestamp",
]
