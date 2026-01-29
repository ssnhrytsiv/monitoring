# app/telethon_client.py
"""
Telethon client + loader for plugins (app.plugins.*).
"""

import logging
import importlib
import pkgutil

from app.config import PLUGINS_PACKAGE

log = logging.getLogger("telethon_client")

client = None  # main client не використовується, але loaders працює
CONTROL_PEER = None


async def load_plugins():
    """
    Динамічно імпортує всі модулі з пакету app.plugins
    (setup всередині плагіна викликається при імпорті).
    """
    try:
        import app.plugins as plugins_pkg
    except Exception:
        log.warning("telethon_client: app.plugins package not found; skip plugins")
        return

    for _, modname, _ in pkgutil.iter_modules(plugins_pkg.__path__, plugins_pkg.__name__ + "."):
        try:
            module = importlib.import_module(modname)
            log.info("telethon_client: plugin loaded: %s", modname)
            setup_fn = getattr(module, "setup", None)
            if callable(setup_fn):
                try:
                    setup_fn(client=None, control_peer=None, monitor_buffer=None)
                    log.info("telethon_client: plugin setup executed: %s", modname)
                except Exception:
                    log.exception("telethon_client: plugin setup failed: %s", modname)
        except Exception:
            log.exception("telethon_client: failed to load plugin %s", modname)

    log.debug("telethon_client: plugins load finished")
