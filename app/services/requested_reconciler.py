from __future__ import annotations

import os
import asyncio
import logging
import random
from collections import defaultdict
from typing import List, Optional

from telethon import errors
from telethon.tl import types
from telethon.tl.functions.messages import CheckChatInviteRequest
from telethon.tl.functions.channels import GetParticipantRequest

from app.services import requested_reconciler_db as rdb
from app.services import membership_db
from app.services.account_pool import iter_pool_clients, session_name

log = logging.getLogger("services.requested_reconciler")

TICK_SEC = int(os.getenv("REQUESTED_RECONCILER_TICK", "60") or "60")
BATCH_LIMIT = int(os.getenv("REQUESTED_RECONCILER_BATCH", "90") or "90")

# Пауза між перевірками, щоб не ловити FLOOD
INTER_DELAY_INV = float(os.getenv("REQUESTED_RECONCILER_INTER_DELAY_INVITE", "1.0") or "1.0")
INTER_DELAY_REQ = float(os.getenv("REQUESTED_RECONCILER_INTER_DELAY_REQUESTED", "1.0") or "1.0")
INTER_DELAY_JITTER = float(os.getenv("REQUESTED_RECONCILER_INTER_DELAY_JITTER", "0.3") or "0.3")

# Ліміт на кількість перевірок за один тік на одну сесію
PER_SESSION_INVITES = int(os.getenv("REQUESTED_RECONCILER_PER_SESSION_INVITES", "20") or "20")
PER_SESSION_REQUESTED = int(os.getenv("REQUESTED_RECONCILER_PER_SESSION_REQUESTED", "20") or "20")


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


def _sleep_delay(base: float) -> float:
    if base <= 0:
        return 0.0
    if INTER_DELAY_JITTER > 0:
        d = base + random.uniform(-INTER_DELAY_JITTER, INTER_DELAY_JITTER)
        return max(0.0, d)
    return base


async def _check_invite_with_session(client, invite_hash: str) -> Optional[types.TypeMessage]:
    try:
        return await client(CheckChatInviteRequest(invite_hash))
    except errors.FloodWaitError as e:
        log.warning(
            "[reconciler.invites] FLOOD (session=%s, invite=%s): %ss",
            session_name(client), invite_hash, e.seconds
        )
        return None
    except Exception as e:
        log.warning(
            "[reconciler.invites] CheckChatInvite error (session=%s, invite=%s): %s",
            session_name(client), invite_hash, e
        )
        return None


