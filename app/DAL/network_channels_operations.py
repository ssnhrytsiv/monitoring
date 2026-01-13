"""
DAO for network_channels lookup.
"""
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.admin_bot.db import models as m


class NetworkChannelsDAO:
    def __init__(self, db: Session):
        self.db = db

    def get_network_for_channel(self, channel_id: int) -> Optional[Tuple[int, Optional[int]]]:
        """
        Повертає (network_id, admin_id) для каналу, якщо він прив'язаний до сітки.
        """
        row = (
            self.db.query(m.NetworkChannel.network_id, m.Network.admin_id)
            .outerjoin(m.Network, m.Network.id == m.NetworkChannel.network_id)
            .filter(m.NetworkChannel.channel_id == int(channel_id))
            .limit(1)
            .one_or_none()
        )
        if not row:
            return None
        net_id, adm_id = row
        return (int(net_id) if net_id is not None else None, int(adm_id) if adm_id is not None else None)


# Обгортка для сумісності
def get_network_for_channel(db: Session, channel_id: int) -> Optional[Tuple[int, Optional[int]]]:
    return NetworkChannelsDAO(db).get_network_for_channel(channel_id)
