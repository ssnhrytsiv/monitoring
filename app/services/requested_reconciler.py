# app/services/requested_reconciler.py
from __future__ import annotations

import os
import asyncio
import logging
from typing import List, Optional

from telethon.tl import types
from telethon.tl.functions.messages import CheckChatInviteRequest

from app.services import requested_reconciler_db as rdb
from app.services import membership_db
from app.services.account_pool import iter_pool_clients, session_name

log = logging.getLogger("services.requested_reconciler")

TICK_SEC = int(os.getenv("REQUESTED_RECONCILER_TICK", "15") or "15")
BATCH_LIMIT = int(os.getenv("REQUESTED_RECONCILER_BATCH", "30") or "30")


def _pool_sessions() -> List[str]:
    names = []
    for slot in iter_pool_clients():
        try:
            nm = getattr(slot, "name", None) or session_name(slot.client)
            if nm:
                names.append(nm)
        except Exception:
            continue
    return names


def _client_by_session(sess: str):
    for slot in iter_pool_clients():
        nm = getattr(slot, "name", None) or session_name(slot.client)
        if nm == sess:
            return slot.client
    return None


async def _check_invite_with_session(client, invite_hash: str) -> Optional[types.TypeMessage]:
    try:
        return await client(CheckChatInviteRequest(invite_hash))
    except Exception as e:
        log.warning(
            "[reconciler.invites] CheckChatInvite error (session=%s, invite=%s): %s",
            session_name(client), invite_hash, e
        )
        return None


async def run_requested_reconciler() -> None:
    log.debug("[reconciler.init] DB init start…")
    rdb.init()
    log.debug("[reconciler.init] DB init done")

    log.info("requested_reconciler started (tick=%ds, batch=%d)", TICK_SEC, BATCH_LIMIT)

    while True:
        try:
            sessions = _pool_sessions()
            log.debug("[reconciler] active sessions: %s", sessions)

            if not sessions:
                await asyncio.sleep(TICK_SEC)
                continue

            # --- 1) INVITES ---
            invites = rdb.due_invites(sessions=sessions, limit=BATCH_LIMIT)
            log.debug("[reconciler.invites] due invites count=%d", len(invites))

            for row in invites:
                invite_hash = row.invite_hash
                sess = row.session
                client = _client_by_session(sess)
                if client is None:
                    log.warning("[reconciler.invites] no client for session=%s; skipping", sess)
                    continue

                log.debug("[reconciler.invites] CheckChatInvite(session=%s, invite=%s)", sess, invite_hash)
                res = await _check_invite_with_session(client, invite_hash)
                if not res:
                    rdb.backoff_invite_miss(sess, invite_hash)
                    continue

                ch_obj = getattr(res, "chat", None)
                if isinstance(ch_obj, (types.Channel, types.Chat)):
                    cid = int(ch_obj.id)
                    title = getattr(ch_obj, "title", None)
                    membership_db.map_invite_set(invite_hash, cid, title)
                    membership_db.upsert_membership(sess, cid, "already")
                    rdb.clear_invite(sess, invite_hash)
                    log.debug(
                        "[reconciler.invites] ChatInviteAlready -> chat=%s, cid=%s",
                        type(ch_obj).__name__, cid
                    )
                else:
                    rdb.backoff_invite_miss(sess, invite_hash)
                    log.debug("[reconciler.invites] pending; backoff invite=%s sess=%s", invite_hash, sess)

            # --- 2) REQUESTED ---
            requested_rows = rdb.due_requested(
                sessions=sessions, per_account=BATCH_LIMIT, limit=BATCH_LIMIT
            )
            log.debug("[reconciler.requested] due rows=%d", len(requested_rows))

            for row in requested_rows:
                sess = row.session
                cid = row.channel_id

                st = membership_db.get_membership(sess, cid)
                if st in ("joined", "already", "invalid", "private", "blocked", "too_many"):
                    rdb.clear(sess, cid)
                    log.debug(
                        "[reconciler.requested] finalized via membership(%s,%s)=%s -> cleared",
                        sess, cid, st
                    )
                    continue

                rdb.backoff_miss(sess, cid)
                log.debug("[reconciler.requested] pending; backoff sess=%s cid=%s", sess, cid)

            await asyncio.sleep(TICK_SEC)

        except asyncio.CancelledError:
            log.warning("[reconciler] cancelled")
            raise
        except Exception:
            log.exception("[reconciler] main loop error")
            await asyncio.sleep(TICK_SEC)