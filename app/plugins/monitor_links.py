# app/plugins/monitor_links.py
"""
Monitor links v2:
- /monitor_links_on — вмикає прийом лінків із чату, парсить, резолвить, пише мапи,
  уникає зайвих join-спроб якщо вже підписані, сигналізує про конфлікт овнера.
- /monitor_links_off — вимикає.

Ключові фічі:
  • Мінімізація API: якщо по channel_id ми вже joined=True -> join НЕ викликаємо,
    лише апдейтимо мапи лінків (invite/username + title) і даємо інфомеседж.
  • Зв’язування лінку з channel_id: upsert_invite / upsert_username із title (коли доступний).
  • Конфлікт овнера: якщо канал уже закріплений за іншим owner — сигналізуємо.
  • Працюємо через join_scheduler (B-6): адаптивні ліміти, cooldown, джитери — вже вбудовано там.

Файл не залежить від "старої" v1-логіки і повністю самодостатній як плагін.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple
import re



_FALLBACK_TME_RE = re.compile(
    r'(?:(?:https?://)?t\.me/)(?:\+?[A-Za-z0-9_]+)',
    re.IGNORECASE
)

from telethon import events
from telethon.tl.types import Channel, Chat, User

# парсер лінків (беремо готовий універсальний із v1)
from app.utils.link_parser import collect_links
# без-API проба, що це за лінк і який channel_id (якщо можливо)
from app.services.joiner import probe_channel_id  # різні сигнатури у v1/v2

# B-6 планувальник join-ів
from app.services.join_scheduler import setup_join_scheduler, enqueue_join, join_status

# карти каналів/лінків/підписок
from app.services import channel_maps

# доступ до пулу акаунтів
from app.services import account_pool

# глобальні налаштування (тіньовий режим тощо)
from app import settings as _S

log = logging.getLogger("monitor_links")

# ---- внутрішній стан плагіна ----
_ACTIVE = False
_CONTROL_PEER: Optional[int] = None
_CLIENT = None

# owner-контекст (передається з telethon_client через monitor_buffer)
_OWNER_USERNAME: Optional[str] = None
_OWNER_DISPLAY: Optional[str] = None

# флаг тіньового режиму (не викликаємо реальний join, але все інше робимо)
MONITOR_LINKS_SHADOW: bool = bool(getattr(_S, "MONITOR_LINKS_SHADOW", False))


# ----------------------------- утиліти --------------------------------
async def _maybe(awaitable_or_value):
    """await, якщо це корутина; інакше повертає значення як є."""
    if inspect.isawaitable(awaitable_or_value):
        return await awaitable_or_value
    return awaitable_or_value  # якщо це вже значення — це OK


def _classify(url: str) -> str:
    """'private' якщо інвайт '+', інакше 'public' (username/інше)."""
    return "private" if url.startswith("https://t.me/+") or url.startswith("+") else "public"


async def _notify(text: str):
    """Надіслати сервісне повідомлення в контрольний чат (якщо він розвʼязаний)."""
    if not _CLIENT or not _CONTROL_PEER:
        return
    try:
        await _CLIENT.send_message(_CONTROL_PEER, text)
    except Exception:
        log.exception("notify failed")


async def _get_pool_sessions() -> List[Any]:
    """
    Повертає список TelegramClient з пулу.
    Підтримує різні інтерфейси account_pool:
      - iter_pool_clients()  <-- твій актуальний варіант
      - get_clients(), get_active_clients(), all_clients(), list_clients(), iter_clients()
      - атрибути: CLIENTS, POOL, ACTIVE
    Якщо елементи — це "слоти" з полем .client, витягуємо .client.
    """
    def _normalize_list(obj) -> List[Any]:
        # iter/generator -> list
        try:
            lst = list(obj)
        except TypeError:
            # не ітерується
            return []
        # витягуємо .client якщо це slot
        out = []
        for x in lst:
            c = getattr(x, "client", None)
            out.append(c if c is not None else x)
        return out

    # 1) найперше — твій публічний інтерфейс
    fn = getattr(account_pool, "iter_pool_clients", None)
    if callable(fn):
        res = fn()
        if inspect.isawaitable(res):
            res = await res
        clients = _normalize_list(res)
        if clients:
            return clients

    # 2) інші можливі імена
    try_names = (
        "get_clients",
        "get_active_clients",
        "all_clients",
        "list_clients",
        "iter_clients",
    )
    for name in try_names:
        fn = getattr(account_pool, name, None)
        if callable(fn):
            res = fn()
            if inspect.isawaitable(res):
                res = await res
            clients = _normalize_list(res)
            if clients:
                return clients

    # 3) атрибути-колекції
    for name in ("CLIENTS", "POOL", "ACTIVE"):
        obj = getattr(account_pool, name, None)
        if obj is not None:
            clients = _normalize_list(obj)
            if clients:
                return clients

    log.warning("monitor_links: cannot retrieve pool sessions; join scheduling may be inactive")
    return []


# ---------- БЕКВАРД-СУМІСНИЙ виклик probe_channel_id ------------------
async def _probe_any(url: str) -> Optional[Dict[str, Any]]:
    """
    Викликає services.joiner.probe_channel_id з урахуванням різних сигнатур:
      - probe_channel_id(url=...)
      - probe_channel_id(client, url)
      - probe_channel_id(client=_CLIENT, url=...)
      - probe_channel_id(url, client=_CLIENT)
    Повертає dict або None.
    """
    fn = probe_channel_id
    # спробуємо розпізнати параметри
    try:
        params = list(inspect.signature(fn).parameters.keys())
    except Exception:
        params = []

    # Набір кандидатів виклику (від безпечного до більш "вгадувального")
    candidates = []

    if "client" in params and "url" in params:
        candidates.append(lambda: fn(client=_CLIENT, url=url))
    if params == ["client", "url"] or params == ["self", "client", "url"]:
        candidates.append(lambda: fn(_CLIENT, url))
    if "url" in params and "client" not in params:
        candidates.append(lambda: fn(url=url))
        candidates.append(lambda: fn(url))
    # універсальні "останній шанс"
    candidates.append(lambda: fn(_CLIENT, url))
    candidates.append(lambda: fn(url=url))

    last_exc = None
    for call in candidates:
        try:
            return await _maybe(call())
        except TypeError as e:
            last_exc = e
            continue
        except Exception as e:
            last_exc = e
            break

    if last_exc:
        log.debug("probe_channel_id fallback failed for url=%s: %r", url, last_exc)
    return None


async def _resolve_url(url: str) -> Dict[str, Any]:
    """
    Витягуємо максимум інформації без важких API:
      - kind: 'invite'|'username'|'unknown'
      - invite: 'hash' якщо це +інвайт
      - username: '@name' або 'name'
      - channel_id: int | None
      - title: Optional[str] (коли є можливість)
    """
    info = await _probe_any(url)

    result = {
        "kind": "unknown",
        "invite": None,
        "username": None,
        "channel_id": None,
        "title": None,
        "url": url,
    }

    if not info:
        # евристика за самим URL
        result["kind"] = "invite" if url.startswith("https://t.me/+") or url.startswith("+") else "username"
        return result

    # очікувані ключі у реалізації: kind, invite, cid, username, title
    k = info.get("kind")
    if k:
        result["kind"] = k
    if info.get("invite"):
        result["invite"] = info.get("invite")
    if info.get("cid") is not None:
        try:
            result["channel_id"] = int(info["cid"])
        except Exception:
            pass
    if info.get("username"):
        u = info["username"]
        result["username"] = u if str(u).startswith("@") else f"@{u}"
    if info.get("title"):
        result["title"] = info["title"]

    if result["kind"] == "unknown":
        result["kind"] = "invite" if url.startswith("https://t.me/+") or url.startswith("+") else "username"

    return result


# ---------- мапи/джойн-логіка (без змін) ----------
async def _update_maps(res: Dict[str, Any]):
    cid = res.get("channel_id")
    title = res.get("title")
    if res["kind"] == "invite" and res.get("invite"):
        try:
            await _maybe(channel_maps.upsert_invite(res["invite"], cid, title))
        except Exception:
            log.exception("map upsert_invite failed")
    elif res["kind"] == "username" and res.get("username"):
        uname = res["username"].lstrip("@")
        try:
            await _maybe(channel_maps.upsert_username(uname, cid, title))
        except Exception:
            log.exception("map upsert_username failed")


async def _already_joined(cid: int) -> bool:
    try:
        row = await _maybe(channel_maps.get_subscription(int(cid)))
    except Exception:
        row = None
    if not row:
        return False
    joined = bool(row[1])
    return joined


async def _owner_of(cid: int) -> Optional[str]:
    try_names = ("get_owner", "get_channel_owner", "owner_of")
    for name in try_names:
        fn = getattr(channel_maps, name, None)
        if callable(fn):
            try:
                res = await _maybe(fn(int(cid)))
                if isinstance(res, (list, tuple)) and res:
                    val = res[0]
                else:
                    val = res
                if isinstance(val, str) and val:
                    return val if val.startswith("@") else f"@{val}"
            except Exception:
                log.exception("owner lookup failed via %s", name)
    return None


async def _process_links(urls: Iterable[str]):
    resolved: List[Dict[str, Any]] = []
    for u in urls:
        r = await _resolve_url(u)
        await _update_maps(r)
        resolved.append(r)

    by_cid: Dict[int, List[Dict[str, Any]]] = {}
    unknown: List[Dict[str, Any]] = []
    for r in resolved:
        if r.get("channel_id") is not None:
            by_cid.setdefault(int(r["channel_id"]), []).append(r)
        else:
            unknown.append(r)

    for cid, items in by_cid.items():
        if await _already_joined(cid):
            existing_owner = await _owner_of(cid)
            if _OWNER_USERNAME and existing_owner and (existing_owner.lower() != _OWNER_USERNAME.lower()):
                await _notify(
                    f"⚠️ Канал <code>{cid}</code> вже закріплений за {existing_owner}, "
                    f"а прийшов інвайт під іншим owner {_OWNER_USERNAME}. "
                    f"Join не виконуємо; лінк додано в карту."
                )
            else:
                await _notify(
                    f"ℹ️ Канал <code>{cid}</code> уже доданий/підписані. "
                    f"Лінк(и) збережено у мапі. Join пропущено."
                )
            continue

        invite = next((i["invite"] for i in items if i["kind"] == "invite" and i.get("invite")), None)
        username = next((i["username"] for i in items if i["kind"] == "username" and i.get("username")), None)
        eff = f"+{invite}" if invite else (username or None)
        if not eff:
            log.debug("monitor_links: no effective identifier for cid=%s; skip", cid)
            continue

        await enqueue_join(cid, eff, items[0].get("url"))

    for r in unknown:
        eff = None
        if r["kind"] == "invite" and r.get("invite"):
            eff = f"+{r['invite']}"
        elif r["kind"] == "username" and r.get("username"):
            eff = r["username"]
        if eff:
            await enqueue_join(r.get("channel_id") or 0, eff, r.get("url"))


# ----------------------------- публічні хендлери -----------------------------
def setup(client, control_peer: Optional[int] = None, monitor_buffer=None, **kwargs):
    global _CLIENT, _CONTROL_PEER, _OWNER_USERNAME, _OWNER_DISPLAY
    _CLIENT = client
    _CONTROL_PEER = control_peer

    if monitor_buffer is not None:
        _OWNER_USERNAME = getattr(monitor_buffer, "owner_username", None)
        _OWNER_DISPLAY = getattr(monitor_buffer, "owner_display", None)

    log.debug("B-5 session.create")

    async def _late_setup():
        retries = 15
        delay = 1.0
        sessions = []
        for _ in range(retries):
            sessions = await _get_pool_sessions()
            if sessions:
                break
            await asyncio.sleep(delay)

        if not sessions:
            log.warning("monitor_links: pool sessions not available after retries; join scheduling inactive")
            return

        try:
            await setup_join_scheduler(sessions)
            log.info("monitor_links: join_scheduler ready (sessions=%d)", len(sessions))
        except Exception:
            log.exception("monitor_links: setup_join_scheduler failed")

    asyncio.get_event_loop().create_task(_late_setup())

    @client.on(events.NewMessage(pattern=r"^/monitor_links_status$"))
    async def cmd_status(ev):
        try:
            st = join_status()
        except Exception:
            st = {"sessions": 0, "queued": 0}
        await ev.respond(
            f"monitor_links: {'ON' if _ACTIVE else 'OFF'}; "
            f"sessions={st.get('sessions', 0)} queued={st.get('queued', 0)}"
        )

    @client.on(events.NewMessage(pattern=r"^/monitor_links_on(\s+.*)?$"))
    async def cmd_on(ev):
        global _ACTIVE
        if _ACTIVE:
            await ev.respond("monitor_links: уже увімкнено")
            return

        if monitor_buffer is not None:
            nonlocal_owner = getattr(monitor_buffer, "owner_username", None)
            nonlocal_display = getattr(monitor_buffer, "owner_display", None)
        else:
            nonlocal_owner = None
            nonlocal_display = None

        if nonlocal_owner:
            _set_owner(nonlocal_owner, nonlocal_display)

        _ACTIVE = True
        log.info("B-5 cmd.on")

        await ev.respond("✅ monitor_links: ON")

    @client.on(events.NewMessage(pattern=r"^/monitor_links_off$"))
    async def cmd_off(ev):
        global _ACTIVE
        if not _ACTIVE:
            await ev.respond("monitor_links: уже вимкнено")
            return
        _ACTIVE = False
        log.info("B-5 cmd.off")
        await ev.respond("🛑 monitor_links: OFF")

    @client.on(events.NewMessage(incoming=True, outgoing=True))
    async def intake(ev):
        if not _ACTIVE:
            return
        if ev.message is None:
            return

        text = (ev.message.message or "").strip()
        if not text:
            return

        log.debug(
            "monitor_links.intake: chat=%s sender=%s text_len=%s",
            getattr(ev.chat_id, "__str__", lambda: str(ev.chat_id))(),
            getattr(getattr(ev, "sender_id", None), "__str__", lambda: str(getattr(ev, "sender_id", None)))(),
            len(ev.message.message or "")
        )

        try:
            raw_links = await _maybe(collect_links(ev.message))
        except Exception:
            log.exception("collect_links failed")
            return

        if not raw_links:
            return
        if isinstance(raw_links, str):
            links = [raw_links]
        else:
            try:
                links = list(raw_links)
            except TypeError:
                links = [str(raw_links)]

        # унікалізація і санітизація
        norm = []
        seen = set()
        for u in links:
            if not u:
                continue
            s = str(u).strip()
            if not _FALLBACK_TME_RE.search(s):
                continue
            if s not in seen:
                seen.add(s)
                norm.append(s)

        links = norm
        log.debug("monitor_links.intake: text_len=%d links_found=%d", len(text or ""), len(links))
        if not links:
            return

        try:
            await _process_links(links)
        except Exception:
            log.exception("intake processing failed")

        try:
            st = join_status()
        except Exception:
            st = {"sessions": 0, "queued": 0}
        log.info("B-5 batch.summary", extra={"queued": st.get("queued", 0), "sessions": st.get("sessions", 0)})


def _set_owner(username: Optional[str], display: Optional[str]):
    global _OWNER_USERNAME, _OWNER_DISPLAY
    if username:
        _OWNER_USERNAME = username if username.startswith("@") else f"@{username}"
    else:
        _OWNER_USERNAME = None
    _OWNER_DISPLAY = display