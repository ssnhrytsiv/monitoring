from __future__ import annotations

import os
import asyncio
import logging
from typing import Optional

from .export_channels_table import export_channels_table

log = logging.getLogger("channels_exporter")

_STATE = {
    "task": None,         # type: Optional[asyncio.Task]
    "stop_event": None,   # type: Optional[asyncio.Event]
}

def _is_enabled() -> bool:
    return (os.getenv("CHANNELS_EXPORT_ENABLED", "1").lower() in ("1", "true", "yes", "on"))

def _interval_seconds() -> int:
    try:
        return int(os.getenv("CHANNELS_EXPORT_INTERVAL_SECONDS", "86400"))
    except Exception:
        return 86400

async def _loop(stop_event: asyncio.Event, interval_sec: int) -> None:
    # Негайний запуск
    export_channels_table(logger=log)

    # Далі — перезапуск раз на інтервал
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            break
        export_channels_table(logger=log)

def start_channels_exporter() -> Optional[asyncio.Task]:
    """
    Стартує експортер як тло-вий таск. Повертає asyncio.Task або None, якщо вимкнено або не налаштовано.
    """
    if not _is_enabled():
        log.info("channels exporter disabled via CHANNELS_EXPORT_ENABLED")
        return None

    if not os.getenv("GSHEET_CHANNELS_SPREADSHEET_ID"):
        log.warning("GSHEET_CHANNELS_SPREADSHEET_ID is not set; channels exporter will not start")
        return None

    if _STATE["task"] is not None and not _STATE["task"].done():
        log.info("channels exporter already running")
        return _STATE["task"]

    stop_event = asyncio.Event()
    interval = _interval_seconds()
    task = asyncio.create_task(_loop(stop_event, interval), name="channels_exporter")
    _STATE["task"] = task
    _STATE["stop_event"] = stop_event
    log.info("channels exporter started: interval=%ss", interval)
    return task

async def stop_channels_exporter() -> None:
    """
    Акуратно зупиняє експортер, якщо він запущений.
    """
    task: Optional[asyncio.Task] = _STATE.get("task")
    stop_event: Optional[asyncio.Event] = _STATE.get("stop_event")
    if not task:
        return
    if stop_event and not stop_event.is_set():
        stop_event.set()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        log.exception("channels exporter task finished with error")
    finally:
        _STATE["task"] = None
        _STATE["stop_event"] = None
        log.info("channels exporter stopped")