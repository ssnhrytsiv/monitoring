from __future__ import annotations

import os
import time
import asyncio
import logging
import random
from enum import Enum
from collections import defaultdict, deque
from typing import List, Optional, Tuple, Any
from contextlib import contextmanager

from telethon import errors
from telethon.tl import types
from telethon.tl.functions.messages import CheckChatInviteRequest
from telethon.tl.functions.channels import GetParticipantRequest

from app.DAL import requested_operations as rdb
from app.services import link_queue
from app.services.account_pool import iter_pool_clients, session_name
from app.DAL import SessionLocal
from app.DAL import channels_operations as cho
from app.DAL import invite_owners_operations as ioo
from app.DAL.membership_operations import MembershipDAO

log = logging.getLogger("services.requested_reconciler")

TICK_SEC = int(os.getenv("REQUESTED_RECONCILER_TICK", str(60 * 60)) or str(60 * 60))
BATCH_LIMIT = int(os.getenv("REQUESTED_RECONCILER_BATCH", "90") or "90")
PROCESSING_STALE_SEC = int(
    os.getenv("REQUESTED_RECONCILER_PROCESSING_STALE_SEC", str(15 * 60)) or str(15 * 60)
)
BACKFILL_MISSING_REQUESTED_INVITES_LIMIT = int(
    os.getenv(
        "REQUESTED_RECONCILER_BACKFILL_MISSING_REQUESTED_INVITES_LIMIT",
        str(BATCH_LIMIT),
    )
    or str(BATCH_LIMIT)
)
BACKFILL_MISSING_REQUESTED_INVITES_START_AFTER_SEC = int(
    os.getenv("REQUESTED_RECONCILER_BACKFILL_MISSING_REQUESTED_INVITES_START_AFTER_SEC", "60") or "60"
)

# Локальні короткі паузи між запитами
INTER_DELAY_INV = float(os.getenv("REQUESTED_RECONCILER_INTER_DELAY_INVITE", "3.0") or "3.0")
INTER_DELAY_REQ = float(os.getenv("REQUESTED_RECONCILER_INTER_DELAY_REQUESTED", "1.0") or "1.0")
INTER_DELAY_JITTER = float(os.getenv("REQUESTED_RECONCILER_INTER_DELAY_JITTER", "0.3") or "0.3")

# Ліміт на кількість перевірок за тік на одну сесію
PER_SESSION_INVITES = int(os.getenv("REQUESTED_RECONCILER_PER_SESSION_INVITES", "20") or "20")
PER_SESSION_REQUESTED = int(os.getenv("REQUESTED_RECONCILER_PER_SESSION_REQUESTED", "20") or "20")

# Rate limit для CheckChatInvite на одну сесію
INVITE_RL_MAX_CALLS = int(os.getenv("REQUESTED_RECONCILER_INVITE_RL_MAX_CALLS", "6") or "6")
INVITE_RL_WINDOW_SEC = int(os.getenv("REQUESTED_RECONCILER_INVITE_RL_WINDOW_SEC", "600") or "600")
# Мін. інтервал між invite-запитами на одну сесію: 5 хв
INVITE_MIN_SPACING_SEC = float(os.getenv("REQUESTED_RECONCILER_INVITE_MIN_SPACING_SEC", "300.0") or "300.0")
# ВИМКНУТО джиттер (щоб він не «з’їв» інтервал)
INVITE_SPACING_JITTER = float(os.getenv("REQUESTED_RECONCILER_INVITE_SPACING_JITTER", "0.0") or "0.0")
# ПІДЛОГА 5 хв — ефективний мінімум не нижче 300s
INVITE_MIN_SPACING_FLOOR_SEC = float(os.getenv("REQUESTED_RECONCILER_INVITE_MIN_SPACING_FLOOR_SEC", "300.0") or "300.0")

