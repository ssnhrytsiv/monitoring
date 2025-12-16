"""Mass posting & timed deletion using the creator session (CREATOR_SESSION_NAME).

Public API (async):
 - post_to_channels(links, text=None, tpl_id=None, delete_after=None) -> list[result dict]
 - resolve_channels(links) -> list[Peer/channel]

Використовує той самий клієнт, що і seed_creator.ensure_client().
Текст може прийти напряму (text) або через tpl_id з таблиці post_template у БД post_watchdog.sqlite3.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import List, Optional, Dict, Any

from telethon import errors
from telethon.tl.types import PeerChannel

from app.services.feature import seed_creator
from app.services.feature.seed_creator import ensure_client
from app.services.post_watch_db import DB_PATH as POST_DB_PATH  # містить post_template
import sqlite3

log = logging.getLogger("seed_posts")


# ---------- helpers: templates ----------

def _load_template_text(tpl_id: int) -> Optional[str]:
    """Читає текст шаблону з таблиці post_template (колонка text)."""
    try:
        conn = sqlite3.connect(POST_DB_PATH)
        cur = conn.execute("SELECT text FROM post_template WHERE id = ?", (tpl_id,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        log.exception("seed_posts: failed to load template id=%s", tpl_id)
        return None


# ---------- helpers: links -> entities ----------

_INVITE_RE = re.compile(r"https?://t\.me/\+([A-Za-z0-9_\-]+)")

async def resolve_channels(links: List[str]) -> List[Any]:
    """Перетворює список посилань (@username або t.me/+invite) у сутності/ідентифікатори, придатні для send_message().
    ВАЖЛИВО: ми використовуємо сесію адміністратора каналів (CREATOR_SESSION_NAME),
    тому get_entity(invite_link) працює для власних каналів без зайвих join-ів.
    """
    c = await ensure_client()
    entities = []
    for raw in links:
        link = (raw or "").strip()
        if not link:
            continue
        try:
            # пряма спроба: Telethon сам розрулить @user / t.me/+... якщо є доступ
            ent = await c.get_entity(link)
            entities.append(ent)
            continue
        except Exception:
            pass

        # fallback для інвайтів: якщо з першого разу не вийшло (рідко)
        m = _INVITE_RE.match(link)
        if m:
            try:
                ent = await c.get_entity(link)  # повторна спроба; як правило цього достатньо
                entities.append(ent)
                continue
            except Exception:
                log.warning("seed_posts: cannot resolve invite %r; skipping", link)
                continue

        # якщо це звичайний @username, але не резолвиться — скіп
        if link.startswith("@"):
            log.warning("seed_posts: cannot resolve username %r; skipping", link)
            continue

        log.warning("seed_posts: unsupported link %r; skipping", link)
    return entities


# ---------- posting with timed deletion ----------

async def _delete_later(channel: Any, message_id: int, delay: int):
    """Локальний таймер видалення повідомлення (in-memory, не переживає рестарт)."""
    try:
        await asyncio.sleep(delay)
        c = await ensure_client()
        await c.delete_messages(entity=channel, message_ids=[message_id])
        log.info("seed_posts: deleted message mid=%s after %ss", message_id, delay)
    except Exception:
        log.exception("seed_posts: delete failed mid=%s", message_id)


async def post_to_channels(
    links: List[str],
    text: Optional[str] = None,
    tpl_id: Optional[int] = None,
    delete_after: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Постить у вказані канали. Повертає список результатів по кожному каналу:
       { 'link': str, 'ok': bool, 'message_id': Optional[int], 'error': Optional[str] }
    """
    if not text and not tpl_id:
        raise ValueError("Either text or tpl_id must be provided.")

    if tpl_id is not None:
        tpl_text = _load_template_text(int(tpl_id))
        if not tpl_text:
            raise ValueError(f"Template id={tpl_id} not found or empty.")
        text_final = tpl_text
    else:
        text_final = text or ""

    # розв'язуємо канали
    ents = await resolve_channels(links)
    c = await ensure_client()
    results: List[Dict[str, Any]] = []

    # невеликий ритм, щоб не ловити flood на send_message (креатор сесія безпечна, але все ж)
    async def _post_one(ent, link_repr: str):
        try:
            msg = await c.send_message(ent, text_final)
            mid = getattr(msg, "id", None)
            if delete_after and int(delete_after) > 0:
                asyncio.create_task(_delete_later(ent, mid, int(delete_after)))
            return {"link": link_repr, "ok": True, "message_id": mid, "error": None}
        except errors.FloodWaitError as e:
            sec = getattr(e, "seconds", 30)
            log.warning("seed_posts: FloodWait on send -> sleep %ss", sec)
            await asyncio.sleep(sec + 2)
            return {"link": link_repr, "ok": False, "message_id": None, "error": f"FloodWait({sec})"}
        except Exception as e:
            log.exception("seed_posts: send failed for %r", link_repr)
            return {"link": link_repr, "ok": False, "message_id": None, "error": str(e)}

    # підтримуємо початковий порядок
    for raw in links:
        link_repr = (raw or "").strip()
        if not link_repr:
            continue
        # знайдемо прив'язаний ent
        ent = None
        for e in ents:
            try:
                if hasattr(e, "username") and link_repr.lstrip("@").lower() == (e.username or "").lower():
                    ent = e
                    break
            except Exception:
                pass
        if ent is None:
            # просто візьмемо перший, який ще не використано (упростимо; для інвайтів важко мапити 1:1 без дод. запитів)
            if ents:
                ent = ents.pop(0)
            else:
                results.append({"link": link_repr, "ok": False, "message_id": None, "error": "unresolved"})
                continue

        res = await _post_one(ent, link_repr)
        results.append(res)
        # маленька пауза між постами
        await asyncio.sleep(0.8)

    return results