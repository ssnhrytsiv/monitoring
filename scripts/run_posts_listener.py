from __future__ import annotations

import asyncio
import signal
import time

from app.logging_json import configure_logging, get_logger
from app.services.models import init_db as orm_init_db
from app.services.owner_conflict_guard import init as owner_guard_init
from app.services.account_pool import start_pool, stop_pool
from app.plugins import posts_watch_listener


async def _run():
    configure_logging()
    log = get_logger("run_posts_listener")

    log.info("Init DB…")
    t0 = time.perf_counter()
    orm_init_db()
    owner_guard_init()
    log.debug("DB init took %.3fs", time.perf_counter() - t0)

    log.info("Starting account pool…")
    t0 = time.perf_counter()
    await start_pool()
    log.debug("Account pool start took %.3fs", time.perf_counter() - t0)

    log.info("Starting posts_watch_listener (standalone)…")
    posts_watch_listener.setup()

    stop_event = asyncio.Event()

    def _stop(*_):
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            # Windows
            pass

    await stop_event.wait()

    log.info("Stopping account pool…")
    await stop_pool()
    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(_run())
