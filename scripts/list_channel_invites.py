#!/usr/bin/env python3
"""
List all exported invites for a channel by channel_id using an existing session.

Usage:
  API_ID=... API_HASH=... SESSION_NAME=tg_session.session python scripts/list_channel_invites.py <channel_id>
"""
import asyncio
import os
import sys
import typing
from datetime import datetime

from telethon import TelegramClient, types
from telethon.tl.functions.messages import (
    GetChatInviteImportersRequest,
    GetExportedChatInvitesRequest,
)
from telethon.utils import get_input_user


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/list_channel_invites.py <channel_id>")
        sys.exit(1)

    channel_id = int(sys.argv[1])
    api_id = int(os.getenv("API_ID", "0") or "0")
    api_hash = os.getenv("API_HASH", "")
    session_name = os.getenv("SESSION_NAME", "tg_session.session")

    if not api_id or not api_hash:
        print("API_ID and API_HASH must be set in environment.")
        sys.exit(1)

    async with TelegramClient(session_name, api_id, api_hash) as client:
        me = await client.get_me()
        peer = await client.get_input_entity(channel_id)
        offset_date = None
        offset_link = None
        limit = 50
        all_invites = []

        while True:
            res = await client(
                GetExportedChatInvitesRequest(
                    peer=peer,
                    admin_id=me,  # current admin
                    offset_date=offset_date,
                    offset_link=offset_link,
                    limit=limit,
                    revoked=False,
                )
            )
            invites = res.invites or []
            all_invites.extend(invites)
            if len(invites) < limit:
                break
            offset_date = invites[-1].date
            offset_link = invites[-1].link

        if not all_invites:
            print("No invites found or insufficient rights.")
            return

        for inv in all_invites:
            exp_ts = getattr(inv, "expire_date", None)
            exp = datetime.fromtimestamp(exp_ts).isoformat() if exp_ts else "—"
            print(
                f"link={inv.link} permanent={inv.permanent} revoked={inv.revoked} "
                f"request_needed={getattr(inv, 'request_needed', False)} "
                f"usage={inv.usage or 0}/{inv.usage_limit or '∞'} expire={exp}"
            )
            # Витягуємо імпортерів по цьому інвайту (доступно лише для лінків із заявками)
            try:
                if getattr(inv, "request_needed", False) is False:
                    print("  importers not available: invite without join-requests")
                    continue

                offset_date = None
                offset_user: typing.Any = types.InputUserEmpty()
                limit = 100
                total_imps = 0
                while True:
                    r = await client(
                        GetChatInviteImportersRequest(
                            peer=peer,
                            link=inv.link,
                            offset_date=offset_date,
                            offset_user=offset_user,
                            limit=limit,
                        )
                    )
                    imps = r.importers or []
                    total_imps += len(imps)
                    users_map = {u.id: u for u in (r.users or [])}
                    for imp in imps:
                        u = users_map.get(imp.user_id)
                        uname = f"@{u.username}" if u and getattr(u, "username", None) else ""
                        full_name = f"{getattr(u, 'first_name', '') or ''} {getattr(u, 'last_name', '') or ''}".strip()
                        who = uname or full_name or str(imp.user_id)
                        print(
                            f"  user_id={imp.user_id} ({who}) requested={imp.requested} "
                            f"approved_by={imp.approved_by} date={imp.date}"
                        )
                    if len(imps) < limit:
                        break
                    offset_date = imps[-1].date
                    # offset_user потребує InputUser; беремо з users_map, fallback – пустий
                    last_user = users_map.get(imps[-1].user_id)
                    offset_user = get_input_user(last_user) if last_user else types.InputUserEmpty()
                if total_imps == 0:
                    print("  (importers empty for this invite)")
            except Exception as e:
                print(f"  failed to fetch importers: {e}")


if __name__ == "__main__":
    asyncio.run(main())
