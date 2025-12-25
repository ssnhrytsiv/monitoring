import html
import logging
import re
from datetime import datetime
from typing import Optional

from telethon import events
from telethon.tl.custom import Message

from app.services import channel_db

log = logging.getLogger("plugin.channel_info")


# ---------- Helpers ----------

def _esc(s: Optional[str]) -> str:
    if not s:
        return ""
    return html.escape(str(s))


def _parse_int(maybe: Optional[str], default: int, min_v=1, max_v=200) -> int:
    try:
        v = int(maybe)
        if v < min_v:
            return min_v
        if v > max_v:
            return max_v
        return v
    except Exception:
        return default


def _fmt_ts(val: Optional[str]) -> str:
    if val is None or val == "":
        return "—"
    try:
        ts = int(val)
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(val)


async def _reply(msg: Message, text: str):
    try:
        await msg.reply(text, parse_mode="html", link_preview=False)
    except Exception:
        try:
            await msg.reply(text)
        except Exception:
            pass


def _extract_args(raw: str, command: str) -> str:
    # Підтримує /cmd, /cmd@BotName і будь-які пробіли після
    pattern = rf"^/{command}(?:@\w+)?\s*(.*)$"
    m = re.match(pattern, raw, re.DOTALL)
    return m.group(1).strip() if m else ""


# ---------- Command Implementations ----------

async def _cmd_channels_owner(event: events.NewMessage.Event):
    args = _extract_args(event.raw_text, "channels_owner")
    parts = args.split()
    if not parts:
        return await _reply(event.message, "⚠️ Використання: /channels_owner <owner> [limit]")
    owner = parts[0]
    limit = _parse_int(parts[1], 30) if len(parts) > 1 else 30
    rows = channel_db.get_channels_by_owner(owner, limit=limit)
    if not rows:
        return await _reply(event.message, f"ℹ️ Каналів для '{_esc(owner)}' не знайдено")
    out = [f"📂 Канали для <b>{_esc(owner)}</b> (max {limit}):"]
    for (channel_id, username, title, last_status, owner_display, owner_username, updated_at) in rows:
        un_part = f"@{_esc(username)}" if username else "(без username)"
        ttl = _esc(title) if title else "—"
        st = _esc(last_status) if last_status else "?"
        out.append(f"• <code>{channel_id}</code> {un_part} — {ttl} — <i>{st}</i> [{_fmt_ts(updated_at)}]")
    await _reply(event.message, "\n".join(out))


async def _cmd_recent_channels(event: events.NewMessage.Event):
    args = _extract_args(event.raw_text, "recent_channels")
    limit = _parse_int(args or None, 25)
    rows = channel_db.recent_channels(limit=limit)
    if not rows:
        return await _reply(event.message, "ℹ️ Немає записів у channels")
    out = [f"🕒 Останні канали (max {limit}):"]
    for (channel_id, username, title, last_status, owner_display, owner_username, updated_at) in rows:
        owner_repr = owner_username or owner_display or "—"
        un_part = f"@{_esc(username)}" if username else "(—)"
        out.append(
            f"• <code>{channel_id}</code> {un_part} — {_esc(title) or '—'} — <i>{_esc(last_status) or '?'}"
            f"</i> — owner: {_esc(owner_repr)} — {_fmt_ts(updated_at)}"
        )
    await _reply(event.message, "\n".join(out))


async def _cmd_recent_links(event: events.NewMessage.Event):
    args = _extract_args(event.raw_text, "recent_links")
    limit = _parse_int(args or None, 30)
    rows = channel_db.recent_links(limit=limit)
    if not rows:
        return await _reply(event.message, "ℹ️ Немає записів у links")
    out = [f"🔗 Останні посилання (max {limit}):"]
    for (raw_url, channel_id, kind, owner_display, owner_username, added_at) in rows:
        cid = f"<code>{channel_id}</code>" if channel_id else "—"
        kind_s = kind or "?"
        owner_repr = owner_username or owner_display or "—"
        out.append(f"• {cid} [{_esc(kind_s)}] {_esc(raw_url)} — owner: {_esc(owner_repr)} ({_fmt_ts(added_at)})")
    await _reply(event.message, "\n".join(out))


