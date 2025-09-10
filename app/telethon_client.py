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
    active=False,
    collected_links=set(),
    needle=None,
    monitors=[],
)

async def load_plugins():
    control_id = None
    if CONTROL_PEER:
        try:
            control_id = await client.get_peer_id(CONTROL_PEER)
            log.info("Resolved CONTROL_PEER=%r to peer_id=%s", CONTROL_PEER, control_id)
        except Exception as e:
            log.warning("Can't resolve CONTROL_PEER=%r: %s. Handlers will accept any chat.", CONTROL_PEER, e)

    log.debug("Loading plugins from package: %s", PLUGINS_PACKAGE)
    package = import_module(PLUGINS_PACKAGE)

    discovered = []
    for modinfo in pkgutil.iter_modules(package.__path__):
        name = modinfo.name
        ispkg = modinfo.ispkg
        log.debug("Discovered plugin candidate: %s (ispkg=%s)", name, ispkg)
        if ispkg or name.startswith("_"):
            continue
        discovered.append(name)

    log.debug("Filtered plugin module list: %s", discovered)

    for modname in discovered:
        full = f"{PLUGINS_PACKAGE}.{modname}"
        try:
            log.debug("Importing plugin module: %s", full)
            mod = import_module(full)
            setup_fn = getattr(mod, "setup", None)
            if callable(setup_fn):
                log.debug("Calling setup() of %s with kwargs (control_peer=%s, monitor_buffer=...)", full, control_id)
                setup_fn(client=client, control_peer=control_id, monitor_buffer=MONITOR_BUFFER)
                log.info("Loaded plugin: %s", full)
            else:
                log.debug("Module %s has no setup() – skipped", full)
        except Exception as e:
            log.exception("Failed to load plugin %s: %s", full, e)