"""
Chat plugin (optional) to control the independent seed generator from control chat.

Commands:
  /seed_channels count=10 mix
  /seed_channels public=5 private_open=3 private_closed=2 private_request=1 title_prefix=SEED
  /seed_links last=10
  /seed_help

Note: This module is OUTSIDE of app.plugins, so it won't be auto-loaded by your plugin loader.
You must import and call setup(...) manually from your app (see instructions below).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from telethon import events
from app.logging_json import get_logger
from app.services.feature import seed_creator
from app.services.feature import seed_db

log = get_logger("plugin.channel_seed")


HELP_TEXT = (
    "Seed generator commands:\n"
    "• /seed_channels count=10 mix\n"
    "• /seed_channels public=5 private_open=3 private_closed=2 private_request=1 title_prefix=SEED\n"
    "• /seed_links last=10\n"
    "\n"
    "Notes:\n"
    "— Works via dedicated session CREATOR_SESSION_NAME (default: tg_session_3).\n"
    "— Sends generated links to SEED_TARGET (default: tg_session).\n"
    "— Independent from account pool and join scheduler.\n"
)


def _parse_kv(s: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not s:
        return out
    parts = [p.strip() for p in s.split() if p.strip()]
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            # allow bare "mix"
            out[p] = "mix"
    return out


def setup(client=None, control_peer=None, monitor_buffer=None):
    """
    Register chat commands on the provided Telethon client.
    Only reacts in control chat if control_peer is set.
    """

    @client.on(events.NewMessage(pattern=r"^/seed_help$"))
    async def cmd_help(event):
        if control_peer and event.chat_id != control_peer:
            return
        await event.reply(HELP_TEXT)

    @client.on(events.NewMessage(pattern=r"^/seed_links(.*)"))
    async def cmd_seed_links(event):
        if control_peer and event.chat_id != control_peer:
            return
        args = _parse_kv(event.pattern_match.group(1).strip())
        try:
            n = int(args.get("last", "10"))
        except Exception:
            n = 10
        await event.reply(f"Resending last {n} links… Check logs.")
        client.loop.create_task(_resend_last_bg(n))

    async def _resend_last_bg(n: int):
        try:
            seed_db.init()
            rows = seed_db.last_created(n)
            links: List[str] = []
            for r in rows:
                inv = r.get("invite_link")
                uname = r.get("username")
                link = inv or (("@" + uname) if uname else None)
                if link:
                    links.append(link)
            if links:
                await seed_creator.send_links(seed_creator.SEED_TARGET, links)
                log.info("channel_seed: resent %d links to %s", len(links), seed_creator.SEED_TARGET)
            else:
                log.info("channel_seed: nothing to resend")
        except Exception:
            log.exception("channel_seed: resend_last failed")

    @client.on(events.NewMessage(pattern=r"^/seed_channels(.*)"))
    async def cmd_seed_channels(event):
        if control_peer and event.chat_id != control_peer:
            return
        args = _parse_kv(event.pattern_match.group(1).strip())
        await event.reply("Seeding started. Check logs for details.")
        client.loop.create_task(_seed_channels_bg(args))

    async def _seed_channels_bg(args: Dict[str, str]):
        """Background worker: parse args, call seed_creator, send links."""
        try:
            seed_db.init()

            # parse explicit mix or random
            mix: Dict[str, int] = {}
            if "public" in args:
                try:
                    mix["public"] = int(args["public"])
                except Exception:
                    pass
            if "private_open" in args:
                try:
                    mix["private_open"] = int(args["private_open"])
                except Exception:
                    pass
            if "private_closed" in args:
                try:
                    mix["private_closed"] = int(args["private_closed"])
                except Exception:
                    pass
            if "private_request" in args:
                try:
                    mix["private_request"] = int(args["private_request"])
                except Exception:
                    pass

            title_prefix = args.get("title_prefix", "SEED")

            if mix:
                total = sum(mix.values())
                log.info("channel_seed: explicit mix=%s (total=%d)", mix, total)
                metas = await seed_creator.create_batch(total, mix=mix, title_prefix=title_prefix)
            else:
                # count + optional "mix" flag → random mix
                try:
                    count = int(args.get("count", "6"))
                except Exception:
                    count = 6
                log.info("channel_seed: random mix count=%d", count)
                metas = await seed_creator.create_batch(count, mix=None, title_prefix=title_prefix)

            # prepare links and send
            links: List[str] = []
            for m in metas:
                inv = m.get("invite_link")
                uname = m.get("username")
                link = inv or (("@" + uname) if uname else None)
                if link:
                    links.append(link)
            if links:
                await seed_creator.send_links(seed_creator.SEED_TARGET, links)
                log.info("channel_seed: sent %d links to %s", len(links), seed_creator.SEED_TARGET)
            log.info("channel_seed: done metas=%d", len(metas))
        except Exception:
            log.exception("channel_seed: _seed_channels_bg failed")

    log.info("channel_seed plugin loaded (manual setup)")