async def _cmd_channel_info(event: events.NewMessage.Event):
    args = _extract_args(event.raw_text, "channel_info")
    q = args.strip()
    if not q:
        return await _reply(event.message, "⚠️ Використання: /channel_info <channel_id|@username|substr>")
    if q.isdigit():
        ch = channel_db.find_channel(int(q))
        if not ch:
            return await _reply(event.message, f"❌ Канал id={_esc(q)} не знайдено")
        text = [
            "ℹ️ Інформація про канал:",
            f"ID: <code>{ch['channel_id']}</code>",
            f"Username: @{_esc(ch['username'])}" if ch.get("username") else "Username: —",
            f"Title: {_esc(ch.get('title')) or '—'}",
            f"Owner(display): {_esc(ch.get('owner_display')) or '—'}",
            f"Owner(username): {_esc(ch.get('owner_username')) or '—'}",
            f"Last status: {_esc(ch.get('last_status')) or '—'}",
            f"Created: {_fmt_ts(ch.get('created_at'))}",
            f"Updated: {_fmt_ts(ch.get('updated_at'))}",
        ]
        return await _reply(event.message, "\n".join(text))
    username_candidate = q.lstrip("@")
    if " " not in q and len(username_candidate) >= 2:
        rows = channel_db.search_channels_by_username(username_candidate, limit=20)
        if not rows:
            return await _reply(event.message, f"❌ Нічого не знайдено за '{_esc(q)}'")
        out = [f"🔍 Результати для '{_esc(q)}':"]
        for (channel_id, username, title, last_status, owner_display, owner_username, updated_at) in rows:
            out.append(
                f"• <code>{channel_id}</code> @{_esc(username) if username else '—'} — {_esc(title) or '—'} — "
                f"<i>{_esc(last_status) or '?'}</i> owner: {_esc(owner_username or owner_display or '—')} ({_fmt_ts(updated_at)})"
            )
        return await _reply(event.message, "\n".join(out))
    return await _reply(event.message, "⚠️ Некоректний формат. Спробуй: число ID або @username / substring.")


async def _cmd_channels_help(event: events.NewMessage.Event):
    text = (
        "📘 Доступні команди:\n"
        "/channels_owner <owner> [limit]\n"
        "/recent_channels [limit]\n"
        "/recent_links [limit]\n"
        "/channel_info <channel_id|@username|substr>\n"
        "/channels_help\n"
    )
    await _reply(event.message, text)


# ---------- Setup ----------

def setup(client, control_peer=None, **kwargs):
    log.info("channel_info plugin setup start (control_peer=%s)", control_peer)

    def _chat_allowed(event) -> bool:
        if control_peer is None:
            return True
        return event.chat_id == control_peer

    async def _guarded(handler, event):
        if _chat_allowed(event):
            await handler(event)

    # Реєстрація (без incoming=, щоб ловити і outgoing)
    client.add_event_handler(lambda e: _guarded(_cmd_channels_help, e),
                             events.NewMessage(pattern=r"^/channels_help(?:@\w+)?(?:\s|$)"))
    client.add_event_handler(lambda e: _guarded(_cmd_channels_owner, e),
                             events.NewMessage(pattern=r"^/channels_owner(?:@\w+)?"))
    client.add_event_handler(lambda e: _guarded(_cmd_recent_channels, e),
                             events.NewMessage(pattern=r"^/recent_channels(?:@\w+)?"))
    client.add_event_handler(lambda e: _guarded(_cmd_recent_links, e),
                             events.NewMessage(pattern=r"^/recent_links(?:@\w+)?"))
    client.add_event_handler(lambda e: _guarded(_cmd_channel_info, e),
                             events.NewMessage(pattern=r"^/channel_info(?:@\w+)?"))

    log.info("channel_info plugin handlers registered (own messages enabled)")
