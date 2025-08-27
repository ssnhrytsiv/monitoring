# app/services/boot_gate.py
from __future__ import annotations

import logging
from app.services import kv_get, kv_put  # <-- беремо з пакета app.services, не з db

log = logging.getLogger("services.boot_gate")

# Ключ у KV, що блокує/дозволяє авто-обробку черги на старті
KEY_QUEUE_HOLD = "queue:hold"  # "1" = стоп, "0" = можна працювати


def is_hold() -> bool:
    """
    true => черга має бути зупинена (не стартувати автоматично).
    """
    return (kv_get(KEY_QUEUE_HOLD, "0") == "1")


def hold_on() -> None:
    """
    Увімкнути "режим утримання" черги (не запускати автоматично після старту).
    """
    kv_put(KEY_QUEUE_HOLD, "1")
    log.info("boot_gate: HOLD ON (queue processing disabled until manual continue)")


def hold_off() -> None:
    """
    Вимкнути утримання — дозволити обробку черги.
    """
    kv_put(KEY_QUEUE_HOLD, "0")
    log.info("boot_gate: HOLD OFF (queue processing allowed)")