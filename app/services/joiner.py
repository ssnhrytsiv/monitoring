import logging
import asyncio
import time
import uuid
from typing import Optional

from telethon.errors import (
    InviteHashInvalidError, InviteHashExpiredError,
    UserAlreadyParticipantError, FloodWaitError,
    UsernameNotOccupiedError, ChannelPrivateError,
)
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest

from app.services.membership_db import map_invite_set, map_invite_get, upsert_membership_with_retry, increment_attempt_count
from app.services.scheduling.models import ScheduledTask, ActionType
from app.services.scheduling.scheduler import TaskScheduler
from app.services.scheduling.rate_limiter import RateLimiterService
from app.services.scheduling.jitter import add_jitter
from app.config import NEW_SCHEDULER_ENABLED, RATE_LIMIT_GLOBAL_DEFAULTS, RATE_LIMIT_ACCOUNT_DEFAULTS

log = logging.getLogger("services.joiner")

# Global scheduler instances (initialized when needed)
_task_scheduler: Optional[TaskScheduler] = None
_rate_limiter: Optional[RateLimiterService] = None
_scheduler_running = False


async def probe_channel_id(client, url: str):
    """
    Повертає (channel_id, title, kind, invite_hash)
    kind: 'invite' | 'public'
    """
    is_invite = ("/+" in url) or ("joinchat" in url)
    if is_invite:
        inv = url.split("/")[-1].replace("+", "")
        mapped = map_invite_get(inv)
        if mapped:
            return mapped, None, "invite", inv
        try:
            info = await client(CheckChatInviteRequest(inv))
            chat = getattr(info, "chat", None)
            if chat is not None:
                return int(chat.id), getattr(chat, "title", None), "invite", inv
            return None, getattr(info, "title", None), "invite", inv
        except Exception:
            return None, None, "invite", inv
    else:
        try:
            ent = await client.get_entity(url)
            return int(getattr(ent, "id", 0) or 0), getattr(ent, "title", None), "public", None
        except Exception:
            return None, None, "public", None


async def ensure_join(client, url: str):
    """
    Реальна спроба приєднання.
    Повертає (status, title, kind, channel_id|None, invite_hash|None)
    """
    is_invite = ("/+" in url) or ("joinchat" in url)
    try:
        if is_invite:
            inv = url.split("/")[-1].replace("+", "")
            updates = await client(ImportChatInviteRequest(inv))
            ch = updates.chats[0] if getattr(updates, "chats", None) else None
            cid = int(ch.id) if ch else None
            title = getattr(ch, "title", "?") if ch else "?"
            if inv and cid:
                map_invite_set(inv, cid)
            return "joined", title, "invite", cid, inv

        ent = await client.get_entity(url)
        try:
            await client(JoinChannelRequest(ent))
            return "joined", getattr(ent, "title", "?"), "public", int(getattr(ent, "id", 0) or 0), None
        except UserAlreadyParticipantError:
            return "already", getattr(ent, "title", None), "public", int(getattr(ent, "id", 0) or 0), None

    except UserAlreadyParticipantError:
        return "already", None, "invite" if is_invite else "public", None, None
    except (InviteHashInvalidError, InviteHashExpiredError):
        return "invalid", None, "invite", None, url.split("/")[-1].replace("+", "")
    except ChannelPrivateError:
        return "private", None, "invite" if is_invite else "public", None, None
    except FloodWaitError as e:
        return f"flood_wait_{e.seconds}", None, "invite" if is_invite else "public", None, None
    except Exception as e:
        msg = str(e) if e else "error"
        if "Too many channels" in msg or "CHANNELS_TOO_MUCH" in msg:
            return "too_many", None, "public", None, None
        if "USER_BANNED_IN_CHANNEL" in msg or "USER_KICKED" in msg:
            return "blocked", None, "public", None, None
        if "INVITE_REQUEST_SENT" in msg:
            return "requested", None, "invite" if is_invite else "public", None, None
        return "error", msg, "invite" if is_invite else "public", None, None


# ---------- Scheduling system functions ----------

def _get_scheduler() -> TaskScheduler:
    """Get or create the global task scheduler."""
    global _task_scheduler
    if _task_scheduler is None:
        _task_scheduler = TaskScheduler()
    return _task_scheduler


def _get_rate_limiter() -> RateLimiterService:
    """Get or create the global rate limiter."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiterService(
            RATE_LIMIT_GLOBAL_DEFAULTS,
            RATE_LIMIT_ACCOUNT_DEFAULTS
        )
    return _rate_limiter


def enqueue_join(url: str, account: str, priority: int = 100, delay_seconds: float = 0.0):
    """Enqueue a JOIN action through the scheduler."""
    if not NEW_SCHEDULER_ENABLED:
        log.debug("Scheduler disabled, ignoring enqueue_join for %s", url)
        return

    scheduler = _get_scheduler()
    task_id = str(uuid.uuid4())
    not_before = time.time() + add_jitter(delay_seconds) if delay_seconds > 0 else 0.0
    
    task = ScheduledTask(
        id=task_id,
        action_type=ActionType.JOIN,
        payload={"url": url, "account": account},
        priority=priority,
        not_before=not_before
    )
    
    scheduler.add_task(task)
    log.debug("Enqueued JOIN task %s for %s (account: %s)", task_id, url, account)


async def scheduler_loop():
    """Main scheduler loop that processes tasks from the queue."""
    global _scheduler_running
    if _scheduler_running:
        log.warning("Scheduler loop already running")
        return
        
    _scheduler_running = True
    log.info("Starting scheduler loop")
    
    scheduler = _get_scheduler()
    rate_limiter = _get_rate_limiter()
    
    try:
        while _scheduler_running:
            task = scheduler.pop_ready(rate_limiter)
            if task is None:
                # No task ready, wait a bit
                delay = scheduler.peek_delay() or 1.0
                await asyncio.sleep(min(delay, 5.0))
                continue
                
            # Process the task
            try:
                await _process_scheduled_task(task)
            except Exception as e:
                log.exception("Error processing scheduled task %s: %s", task.id, e)
                
            # Small delay between tasks to avoid overwhelming
            await asyncio.sleep(0.1)
            
    except Exception as e:
        log.exception("Scheduler loop error: %s", e)
    finally:
        _scheduler_running = False
        log.info("Scheduler loop stopped")


async def retry_refill_loop():
    """Stub for retry refill loop - to be implemented in future steps."""
    log.info("Retry refill loop stub - not implemented yet")
    # TODO: Implement URL reconstruction mapping for re-enqueue
    pass


async def _process_scheduled_task(task: ScheduledTask):
    """Process a single scheduled task."""
    if task.action_type != ActionType.JOIN:
        log.warning("Unknown action type %s in task %s", task.action_type, task.id)
        return
        
    url = task.payload.get("url")
    account = task.payload.get("account")
    
    if not url or not account:
        log.error("Missing url/account in task %s payload", task.id)
        return
        
    log.debug("Processing JOIN task %s: %s (account: %s)", task.id, url, account)
    
    # TODO: Get actual client for the account - for now just log
    # In future steps this will integrate with account pool
    # status, title, kind, channel_id, invite_hash = await ensure_join(client, url)
    log.info("Would process JOIN for %s with account %s", url, account)