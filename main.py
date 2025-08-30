import asyncio

from app.telethon_client import client, load_plugins
from app.services.account_pool import start_pool, stop_pool
from app.logging_json import configure_logging, get_logger
from app.services.post_watch_db import init as postwatch_init  # ⇦ додано


def setup_logging():
    # Ініціалізуємо структуроване або plain логування згідно з env:
    # LOG_JSON=1 -> JSON формат
    # LOG_PLAIN_FIELDS=0 -> plain без key=value полів
    configure_logging()


async def _main():
    setup_logging()
    log = get_logger("main")

    # Ініціалізація схеми БД для шаблонів постів (безпечно викликати багаторазово)
    try:
        postwatch_init()
    except Exception as e:
        log.error("post_watch_db init failed: %s", e)
        raise

    log.info("Запускаю головний клієнт…")
    await client.start()

    log.info("Запускаю пул акаунтів…")
    await start_pool()

    log.info("Завантажую плагіни…")
    await load_plugins()

    log.info("✅ Бот готовий. Чекаю подій…")
    try:
        await client.run_until_disconnected()
    finally:
        await stop_pool()


if __name__ == "__main__":
    asyncio.run(_main())