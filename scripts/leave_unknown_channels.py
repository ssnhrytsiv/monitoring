"""
Перевіряє підписки пулових сесій і відписує від каналів, яких немає в нашій БД.

Логіка:
 1. Стартує account_pool і бере всі сесії з пулу.
 2. Зчитує список відомих channel_id з channel_db (таблиця channels).
 3. Для кожної сесії обходитиме діалоги і збирає реальні channel_id, де акаунт є учасником.
 4. Якщо знаходить канали, яких немає в БД, у режимі dry-run просто показує їх;
    у режимі виконання викликає leave_channels для відписки.

Запуск:
    python -m scripts.leave_unknown_channels          # лише показати
    DRY_RUN=0 python -m scripts.leave_unknown_channels # відписати
"""

import asyncio
import os
import sys
from typing import Set

from telethon import types
from telethon import functions, errors

from app.services.account_pool import (
    start_pool,
    stop_pool,
    iter_pool_clients,
    session_name,
    leave_channels,
)
from app.services import channel_db
from app.config import API_ID, API_HASH
from telethon import TelegramClient


def _known_channel_ids() -> Set[int]:
    conn = channel_db.raw_connection()
    cur = conn.execute("SELECT channel_id FROM channels WHERE channel_id IS NOT NULL")
    ids = {int(r[0]) for r in cur.fetchall() if r and r[0] is not None}
    return ids


async def _actual_channel_ids(client) -> Set[int]:
    out: Set[int] = set()
    async for dlg in client.iter_dialogs():
        ent = dlg.entity
        if isinstance(ent, types.Channel):
            try:
                out.add(int(ent.id))
            except Exception:
                continue
    return out


async def _process_client(client, sess: str, known: Set[int], dry_run: bool, use_pool_leave: bool):
    actual = await _actual_channel_ids(client)
    unknown = sorted(actual - known)
    missing_count = len(unknown)
    if missing_count == 0:
        print(f"[{sess}] ok: no unknown channels")
        return

    print(f"[{sess}] unknown channels: {missing_count} (will leave={missing_count if not dry_run else 0})")
    print(f"[{sess}] list: {unknown}")
    if dry_run:
        return

    if use_pool_leave:
        res = await leave_channels(sess, unknown)
        print(f"[{sess}] left={res['left']} errors={res['errors']}")
        return

    left, errors_cnt = 0, 0
    for cid in unknown:
        try:
            ent = await client.get_entity(cid)
            await client(functions.channels.LeaveChannelRequest(ent))
            left += 1
        except (errors.UserNotParticipantError, errors.ChannelPrivateError):
            errors_cnt += 1
        except Exception as e:
            errors_cnt += 1
            print(f"[{sess}] leave failed cid={cid}: {e}")
        await asyncio.sleep(0.5)
    print(f"[{sess}] left={left} errors={errors_cnt}")


async def main():
    dry_run = os.getenv("DRY_RUN", "1") not in ("0", "false", "False")
    target_session = os.getenv("SESSION") or os.getenv("SESSION_NAME")
    if not target_session and len(sys.argv) > 1:
        target_session = sys.argv[1]
    if target_session:
        target_session = target_session.strip()

    channel_db.init()
    known = _known_channel_ids()
    print(f"Known channels in DB: {len(known)}")

    # Спроба працювати через пул
    await start_pool()
    slots = iter_pool_clients()

    # Якщо пул порожній або потрібна конкретна сесія, яку не знайшли — використовуємо пряме підключення.
    if (not slots) and target_session:
        print("Pool is empty, using direct client for session:", target_session)
        if not API_ID or not API_HASH:
            print("API_ID/API_HASH not set; cannot create direct client.")
            return
        client = TelegramClient(target_session, API_ID, API_HASH)
        await client.connect()
        await _process_client(client, target_session, known, dry_run, use_pool_leave=False)
        await client.disconnect()
        return

    if target_session:
        slots = [s for s in slots if session_name(s.client) == target_session or getattr(s, "name", None) == target_session]
        if not slots:
            available = [session_name(s.client) or getattr(s, "name", None) for s in iter_pool_clients()]
            print(f"No session '{target_session}' found in pool. Available: {available}")
            await stop_pool()
            return

    for slot in slots:
        await _process_client(slot.client, session_name(slot.client), known, dry_run, use_pool_leave=True)

    await stop_pool()


if __name__ == "__main__":
    asyncio.run(main())
