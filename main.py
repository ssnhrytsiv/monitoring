from __future__ import annotations

import asyncio
import time
import os

from app.telethon_client import client, load_plugins
from app.services.account_pool import start_pool, stop_pool
from app.logging_json import configure_logging, get_logger
from app.services.post_watch_db import init as postwatch_init
from app.services import channel_db
from app.services import channel_maps
from app.services.requested_reconciler import run_requested_reconciler
from app.services import requested_reconciler_db as reqdb
from app.services.models import init_db as orm_init_db
from app.services.owner_conflict_guard import init as owner_guard_init
from app.services.posts_watch_result_db import init as posts_result_init
from dotenv import load_dotenv

load_dotenv()


from app.services.googlesheets.channels_export_service import (
    start_channels_exporter,
    stop_channels_exporter,
)

from app.bot.run import run_bot
from admin_bot.run import run_admin_bot
from admin_bot.config import ADMIN_BOT_TOKEN


def setup_logging():
    configure_logging()


async def _main():
    setup_logging()
    log = get_logger("main")

    reconciler_task = None
    exporter_task = None
    bot_task = None
    admin_bot_task = None

    def _log_task_result(name: str):
        def _inner(t: asyncio.Task):
            try:
                t.result()
            except asyncio.CancelledError:
                log.warning("%s task cancelled", name)
            except Exception:
                log.exception("%s task crashed", name)

        return _inner

    log.info("Ініціалізую БД…")
    t0 = time.perf_counter()
    try:
        postwatch_init()
        posts_result_init()
        channel_db.init()
        await channel_maps.init()
        reqdb.init()
        orm_init_db()
        owner_guard_init()
        log.debug("DB init complete")
    except Exception:
        log.exception("DB init error: one of init() failed")
        raise SystemExit(1)
    finally:
        log.debug("DB init took %.3fs", time.perf_counter() - t0)

    log.info("Запускаю головний клієнт…")
    t0 = time.perf_counter()
    try:
        await client.start()
        log.debug("Main client started")
    except Exception:
        log.exception("Failed to start main client")
        raise SystemExit(1)
    finally:
        log.debug("Main client start took %.3fs", time.perf_counter() - t0)

    log.info("Запускаю пул акаунтів…")
    t0 = time.perf_counter()
    try:
        await start_pool()
        log.debug("Account pool started")
    except Exception:
        log.exception("Failed to start account pool")
        try:
            await client.disconnect()
        except Exception:
            log.exception("Failed to disconnect main client after pool start failure")
        raise SystemExit(1)
    finally:
        log.debug("Account pool start took %.3fs", time.perf_counter() - t0)

    log.info("Запускаю reconciler заявок…")
    try:
        reconciler_task = asyncio.create_task(
            run_requested_reconciler(),
            name="requested_reconciler",
        )
        log.debug("Reconciler task created: %s", reconciler_task.get_name())
    except Exception:
        log.exception("Failed to create reconciler task")
        try:
            await stop_pool()
        except Exception:
            log.exception("stop_pool() failed after reconciler create failure")
        try:
            await client.disconnect()
        except Exception:
            log.exception("client.disconnect() failed after reconciler create failure")
        raise SystemExit(1)

    try:
        exporter_task = start_channels_exporter()
        if exporter_task:
            log.debug("Channels exporter task created: %s", exporter_task.get_name())
        else:
            log.info("Channels exporter is disabled or not configured; skipping")
    except Exception:
        log.exception("Failed to start channels exporter")

    log.info("Завантажую плагіни…")
    t0 = time.perf_counter()
    try:
        from app.settings import MONITOR_LINKS_V2
        if MONITOR_LINKS_V2:
            import app.plugins.monitor_links
        await load_plugins()
        log.debug("Plugins loaded")
    except Exception:
        log.exception("Failed to load plugins")
        try:
            if reconciler_task:
                reconciler_task.cancel()
                try:
                    await reconciler_task
                except asyncio.CancelledError:
                    log.debug("Reconciler task cancelled during plugin load failure")
        except Exception:
            log.exception("Error while cancelling reconciler on plugin load failure")
        try:
            await stop_pool()
        except Exception:
            log.exception("stop_pool() failed after plugin load failure")
        try:
            await client.disconnect()
        except Exception:
            log.exception("client.disconnect() failed after plugin load failure")
        raise SystemExit(1)
    finally:
        log.debug("Plugins load took %.3fs", time.perf_counter() - t0)

    try:
        log.info("BOT_TOKEN present=%s", bool(os.getenv("BOT_TOKEN")))
        bot_task = asyncio.create_task(run_bot(), name="bot_api_ui")
        bot_task.add_done_callback(_log_task_result("Bot UI"))
        log.info("Bot UI task created: %s", bot_task.get_name())
        # Даем обработчику каналов стартовать первым, чтобы не дергать оба токена одновременно.
        await asyncio.sleep(1.0)
    except Exception:
        log.exception("Failed to start Bot UI task")

    try:
        if ADMIN_BOT_TOKEN:
            admin_bot_task = asyncio.create_task(run_admin_bot(), name="admin_bot")
            admin_bot_task.add_done_callback(_log_task_result("Admin bot"))
            log.info("Admin bot task created: %s", admin_bot_task.get_name())
        else:
            log.info("ADMIN_BOT_TOKEN not set; admin bot is disabled")
    except Exception:
        log.exception("Failed to start Admin bot task")

    log.info("✅ Бот готовий. Чекаю подій…")

    try:
        await client.run_until_disconnected()
    except asyncio.CancelledError:
        log.warning("Main run loop cancelled")
        raise
    except Exception:
        log.exception("Main run loop error")
        raise
    finally:
        if bot_task:
            log.info("Зупиняю Bot UI…")
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                log.debug("Bot UI task cancelled")
            except Exception:
                log.exception("Bot UI task finished with error")

        if admin_bot_task:
            log.info("Зупиняю admin bot…")
            admin_bot_task.cancel()
            try:
                await admin_bot_task
            except asyncio.CancelledError:
                log.debug("Admin bot task cancelled")
            except Exception:
                log.exception("Admin bot task finished with error")

        if exporter_task:
            log.info("Зупиняю експортер каналів…")
            try:
                await stop_channels_exporter()
            except Exception:
                log.exception("Channels exporter stop failed")

        if reconciler_task:
            log.info("Зупиняю reconciler…")
            reconciler_task.cancel()
            try:
                await reconciler_task
            except asyncio.CancelledError:
                log.debug("Reconciler task cancelled")
            except Exception:
                log.exception("Reconciler task finished with error")

        log.info("Зупиняю пул акаунтів…")
        try:
            await stop_pool()
        except Exception:
            log.exception("stop_pool() failed")

        log.info("Від'єдную головний клієнт…")
        try:
            await client.disconnect()
        except Exception:
            log.exception("client.disconnect() failed")


if __name__ == "__main__":
    asyncio.run(_main())