async def _is_member(client, channel_id: int) -> Optional[bool]:
    """
    Повертає True, якщо клієнт вже учасник каналу, False якщо ні, None при невідомій помилці.
    """
    try:
        ent = await client.get_entity(channel_id)
        res = await client(GetParticipantRequest(ent, 'me'))
        part = getattr(res, "participant", None)
        if isinstance(part, types.ChannelParticipant):
            return True
        return False
    except errors.FloodWaitError as e:
        log.warning("[reconciler.requested] FLOOD get_entity/participant (sess=%s, cid=%s): %ss",
                    session_name(client), channel_id, e.seconds)
        return None
    except Exception as e:
        log.debug("[reconciler.requested] membership check failed (sess=%s, cid=%s): %s",
                  session_name(client), channel_id, e)
        return False


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

            # --- 1) INVITES (за invite_hash) ---
            invites = rdb.due_invites(sessions=sessions, limit=BATCH_LIMIT)
            log.debug("[reconciler.invites] due invites count=%d", len(invites))

            # Групуємо по сесіях і обмежуємо кількість на сесію
            inv_by_sess = defaultdict(list)
            for row in invites:
                if len(inv_by_sess[row.session]) < PER_SESSION_INVITES:
                    inv_by_sess[row.session].append(row)

            for sess, rows in inv_by_sess.items():
                client = _client_by_session(sess)
                if client is None:
                    log.warning("[reconciler.invites] no client for session=%s; skipping batch", sess)
                    for row in rows:
                        rdb.backoff_invite_miss(sess, row.invite_hash)
                    continue

                for row in rows:
                    invite_hash = row.invite_hash
                    log.debug("[reconciler.invites] CheckChatInvite(session=%s, invite=%s)", sess, invite_hash)
                    res = await _check_invite_with_session(client, invite_hash)
                    if not res:
                        rdb.backoff_invite_miss(sess, invite_hash)
                        await asyncio.sleep(_sleep_delay(INTER_DELAY_INV))
                        continue

                    ch_obj = getattr(res, "chat", None)
                    # ChatInviteAlready → res.chat = Channel/Chat
                    if isinstance(ch_obj, (types.Channel, types.Chat)):
                        cid = int(ch_obj.id)
                        title = getattr(ch_obj, "title", None)
                        try:
                            membership_db.map_invite_set(invite_hash, cid, title)
                        except Exception:
                            pass
                        try:
                            membership_db.upsert_membership(sess, cid, "already")
                        except Exception:
                            pass
                        rdb.clear_invite(sess, invite_hash)
                        log.debug(
                            "[reconciler.invites] ChatInviteAlready -> chat=%s, cid=%s",
                            type(ch_obj).__name__, cid
                        )
                    else:
                        # Все ще pending (ChatInvite без .chat) → backoff
                        rdb.backoff_invite_miss(sess, invite_hash)
                        log.debug("[reconciler.invites] pending; backoff invite=%s sess=%s", invite_hash, sess)

                    await asyncio.sleep(_sleep_delay(INTER_DELAY_INV))

            # --- 2) REQUESTED (за channel_id) ---
            requested_rows = rdb.due_requested(
                sessions=sessions, per_account=BATCH_LIMIT, limit=BATCH_LIMIT
            )
            log.debug("[reconciler.requested] due rows=%d", len(requested_rows))

            # Групуємо по сесіях і обмежуємо кількість на сесію
            req_by_sess = defaultdict(list)
            for row in requested_rows:
                if len(req_by_sess[row.session]) < PER_SESSION_REQUESTED:
                    req_by_sess[row.session].append(row)

            for sess, rows in req_by_sess.items():
                client = _client_by_session(sess)
                if client is None:
                    log.warning("[reconciler.requested] no client for session=%s; skipping batch", sess)
                    for row in rows:
                        rdb.backoff_miss(sess, row.channel_id)
                    continue

                for row in rows:
                    cid = row.channel_id

                    # Якщо кеш вже говорить, що фіналізовано — очистити і далі
                    st = membership_db.get_membership(sess, cid)
                    if st in ("joined", "already", "invalid", "private", "blocked", "too_many"):
                        rdb.clear(sess, cid)
                        log.debug(
                            "[reconciler.requested] finalized via membership(%s,%s)=%s -> cleared",
                            sess, cid, st
                        )
                        await asyncio.sleep(_sleep_delay(INTER_DELAY_REQ))
                        continue

                    is_mem = await _is_member(client, cid)
                    if is_mem is True:
                        try:
                            membership_db.upsert_membership(sess, cid, "already")
                        except Exception:
                            pass
                        rdb.clear(sess, cid)
                        log.debug("[reconciler.requested] accepted -> already (sess=%s, cid=%s) -> cleared", sess, cid)
                    elif is_mem is False:
                        # Ще не прийнято → backoff
                        rdb.backoff_miss(sess, cid)
                        log.debug("[reconciler.requested] pending; backoff sess=%s cid=%s", sess, cid)
                    else:
                        # None (помилка/флуд) → теж backoff
                        rdb.backoff_miss(sess, cid)
                        log.debug("[reconciler.requested] unknown/missed; backoff sess=%s cid=%s", sess, cid)

                    await asyncio.sleep(_sleep_delay(INTER_DELAY_REQ))

            await asyncio.sleep(TICK_SEC)

        except asyncio.CancelledError:
            log.warning("[reconciler] cancelled")
            raise
        except Exception:
            log.exception("[reconciler] main loop error")
            await asyncio.sleep(TICK_SEC)