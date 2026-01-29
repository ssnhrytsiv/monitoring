from __future__ import annotations

import asyncio
import time
import os

from dotenv import load_dotenv

# Load env before importing modules that read os.getenv at import time
load_dotenv()

from app.telethon_client import client, load_plugins
from app.services.account_pool import start_pool, stop_pool
from app.logging_json import configure_logging, get_logger
from app.services.requested_reconciler import run_requested_reconciler
from app.services.models import init_db as orm_init_db
from app.services.owner_conflict_guard import init as owner_guard_init

from app.services.googlesheets.channels_export_service import (
    start_channels_exporter,
    stop_channels_exporter,
)

from app.watch_bot.run import run_bot
from app.admin_bot.run import run_admin_bot
from app.admin_bot.config import ADMIN_BOT_TOKEN
from scripts.forward_bot import start_forward_bot
from app.notificator_bot.run import start_notificator_bot
from app.planning_bot.run import start_planning_bot


def setup_logging():
    configure_logging()


async def _main():
    setup_logging()
    log = get_logger("main")
    SKIP_MAIN_CLIENT = os.getenv("SKIP_MAIN_CLIENT") == "1"

    reconciler_task = None
    exporter_task = None
    bot_task = None
    admin_bot_task = None
    forward_bot_task = None
    notifier_task = None
    planning_bot_task = None

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
        orm_init_db()
        owner_guard_init()
        log.debug("DB init complete")
    except Exception:
        log.exception("DB init error: one of init() failed")
        raise SystemExit(1)
    finally:
        log.debug("DB init took %.3fs", time.perf_counter() - t0)

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
        forward_bot_task = asyncio.create_task(start_forward_bot(), name="forward_bot")
        forward_bot_task.add_done_callback(_log_task_result("Forward bot"))
        log.info("Forward bot task created: %s", forward_bot_task.get_name())
    except Exception:
        log.exception("Failed to start Forward bot task")

    try:
        notifier_task = asyncio.create_task(start_notificator_bot(), name="notificator_bot")
        notifier_task.add_done_callback(_log_task_result("Notifier bot"))
        log.info("Notifier bot task created: %s", notifier_task.get_name())
    except Exception:
        log.exception("Failed to start Notifier bot task")

    try:
        planning_bot_task = asyncio.create_task(start_planning_bot(), name="planning_bot")
        planning_bot_task.add_done_callback(_log_task_result("Planning bot"))
        log.info("Planning bot task created: %s", planning_bot_task.get_name())
    except Exception:
        log.exception("Failed to start Planning bot task")

    try:
        if ADMIN_BOT_TOKEN:
            admin_bot_task = asyncio.create_task(run_admin_bot(), name="admin_bot")
            admin_bot_task.add_done_callback(_log_task_result("Admin bot"))
            log.info("Admin bot task created: %s", admin_bot_task.get_name())
        else:
            log.info("ADMIN_BOT_TOKEN not set; admin bot is disabled")
    except Exception:
        log.exception("Failed to start Admin bot task")

    log.info("✅ Бот готовий. Головний клієнт вимкнений — чекаємо на задачі ботів.")

    try:
        await asyncio.gather(
            *[
                t
                for t in (
                    bot_task,
                    forward_bot_task,
                    notifier_task,
                    planning_bot_task,
                    admin_bot_task,
                    exporter_task,
                    reconciler_task,
                )
                if t
            ],
            return_exceptions=False,
        )
    except asyncio.CancelledError:
        log.warning("Main loop cancelled")
    except Exception:
        log.exception("Main loop error")
    finally:
        for t, name in (
            (bot_task, "Bot UI"),
            (forward_bot_task, "Forward bot"),
            (notifier_task, "Notifier bot"),
            (planning_bot_task, "Planning bot"),
            (admin_bot_task, "Admin bot"),
        ):
            if not t:
                continue
            log.info("Зупиняю %s…", name)
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                log.debug("%s task cancelled", name)
            except Exception:
                log.exception("%s task finished with error", name)

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
