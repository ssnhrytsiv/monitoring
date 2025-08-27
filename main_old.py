# main.py
import asyncio

from app.telethon_client import client, load_plugins
from app.services.account_pool import start_pool, stop_pool
from app.logging_json import configure_logging, get_logger

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

    log.info("Запускаю головний клієнт…")
    await client.start()

    log.info("Запускаю пул акаунтів…")
    await start_pool()   # піднімає всі сесії з ACCOUNTS у .env

    log.info("Завантажую плагіни…")
    await load_plugins()

    log.info("✅ Бот готовий. Чекаю подій…")
    try:
        await client.run_until_disconnected()
    finally:
        await stop_pool()


if __name__ == "__main__":
    asyncio.run(_main())