from __future__ import annotations

import asyncio
import time
import os

from dotenv import load_dotenv

# Load env before importing modules that read os.getenv at import time
load_dotenv()

from app.telethon_client import client, load_plugins  # noqa: E402
from app.services.account_pool import start_pool, stop_pool  # noqa: E402
from app.logging_json import configure_logging, get_logger  # noqa: E402
from app.services.requested_reconciler import run_requested_reconciler  # noqa: E402
from app.db.session import init_db as orm_init_db  # noqa: E402
from app.services.owner_conflict_guard import init as owner_guard_init  # noqa: E402


from app.watch_bot.run import run_bot  # noqa: E402
from app.admin_bot.run import run_admin_bot  # noqa: E402
from app.admin_bot.config import ADMIN_BOT_TOKEN  # noqa: E402
from app.notificator_bot.run import start_notificator_bot  # noqa: E402


def setup_logging():
    configure_logging()


async def _main():
    setup_logging()
    log = get_logger("main")

    reconciler_task = None
    bot_task = None
    admin_bot_task = None
    notifier_task = None

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
        notifier_task = asyncio.create_task(start_notificator_bot(), name="notificator_bot")
        notifier_task.add_done_callback(_log_task_result("Notifier bot"))
        log.info("Notifier bot task created: %s", notifier_task.get_name())
    except Exception:
        log.exception("Failed to start Notifier bot task")

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