# Rate limit для requested-перевірок (get_entity/GetParticipantRequest) на одну сесію
REQUESTED_RL_MAX_CALLS = int(os.getenv("REQUESTED_RECONCILER_REQUESTED_RL_MAX_CALLS", "30") or "30")
REQUESTED_RL_WINDOW_SEC = int(os.getenv("REQUESTED_RECONCILER_REQUESTED_RL_WINDOW_SEC", "600") or "600")
REQUESTED_MIN_SPACING_SEC = float(os.getenv("REQUESTED_RECONCILER_REQUESTED_MIN_SPACING_SEC", "300.0") or "300.0")
REQUESTED_SPACING_JITTER = float(os.getenv("REQUESTED_RECONCILER_REQUESTED_SPACING_JITTER", "0.7") or "0.7")
REQUESTED_MIN_SPACING_FLOOR_SEC = float(
    os.getenv("REQUESTED_RECONCILER_REQUESTED_MIN_SPACING_FLOOR_SEC", "300.0") or "300.0"
)

FLOOD_SLACK_SEC = int(os.getenv("REQUESTED_RECONCILER_FLOOD_SLACK_SEC", "45") or "45")
FLOOD_MAX_WAIT_SEC = int(os.getenv("REQUESTED_RECONCILER_FLOOD_MAX_WAIT", "3600") or "3600")

FAIR_INVITES_FETCH = os.getenv("REQUESTED_RECONCILER_FAIR_INVITES_FETCH", "1") not in ("0", "false", "False")
# Діагностика rate-limiter'ів
RL_DEBUG = os.getenv("REQUESTED_RECONCILER_RL_DEBUG", "0").lower() not in ("0", "false", "")


def _db_session():
    return SessionLocal()


@contextmanager
def _membership_db():
    db = SessionLocal()
    try:
        yield MembershipDAO(db)
    finally:
        db.close()


def _get_invite_owner(invite_hash: str):
    db = _db_session()
    try:
        return ioo.get_invite_owner(db, invite_hash)
    finally:
        db.close()


def _find_channel(cid: int):
    db = _db_session()
    try:
        return cho.find_channel(db, cid)
    finally:
        db.close()


def _upsert_channel(cid: int, username, title, owner_display, owner_username, last_status):
    db = _db_session()
    try:
        cho.upsert_channel(db, cid, username, title, owner_display, owner_username, last_status)
    finally:
        db.close()


class InviteCheckStatus(Enum):
    OK = "ok"
    TRANSIENT = "transient"
    TERMINAL = "terminal"


class MemberStatus(Enum):
    MEMBER = "member"
    NOT_MEMBER = "not_member"
    TRANSIENT = "transient"
    BLOCKED = "blocked"
    TOO_MANY = "too_many"


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


class SlidingWindowRateLimiter:
    def __init__(
        self,
        max_calls: int,
        window_sec: float,
        min_spacing_sec: float,
        jitter: float,
        floor_sec: float = 0.0,
        name: str = "rl",
    ):
        self.max_calls = max_calls
        self.window_sec = window_sec
        self.min_spacing_sec = min_spacing_sec
        self.jitter = jitter
        self.min_spacing_floor_sec = max(0.0, float(floor_sec))
        self._calls = defaultdict(deque)
        self._last_ts = {}
        self.name = name

    async def acquire(self, key: str):
        loop = asyncio.get_running_loop()
        now = loop.time()
        dq = self._calls[key]
        cutoff = now - self.window_sec
        while dq and dq[0] < cutoff:
            dq.popleft()

        last = self._last_ts.get(key, None)
        spacing_need = 0.0
        if last is not None:
            spacing_need = (last + self._min_spacing_with_jitter()) - now

        window_need = 0.0
        if len(dq) >= self.max_calls:
            window_need = (dq[0] + self.window_sec) - now

        delay = max(0.0, spacing_need, window_need)
        if RL_DEBUG:
            log.debug("[rl.%s] key=%s delay=%.2fs spacing=%.2fs window=%.2fs calls_in_window=%d",
                      self.name, key, max(0.0, delay), max(0.0, spacing_need), max(0.0, window_need), len(dq))
        if delay > 0:
            await asyncio.sleep(delay)

        now2 = loop.time()
        dq.append(now2)
        self._last_ts[key] = now2

    def _min_spacing_with_jitter(self) -> float:
        eff = self.min_spacing_sec
        if self.jitter > 0:
            eff = eff + random.uniform(-self.jitter, self.jitter)
        return max(self.min_spacing_floor_sec, eff)


