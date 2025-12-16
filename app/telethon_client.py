# app/telethon_client.py
import logging
from types import SimpleNamespace
from importlib import import_module
import pkgutil
import re

from telethon import TelegramClient
from app.config import API_ID, API_HASH, SESSION, CONTROL_PEER, PLUGINS_PACKAGE
from telethon.network.connection import ConnectionTcpAbridged
from app.settings import MONITOR_LINKS_V2  # ← прапор V2

log = logging.getLogger("telethon_client")

client = TelegramClient(SESSION, API_ID, API_HASH, connection=ConnectionTcpAbridged)
client.parse_mode = "html"

# Плагіни, які мають працювати лише в контрольному чаті
STRICT_CONTROLLED_PLUGINS = {
    "batch_links",
    "monitor_links",
    "owner_set",
    "help_and_ping",
    "resolve_channel",
    "channel_info",
    "monitor_watch",
}

# Shared state
MONITOR_BUFFER = SimpleNamespace(
    active=False,
    collected_links=set(),
    needle=None,
    monitors=[],
    owner_username=None,
    owner_display=None,
    pending_batch=None,
)

async def _resolve_control_peer() -> tuple[int | None, str]:
    """
    Повертає (control_id, reason).
    - Числове значення використовуємо напряму (без network lookup).
    - Інакше пробуємо client.get_peer_id().
    """
    if not CONTROL_PEER:
        return None, "not-set"

    s = str(CONTROL_PEER).strip()
    if re.fullmatch(r"-?\d+", s):
        # напряму приймаємо як chat_id
        try:
            cid = int(s)
            return cid, "parsed-numeric"
        except ValueError:
            return None, "numeric-parse-failed"

    try:
        cid = await client.get_peer_id(s)
        return cid, "resolved"
    except Exception as e:
        log.error("CONTROL_PEER resolve failed for %r: %s", CONTROL_PEER, e)
        return None, "resolve-failed"

async def load_plugins():
    control_id, how = await _resolve_control_peer()
    if control_id is not None:
        log.info("CONTROL_PEER %r -> peer_id=%s (%s)", CONTROL_PEER, control_id, how)
    else:
        log.warning(
            "CONTROL_PEER is not available (%s). Strict-controlled plugins will NOT be loaded.",
            how
        )

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

    # ---- V1/V2 взаємовиключення -----------------------------------------
    filtered = []
    for name in discovered:
        if MONITOR_LINKS_V2 and name == "batch_links":
            log.debug("Filtered out legacy plugin due to MONITOR_LINKS_V2=1: %s", name)
            continue
        if not MONITOR_LINKS_V2 and name == "monitor_links":
            log.debug("Filtered out V2 plugin due to MONITOR_LINKS_V2=0: %s", name)
            continue
        filtered.append(name)

    # Якщо CONTROL_PEER не доступний — не вантажимо керовані плагіни
    if control_id is None:
        filtered_strict = [n for n in filtered if n not in STRICT_CONTROLLED_PLUGINS]
        skipped = [n for n in filtered if n in STRICT_CONTROLLED_PLUGINS]
        if skipped:
            log.warning("Skipping strictly-controlled plugins due to missing CONTROL_PEER: %s", skipped)
        filtered = filtered_strict

    log.debug("Filtered plugin module list: %s", filtered)

    for modname in filtered:
        full = f"{PLUGINS_PACKAGE}.{modname}"
        try:
            log.debug("Importing plugin module: %s", full)
            mod = import_module(full)
            setup_fn = getattr(mod, "setup", None)
            if callable(setup_fn):
                log.debug(
                    "Calling setup() of %s with kwargs (control_peer=%s, monitor_buffer=...)",
                    full, control_id
                )
                setup_fn(client=client, control_peer=control_id, monitor_buffer=MONITOR_BUFFER)
                log.info("Loaded plugin: %s", full)
            else:
                log.debug("Module %s has no setup() – skipped", full)
        except Exception as e:
            log.exception("Failed to load plugin %s: %s", full, e)