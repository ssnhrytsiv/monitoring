# app/telethon_client.py
import logging
from types import SimpleNamespace
from importlib import import_module
import pkgutil

from telethon import TelegramClient
from app.config import API_ID, API_HASH, SESSION, CONTROL_PEER, PLUGINS_PACKAGE

log = logging.getLogger("telethon_client")

client = TelegramClient(SESSION, API_ID, API_HASH)
client.parse_mode = "html"

# Shared state
MONITOR_BUFFER = SimpleNamespace(
    active=False,             # batch-links intake toggle
    collected_links=set(),    # normalized links collected during intake
    needle=None,              # captured needle text
    monitors=[],              # list of active monitor dicts
)

async def load_plugins():
    # resolve CONTROL_PEER -> numeric peer_id if possible
    control_id = None
    if CONTROL_PEER:
        try:
            control_id = await client.get_peer_id(CONTROL_PEER)
            log.info("Resolved CONTROL_PEER=%r to peer_id=%s", CONTROL_PEER, control_id)
        except Exception as e:
            log.warning("Can't resolve CONTROL_PEER=%r: %s. Handlers will accept any chat.", CONTROL_PEER, e)

    package = import_module(PLUGINS_PACKAGE)
    for _, modname, ispkg in pkgutil.iter_modules(package.__path__):
        if ispkg or modname.startswith("_"):
            continue
        full = f"{PLUGINS_PACKAGE}.{modname}"
        try:
            mod = import_module(full)
            if hasattr(mod, "setup"):
                mod.setup(client=client, control_peer=control_id, monitor_buffer=MONITOR_BUFFER)
                log.info("Loaded plugin: %s", full)
        except Exception as e:
            log.exception("Failed to load plugin %s: %s", full, e)