_invite_rl = SlidingWindowRateLimiter(
    INVITE_RL_MAX_CALLS,
    INVITE_RL_WINDOW_SEC,
    INVITE_MIN_SPACING_SEC,
    INVITE_SPACING_JITTER,
    floor_sec=INVITE_MIN_SPACING_FLOOR_SEC,
    name="invite",
)
_requested_rl = SlidingWindowRateLimiter(
    REQUESTED_RL_MAX_CALLS,
    REQUESTED_RL_WINDOW_SEC,
    REQUESTED_MIN_SPACING_SEC,
    REQUESTED_SPACING_JITTER,
    floor_sec=REQUESTED_MIN_SPACING_FLOOR_SEC,
    name="requested",
)

_flood_cooldown_until: dict[str, float] = defaultdict(float)
_flood_defer_applied_until: dict[str, float] = defaultdict(float)


def _in_flood_cooldown(sess: str) -> bool:
    return time.time() < _flood_cooldown_until.get(sess, 0.0)


def _set_flood_cooldown(sess: str, seconds: int) -> float:
    wait = max(0, int(min(seconds, FLOOD_MAX_WAIT_SEC)))
    until = time.time() + wait
    prev = _flood_cooldown_until.get(sess, 0.0)
    _flood_cooldown_until[sess] = max(prev, until)
    log.warning(
        "[reconciler] session=%s entering FLOOD cooldown for %ss (capped=%ss, until_epoch=%d)",
        sess, seconds, wait, int(_flood_cooldown_until[sess])
    )
    return _flood_cooldown_until[sess]


def _jittered(ts: float, spread: float = 0.2) -> float:
    return ts + random.uniform(-spread, spread) * max(1.0, ts - time.time())


def _apply_session_cooldown_db(sess: str, cooldown_until_epoch: float):
    target = cooldown_until_epoch + int(os.getenv("REQUESTED_RECONCILER_FLOOD_SLACK_SEC", FLOOD_SLACK_SEC))
    if target <= _flood_defer_applied_until.get(sess, 0.0):
        return

    target_with_jitter = _jittered(target)
    try:
        rdb.bulk_defer_session_invites(sess, target_with_jitter)
    except Exception as e:
        log.debug("[reconciler.invites] bulk_defer_session_invites failed (sess=%s): %s", sess, e)
    try:
        rdb.bulk_defer_session_requested(sess, target_with_jitter)
    except Exception as e:
        log.debug("[reconciler.requested] bulk_defer_session_requested failed (sess=%s): %s", sess, e)

    _flood_defer_applied_until[sess] = target_with_jitter
    log.info("[reconciler] session=%s deferred invites/requested until ~%d (tries not incremented)",
             sess, int(target_with_jitter))


async def _check_invite_with_session(client, invite_hash: str) -> Tuple["InviteCheckStatus", Optional[Any]]:
    sess = session_name(client)
    if _in_flood_cooldown(sess):
        return (InviteCheckStatus.TRANSIENT, "FLOOD_COOLDOWN_ACTIVE")

    queued_ts = time.time()
    log.debug("[reconciler.invites] queued for RL (session=%s, invite=%s)", sess, invite_hash)

    await _invite_rl.acquire(sess)

    waited = time.time() - queued_ts
    log.debug("[reconciler.invites] acquired RL after %.2fs → CheckChatInvite(session=%s, invite=%s)",
              waited, sess, invite_hash)
    try:
        res = await client(CheckChatInviteRequest(invite_hash))
        return (InviteCheckStatus.OK, res)
    except errors.FloodWaitError as e:
        until = _set_flood_cooldown(sess, e.seconds)
        _apply_session_cooldown_db(sess, until)
        return (InviteCheckStatus.TRANSIENT, "FLOOD_COOLDOWN_ACTIVE")
    except errors.InviteHashInvalidError:
        return (InviteCheckStatus.TERMINAL, "INVITE_HASH_INVALID")
    except errors.ChannelPrivateError:
        return (InviteCheckStatus.TERMINAL, "CHANNEL_PRIVATE")
    except errors.UserBannedInChannelError:
        return (InviteCheckStatus.TERMINAL, "USER_BANNED_IN_CHANNEL")
    except Exception as e:
        return (InviteCheckStatus.TRANSIENT, type(e).__name__)


