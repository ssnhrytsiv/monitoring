# app/telethon_client.py
"""
Stub telethon client: головний клієнт і control peer вимкнені.
Цей патч легко відкотити, повернувши створення TelegramClient із SESSION.
"""

import logging

from app.config import PLUGINS_PACKAGE
from importlib import import_module

log = logging.getLogger("telethon_client")

# Головний клієнт відключений
client = None
CONTROL_PEER = None


async def load_plugins():
    log.debug("telethon_client stub: load_plugins no-op (main client disabled)")
    try:
        package = import_module(PLUGINS_PACKAGE)
        log.debug("telethon_client stub: scanned package %s (no setup called)", package)
    except Exception:
        pass
    return True


