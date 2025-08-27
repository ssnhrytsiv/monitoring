# main.py
import asyncio
import logging

from app.telethon_client import client, load_plugins
from app.config import LOG_LEVEL
from app.services.account_pool import start_pool, stop_pool
from app.services.link_queue import init as lq_init
from app.flows.batch_links.queue_worker import run_link_queue_worker


def setup_logging():
    fmt = "[%(asctime)s] %(levelname)-8s %(name)s: %(message)s"
    datefmt = "%H:%M:%S"
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format=fmt,
        datefmt=datefmt
    )
    # Telethon дуже “шумний” на DEBUG, тому знижуємо до INFO
    if LOG_LEVEL == "DEBUG":
        logging.getLogger("telethon").setLevel(logging.INFO)


async def _main():
    setup_logging()
    log = logging.getLogger("main")

    # Ініціалізація БД для link_queue (ідемпотентно)
    lq_init()

    log.info("Запускаю головний клієнт…")
    await client.start()

    log.info("Запускаю пул акаунтів…")
    await start_pool()   # піднімає всі сесії з ACCOUNTS у .env

    log.info("Завантажую плагіни…")
    await load_plugins()

    # Стартуємо воркер черги у фоні
    log.info("Стартую воркер черги…")
    queue_task = asyncio.create_task(run_link_queue_worker(client))

    log.info("✅ Бот готовий. Чекаю подій…")
    try:
        await client.run_until_disconnected()
    finally:
        # акуратне завершення
        queue_task.cancel()
        try:
            await queue_task
        except asyncio.CancelledError:
            pass
        await stop_pool()


if __name__ == "__main__":
    asyncio.run(_main())