async def _is_member(client, channel_id: int) -> "MemberStatus":
    sess = session_name(client)
    if _in_flood_cooldown(sess):
        return MemberStatus.TRANSIENT

    queued_ts = time.time()
    log.debug("[reconciler.requested] queued for RL (session=%s, cid=%s)", sess, channel_id)

    await _requested_rl.acquire(sess)

    waited = time.time() - queued_ts
    log.debug("[reconciler.requested] acquired RL after %.2fs → GetParticipant(session=%s, cid=%s)",
              waited, sess, channel_id)
    try:
        ent = await client.get_entity(channel_id)
        res = await client(GetParticipantRequest(ent, 'me'))
        part = getattr(res, "participant", None)
        if isinstance(part, types.ChannelParticipant):
            return MemberStatus.MEMBER
        return MemberStatus.NOT_MEMBER
    except errors.FloodWaitError as e:
        until = _set_flood_cooldown(sess, e.seconds)
        _apply_session_cooldown_db(sess, until)
        log.warning("[reconciler.requested] FLOOD get_entity/participant (sess=%s, cid=%s): %ss",
                    sess, channel_id, e.seconds)
        return MemberStatus.TRANSIENT
    except errors.ChannelPrivateError:
        log.debug(
            "[reconciler.requested] ChannelPrivateError (sess=%s, cid=%s) -> treat as pending",
            sess,
            channel_id,
        )
        return MemberStatus.NOT_MEMBER
    except errors.UserBannedInChannelError:
        return MemberStatus.BLOCKED
    except errors.ChannelsTooMuchError:
        return MemberStatus.TOO_MANY
    except Exception as e:
        log.debug("[reconciler.requested] membership check failed (sess=%s, cid=%s): %s",
                  sess, channel_id, e)
        return MemberStatus.TRANSIENT


