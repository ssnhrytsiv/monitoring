from __future__ import annotations

import asyncio
from typing import Optional, List, Dict, Any

from app.services.account_pool import iter_ready_pool_clients, session_name


class _RoundRobin:
    """
    Мінімальний RR для розподілу URL між готовими слотами пулу.
    Зберігає кільце і зсуває голову на кожен виклик pick().
    """

    def __init__(self) -> None:
        self._ring: List[str] = []
        self._pos: int = 0

    def _sid(self, slot) -> str:
        try:
            return getattr(slot, "name", None) or session_name(slot.client)
        except Exception:
            return "unknown"

    def pick(self, slots: List[Any]) -> Optional[Any]:
        if not slots:
            return None

        id_to_slot: Dict[str, any] = {}
        avail_ids: List[str] = []
        for s in slots:
            sid = self._sid(s)
            if sid not in id_to_slot:
                id_to_slot[sid] = s
                avail_ids.append(sid)

        # перебудовуємо кільце, зберігаючи попередній порядок
        new_ring = [sid for sid in self._ring if sid in avail_ids]
        for sid in avail_ids:
            if sid not in new_ring:
                new_ring.append(sid)
        self._ring = new_ring

        if not self._ring:
            return None

        if self._pos >= len(self._ring):
            self._pos %= len(self._ring)

        head_idx = self._pos
        ordered_ids = self._ring[head_idx:] + self._ring[:head_idx]
        self._pos = (head_idx + 1) % len(self._ring)

        for sid in ordered_ids:
            slot = id_to_slot.get(sid)
            if slot:
                return slot
        return None


_RR = _RoundRobin()


async def get_ready_slot(max_wait_sec: int = 30, step: float = 2.0, preferred_session: Optional[str] = None):
    """
    Чекає появи готового клієнта з пулу (не busy, без кулдауна).
    Повертає slot або None після таймауту.
    """
    waited = 0.0
    while waited <= max_wait_sec:
        slots = iter_ready_pool_clients()
        if preferred_session:
            pref_norm = preferred_session[:-8] if preferred_session.endswith(".session") else preferred_session
            for s in slots:
                s_norm = s.name[:-8] if s.name.endswith(".session") else s.name
                if s_norm == pref_norm:
                    return s
            # якщо preferred не знайдений або не готовий, падаємо в RR
            slots = iter_ready_pool_clients()
        slot = _RR.pick(slots)
        if slot:
            return slot
        await asyncio.sleep(step)
        waited += step
    return None


__all__ = ["get_ready_slot"]
