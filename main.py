# main.py
import asyncio
import time

from app.telethon_client import client, load_plugins
from app.services.account_pool import start_pool, stop_pool
from app.logging_json import configure_logging, get_logger
from app.services.post_watch_db import init as postwatch_init
from app.services import channel_db
from app.services.requested_reconciler import run_requested_reconciler
from app.services import requested_reconciler_db as reqdb
# ✅ ORM-метадані (idempotent create_all)
from app.services.models import init_db as orm_init_db
from app.services.owner_conflict_guard import init as owner_guard_init


def setup_logging():
    configure_logging()


async def _main():
    setup_logging()
    log = get_logger("main")

    reconciler_task = None

    # ---- DB init (одноразово, без дублювань)
    log.info("Ініціалізую БД…")
    t0 = time.perf_counter()
    try:
        postwatch_init()
        channel_db.init()
        reqdb.init()       # legacy-схеми/міграції для reconciler
        orm_init_db()      # ORM create_all (idempotent, нічого не ламає)
        owner_guard_init()
        log.debug("DB init complete")
    except Exception:
        log.exception("DB init error: one of init() failed")
        raise SystemExit(1)
    finally:
        log.debug("DB init took %.3fs", time.perf_counter() - t0)

    # ---- Telegram client + pool
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
        # спробуємо від'єднати головний клієнт перед виходом
        try:
            await client.disconnect()
        except Exception:
            log.exception("Failed to disconnect main client after pool start failure")
        raise SystemExit(1)
    finally:
        log.debug("Account pool start took %.3fs", time.perf_counter() - t0)

    # ---- Запускаємо reconciler ПІСЛЯ старту пулу
    log.info("Запускаю reconciler заявок…")
    try:
        reconciler_task = asyncio.create_task(
            run_requested_reconciler(),
            name="requested_reconciler",
        )
        log.debug("Reconciler task created: %s", reconciler_task.get_name())
    except Exception:
        log.exception("Failed to create reconciler task")
        # якщо не вийшло — зупиняємося чисто
        try:
            await stop_pool()
        except Exception:
            log.exception("stop_pool() failed after reconciler create failure")
        try:
            await client.disconnect()
        except Exception:
            log.exception("client.disconnect() failed after reconciler create failure")
        raise SystemExit(1)

    # ---- Плагіни
    log.info("Завантажую плагіни…")
    t0 = time.perf_counter()
    try:
        await load_plugins()
        log.debug("Plugins loaded")
    except Exception:
        log.exception("Failed to load plugins")
        # акуратно завершуємо
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
        # Акуратно зупиняємо reconciler
        if reconciler_task:
            log.info("Зупиняю reconciler…")
            reconciler_task.cancel()
            try:
                await reconciler_task
            except asyncio.CancelledError:
                log.debug("Reconciler task cancelled")
            except Exception:
                log.exception("Reconciler task finished with error")

        # Акуратно зупиняємо пул
        log.info("Зупиняю пул акаунтів…")
        try:
            await stop_pool()
        except Exception:
            log.exception("stop_pool() failed")

        # Від'єднуємо головний клієнт
        log.info("Від'єдную головний клієнт…")
        try:
            await client.disconnect()
        except Exception:
            log.exception("client.disconnect() failed")


if __name__ == "__main__":
    asyncio.run(_main())