async def run_requested_reconciler() -> None:
    log.debug("[reconciler.init] DB init start…")
    if hasattr(rdb, "init"):
        rdb.init()
        log.debug("[reconciler.init] DB init done")
    else:
        log.warning("[reconciler.init] skipped: requested_operations.init not implemented")

    last_reset_day = None

    log.info("requested_reconciler started (tick=%ds, batch=%d)", TICK_SEC, BATCH_LIMIT)
    while True:
        try:
            # Якщо зараз активні батчі (link_queue має processing), не заважаємо основному воркеру
            try:
                active_processing_total = link_queue.count_processing()
                if active_processing_total > 0:
                    active_processing_recent = link_queue.count_processing_recent(PROCESSING_STALE_SEC)
                    stale_processing_count = max(0, active_processing_total - active_processing_recent)
                    if active_processing_recent > 0:
                        log.debug(
                            "[reconciler] skip tick: processing_total=%d processing_recent=%d stale=%d",
                            active_processing_total,
                            active_processing_recent,
                            stale_processing_count,
                        )
                        await asyncio.sleep(TICK_SEC)
                        continue
                    log.warning(
                        "[reconciler] stale processing detected: total=%d stale=%d older_than=%ss; continue checks",
                        active_processing_total,
                        stale_processing_count,
                        PROCESSING_STALE_SEC,
                    )
            except Exception as e:
                log.debug("[reconciler] active-processing check failed: %s", e)

            # Щоденний скидання лічильників requested (раз на зміну дня)
            current_day = int(time.time() // 86400)
            if last_reset_day != current_day:
                try:
                    rows = rdb.reset_requested_daily()
                    log.debug("[reconciler.daily_reset] day=%s rows=%d", current_day, rows)
                except Exception as e:
                    log.debug("[reconciler.daily_reset] failed: %s", e)
                last_reset_day = current_day

            sessions = _pool_sessions()
            log.debug("[reconciler] active sessions: %s", sessions)
            if not sessions:
                await asyncio.sleep(TICK_SEC)
                continue

            try:
                backfilled_invite_checks_count = rdb.enqueue_missing_requested_invites_for_recheck(
                    session_names=sessions,
                    limit=BACKFILL_MISSING_REQUESTED_INVITES_LIMIT,
                    start_after_sec=BACKFILL_MISSING_REQUESTED_INVITES_START_AFTER_SEC,
                )
                if backfilled_invite_checks_count > 0:
                    log.info(
                        "[reconciler.invites] backfilled missing requested invite checks: count=%d",
                        backfilled_invite_checks_count,
                    )
            except Exception as exception:
                log.debug(
                    "[reconciler.invites] backfill missing requested invite checks failed: %s",
                    exception,
                )

            # --- 1) INVITES ---
            if FAIR_INVITES_FETCH:
                inv_by_sess: dict[str, list] = defaultdict(list)
                per_limit = max(1, min(PER_SESSION_INVITES, BATCH_LIMIT))
                for sess in sessions:
                    rows = rdb.due_invites(sessions=[sess], limit=per_limit)
                    if rows:
                        inv_by_sess[sess].extend(rows)
                total_due = sum(len(v) for v in inv_by_sess.values())
                log.debug("[reconciler.invites] due invites (fair) total=%d per_sess={%s}",
                          total_due, ", ".join(f"{s}:{len(v)}" for s, v in inv_by_sess.items()))
            else:
                invites = rdb.due_invites(sessions=sessions, limit=BATCH_LIMIT)
                inv_by_sess = defaultdict(list)
                for row in invites:
                    if len(inv_by_sess[row.session]) < PER_SESSION_INVITES:
                        inv_by_sess[row.session].append(row)
                log.debug("[reconciler.invites] due invites count=%d", len(invites))

            for sess, rows in inv_by_sess.items():
                client = _client_by_session(sess)
                if client is None:
                    log.warning("[reconciler.invites] no client for session=%s; skipping batch", sess)
                    try:
                        rdb.bulk_defer_session_invites(sess, time.time() + 300)
                    except Exception:
                        pass
                    continue

                if _in_flood_cooldown(sess):
                    log.debug("[reconciler.invites] session=%s in FLOOD cooldown; skip %d invites", sess, len(rows))
                    continue

                for row in rows:
                    invite_hash = row.invite_hash
                    log.debug("[reconciler.invites] submitting for check (session=%s, invite=%s)", sess, invite_hash)
                    status, payload = await _check_invite_with_session(client, invite_hash)

                    if status is InviteCheckStatus.TRANSIENT:
                        if payload != "FLOOD_COOLDOWN_ACTIVE" and not _in_flood_cooldown(sess):
                            rdb.backoff_invite_miss(sess, invite_hash)
                            log.debug("[reconciler.invites] transient(backoff); invite=%s sess=%s reason=%s",
                                      invite_hash, sess, payload)
                        else:
                            log.debug("[reconciler.invites] transient(cooldown); invite=%s sess=%s", invite_hash, sess)
                        await asyncio.sleep(_sleep_delay(INTER_DELAY_INV))
                        continue

                    if status is InviteCheckStatus.TERMINAL:
                        rdb.clear_invite(sess, invite_hash)
                        log.debug("[reconciler.invites] terminal; cleared invite=%s sess=%s reason=%s",
                                  invite_hash, sess, payload)
                        await asyncio.sleep(_sleep_delay(INTER_DELAY_INV))
                        continue

                    res = payload
                    ch_obj = getattr(res, "chat", None)
                    if isinstance(ch_obj, (types.Channel, types.Chat)):
                        cid = int(ch_obj.id)
                        title = getattr(ch_obj, "title", None)
                        try:
                            with _membership_db() as membership_db:
                                membership_db.map_invite_set(invite_hash, cid, title)
                                membership_db.upsert_membership(sess, cid, "already")
                                membership_db.invite_status_put(invite_hash, "already")
                        except Exception:
                            pass

                        # NEW: sticky owner from invite -> channel if channel has no owner yet
                        try:
                            inv_row = _get_invite_owner(str(invite_hash))
                        except Exception:
                            inv_row = None
                        if inv_row:
                            try:
                                ch_row = _find_channel(cid)
                            except Exception:
                                ch_row = None
                            ex_disp = (ch_row or {}).get("owner_display") if ch_row else None
                            ex_user = (ch_row or {}).get("owner_username") if ch_row else None
                            if not ex_disp and not ex_user:
                                od = inv_row.get("owner_display")
                                ou = inv_row.get("owner_username")
                                if od or ou:
                                    try:
                                        _upsert_channel(cid, None, title, od, ou, "already")
                                        log.debug("[reconciler.invites] set owner from invite (cid=%s invite=%s owner=%s/%s)",
                                                  cid, invite_hash, od, ou)
                                    except Exception as e:
                                        log.debug("[reconciler.invites] failed to set owner from invite (cid=%s invite=%s): %s",
                                                  cid, invite_hash, e)

                        rdb.clear_invite(sess, invite_hash)
                        log.debug("[reconciler.invites] visible -> chat=%s, cid=%s -> cleared",
                                  type(ch_obj).__name__, cid)
                    else:
                        rdb.backoff_invite_miss(sess, invite_hash)
                        log.debug("[reconciler.invites] pending(no chat); backoff invite=%s sess=%s",
                                  invite_hash, sess)

                    await asyncio.sleep(_sleep_delay(INTER_DELAY_INV))

            # --- 2) REQUESTED ---
            requested_rows = rdb.due_requested(
                sessions=sessions, per_account=BATCH_LIMIT, limit=BATCH_LIMIT
            )
            log.debug("[reconciler.requested] due rows=%d", len(requested_rows))

            req_by_sess = defaultdict(list)
            for row in requested_rows:
                if len(req_by_sess[row.session]) < PER_SESSION_REQUESTED:
                    req_by_sess[row.session].append(row)

            for sess, rows in req_by_sess.items():
                with _membership_db() as membership_db:
                    client = _client_by_session(sess)
                    if client is None:
                        log.warning("[reconciler.requested] no client for session=%s; skipping batch", sess)
                        try:
                            rdb.bulk_defer_session_requested(sess, time.time() + 300)
                        except Exception:
                            pass
                        continue

                    if _in_flood_cooldown(sess):
                        log.debug("[reconciler.requested] session=%s in FLOOD cooldown; skip %d requested rows",
                                  sess, len(rows))
                        continue

                    for row in rows:
                        cid = row.channel_id
                        st = membership_db.get_membership(sess, cid)
                        if st in ("joined", "already", "invalid", "blocked", "too_many"):
                            rdb.clear(sess, cid)
                            log.debug("[reconciler.requested] finalized via membership(%s,%s)=%s -> cleared", sess, cid, st)
                            await asyncio.sleep(_sleep_delay(INTER_DELAY_REQ))
                            continue

                        mstat = await _is_member(client, cid)

                        if mstat is MemberStatus.MEMBER:
                            try:
                                membership_db.upsert_membership(sess, cid, "already")
                            except Exception:
                                pass
                            try:
                                membership_db.invite_status_put_for_channel(cid, "already")
                            except Exception:
                                pass
                            rdb.clear(sess, cid)
                            log.debug("[reconciler.requested] accepted -> already (sess=%s, cid=%s) -> cleared", sess, cid)

                        elif mstat is MemberStatus.NOT_MEMBER:
                            rdb.backoff_miss(sess, cid)
                            log.debug("[reconciler.requested] pending; backoff sess=%s cid=%s", sess, cid)

                        elif mstat is MemberStatus.TRANSIENT:
                            if not _in_flood_cooldown(sess):
                                rdb.backoff_miss(sess, cid)
                                log.debug("[reconciler.requested] transient(backoff); sess=%s cid=%s", sess, cid)
                            else:
                                log.debug("[reconciler.requested] transient(cooldown); skip backoff sess=%s cid=%s",
                                          sess, cid)

                        elif mstat is MemberStatus.BLOCKED:
                            try:
                                membership_db.upsert_membership(sess, cid, "blocked")
                            except Exception:
                                pass
                            rdb.clear(sess, cid)
                            log.debug("[reconciler.requested] terminal -> blocked; cleared (sess=%s, cid=%s)", sess, cid)

                        elif mstat is MemberStatus.TOO_MANY:
                            try:
                                membership_db.upsert_membership(sess, cid, "too_many")
                            except Exception:
                                pass
                            rdb.clear(sess, cid)
                            log.debug("[reconciler.requested] terminal -> too_many; cleared (sess=%s, cid=%s)", sess, cid)

                        else:
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
