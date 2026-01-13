"""
Збирає підписки по кожній сесії, об'єднує їх і звіряє з БД каналів.

Кроки:
 1) Для кожної сесії читає всі dialog'и і витягує channel_id (Channel і Chat).
 2) Будує union усіх channel_id по сесіях.
 3) Зчитує channel_id з БД (таблиця channels).
 4) Показує, які channel_id є в БД, але відсутні в union сесій.

Запуск:
    python -m scripts.compare_db_with_sessions
    SESSIONS=foo.session,bar.session python -m scripts.compare_db_with_sessions   # перелік через кому для прямого підключення
    SKIP_POOL=1 python -m scripts.compare_db_with_sessions                        # пропустити пул і піти напряму
"""

import asyncio
import os
import sys
from typing import Dict, Iterable, List, Set

from telethon import TelegramClient, types
from sqlalchemy import delete, select

from app.config import API_HASH, API_ID
from app.services.account_pool import iter_pool_clients, session_name, start_pool, stop_pool
from app.admin_bot.db.session import SessionLocal
from app.admin_bot.db import models as m

DEFAULT_SESSIONS = [
    "tg_session.session",
    "tg_session_2.session",
    "tg_session_4.session",
]


def _known_channel_ids() -> Set[int]:
    db = SessionLocal()
    try:
        return {int(cid) for cid, in db.query(m.Channel.id).filter(m.Channel.id.isnot(None)).all()}
    finally:
        db.close()


async def _collect_session_channels(client) -> Set[int]:
    result: Set[int] = set()
    async for dlg in client.iter_dialogs():
        ent = dlg.entity
        if isinstance(ent, (types.Channel, types.Chat)):
            try:
                result.add(int(ent.id))
            except Exception:
                continue
    return result


async def _collect_from_pool() -> Dict[str, Set[int]]:
    per_session: Dict[str, Set[int]] = {}
    await start_pool()
    try:
        slots = list(iter_pool_clients())
        for slot in slots:
            sess_name = session_name(slot.client)
            ids = await _collect_session_channels(slot.client)
            per_session[sess_name] = ids
            print(f"[pool] {sess_name}: collected {len(ids)} channel ids")
    finally:
        try:
            await stop_pool()
        except asyncio.CancelledError:
            # ignore cancellation from background tasks that we explicitly stop
            pass
    return per_session


async def _collect_direct(sessions: Iterable[str]) -> Dict[str, Set[int]]:
    per_session: Dict[str, Set[int]] = {}
    if not API_ID or not API_HASH:
        print("API_ID/API_HASH not set; cannot collect without пул.")
        return per_session

    for sess_name in sessions:
        sess_name = sess_name.strip()
        if not sess_name:
            continue
        client = TelegramClient(sess_name, API_ID, API_HASH)
        await client.connect()
        ids = await _collect_session_channels(client)
        per_session[sess_name] = ids
        print(f"[direct] {sess_name}: collected {len(ids)} channel ids")
        await client.disconnect()
    return per_session


def _union(per_session: Dict[str, Set[int]]) -> Set[int]:
    union: Set[int] = set()
    for ids in per_session.values():
        union.update(ids)
    return union


def _report(known: Set[int], per_session: Dict[str, Set[int]]) -> None:
    union_ids = _union(per_session)
    missing = sorted(known - union_ids)
    print("--- Summary ---")
    print(f"Sessions processed: {len(per_session)}")
    for sess, ids in per_session.items():
        print(f"  {sess}: {len(ids)} channel ids")
    print(f"DB channel ids: {len(known)}")
    print(f"Union of sessions: {len(union_ids)}")
    print(f"Missing in sessions but present in DB: {len(missing)}")

    if not missing:
        return

    db = SessionLocal()
    try:
        rows = (
            db.query(m.Channel.id, m.Channel.title, m.Channel.owner_display, m.Channel.owner_username)
            .filter(m.Channel.id.in_(missing))
            .all()
        )
    finally:
        db.close()
    print("Details (cid, title, owner):")
    for cid, title, od, ou in rows:
        owner = od or (f"@{ou}" if ou else "—")
        print(f"  {cid}: {title or '—'} (owner: {owner})")

    # Видалення з БД, якщо не DRY_RUN
    dry_run = os.getenv("DRY_RUN", "1") not in ("0", "false", "False")
    if dry_run:
        print("DRY_RUN=1 → лише показ, без видалення.")
        return

    _purge_channels(missing)


def _purge_channels(missing_ids: List[int]) -> None:
    """
    Видаляє записи про канали з усіх пов'язаних таблиць admin_bot БД.
    """
    if not missing_ids:
        return

    db = SessionLocal()
    try:
        hashes = list(
            db.execute(
                select(m.InviteMap.invite_hash).where(m.InviteMap.channel_id.in_(missing_ids))
            ).scalars().all()
        )

        counts = {}
        counts["admin_channels"] = db.execute(
            delete(m.AdminChannel).where(m.AdminChannel.channel_id.in_(missing_ids))
        ).rowcount or 0
        counts["network_channels"] = db.execute(
            delete(m.NetworkChannel).where(m.NetworkChannel.channel_id.in_(missing_ids))
        ).rowcount or 0
        counts["membership"] = db.execute(
            delete(m.Membership).where(m.Membership.channel_id.in_(missing_ids))
        ).rowcount or 0
        counts["invite_status"] = (
            db.execute(delete(m.InviteStatus).where(m.InviteStatus.invite_hash.in_(hashes))).rowcount or 0
            if hashes
            else 0
        )
        counts["invite_map"] = db.execute(
            delete(m.InviteMap).where(m.InviteMap.channel_id.in_(missing_ids))
        ).rowcount or 0
        counts["owner_conflicts"] = db.execute(
            delete(m.OwnerConflict).where(m.OwnerConflict.channel_id.in_(missing_ids))
        ).rowcount or 0
        counts["links"] = db.execute(delete(m.Link).where(m.Link.channel_id.in_(missing_ids))).rowcount or 0
        counts["channels"] = db.execute(delete(m.Channel).where(m.Channel.channel_id.in_(missing_ids))).rowcount or 0
        db.commit()

        print("Deleted rows:")
        for k, v in counts.items():
            print(f"  {k}: {v}")
    finally:
        db.close()


async def main():
    known = _known_channel_ids()

    target_sessions: List[str] = []
    env_sessions = os.getenv("SESSIONS")
    if env_sessions:
        target_sessions = [s.strip() for s in env_sessions.split(",") if s.strip()]
    elif len(sys.argv) > 1:
        target_sessions = [s.strip() for s in sys.argv[1].split(",") if s.strip()]

    skip_pool = os.getenv("SKIP_POOL") in ("1", "true", "True") or os.getenv("USE_POOL") in ("0", "false", "False")

    per_session: Dict[str, Set[int]] = {}
    if not skip_pool:
        per_session = await _collect_from_pool()

    if skip_pool or not per_session:
        print("Pool is empty, using direct sessions.")
        if not target_sessions:
            target_sessions = DEFAULT_SESSIONS
        per_session = await _collect_direct(target_sessions)

    _report(known, per_session)


if __name__ == "__main__":
    asyncio.run(main())
