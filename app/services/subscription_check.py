# app/services/subscription_check.py
import logging
from typing import Optional

from telethon.tl.functions.channels import GetParticipantRequest
from telethon.errors import ChannelInvalidError, ChannelPrivateError

from app.services.account_pool import iter_pool_clients, session_name

log = logging.getLogger("services.subscription_check")

async def is_already_subscribed_any(url: str) -> Optional[str]:
    """
    Якщо бодай один акаунт із пулу вже підписаний на канал/чат 'url',
    повертає назву його сесії (для статусу). Інакше None.
    """
    for slot in iter_pool_clients():
        client = slot.client
        try:
            ent = await client.get_entity(url)
            me = await client.get_me()
            await client(GetParticipantRequest(ent, me.id))
            # якщо не впало — ми учасник
            return session_name(client)
        except (ChannelInvalidError, ChannelPrivateError):
            # не канал або недоступний цьому клієнту — пробуємо далі
            continue
        except Exception:
            continue
    return None