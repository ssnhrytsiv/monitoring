from __future__ import annotations

import logging
from sqlalchemy import Column, Integer, String, Text, PrimaryKeyConstraint, Index, UniqueConstraint

from app.db.session import Base, engine

log = logging.getLogger("notificator.models")


class NotifierState(Base):
    """
    Зберігаємо факт відправки нотифікації, щоб не дублікувати.
    """

    __tablename__ = "notifier_state"

    event_id = Column(Text, nullable=False)
    project = Column(String(64), nullable=True)
    watch_id = Column(Integer, nullable=True)
    event_type = Column(String(64), nullable=True)
    updated_at = Column(Integer, nullable=True)
    sent_at = Column(Integer, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("event_id", name="pk_notifier_state"),
        Index("idx_notifier_project", "project"),
        Index("idx_notifier_updated", "updated_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<NotifierState event_id={self.event_id} project={self.project} "
            f"event_type={self.event_type} sent_at={self.sent_at}>"
        )


class NotifierMessage(Base):
    """
    Зберігаємо останнє надіслане повідомлення по group_id,
    щоб мати змогу видалити його при оновленнях.
    """

    __tablename__ = "notifier_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(Integer, nullable=False)
    project = Column(String(64), nullable=True)
    admin = Column(Text, nullable=True)
    group_id = Column(Integer, nullable=False)
    message_id = Column(Integer, nullable=False)
    updated_at = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("chat_id", "project", "admin", "group_id", name="uq_notifier_message_target"),
        Index("idx_notifier_msg_group", "group_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<NotifierMessage chat_id={self.chat_id} project={self.project} "
            f"admin={self.admin} group_id={self.group_id} message_id={self.message_id}>"
        )


class NotifierMessagePage(Base):
    """
    Зберігаємо сторінки довгого повідомлення та прив'язку до Telegram message.
    """

    __tablename__ = "notifier_message_pages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    notification_page_session_identifier = Column(String(64), nullable=False)
    page_number = Column(Integer, nullable=False)
    page_text = Column(Text, nullable=False)
    chat_id = Column(Integer, nullable=True)
    message_id = Column(Integer, nullable=True)
    created_at = Column(Integer, nullable=False)
    updated_at = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "notification_page_session_identifier",
            "page_number",
            name="uq_notifier_message_page_session_number",
        ),
        Index(
            "idx_notifier_message_page_session",
            "notification_page_session_identifier",
        ),
        Index(
            "idx_notifier_message_page_chat_message",
            "chat_id",
            "message_id",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            "<NotifierMessagePage "
            f"session={self.notification_page_session_identifier} "
            f"page_number={self.page_number} "
            f"chat_id={self.chat_id} "
            f"message_id={self.message_id}>"
        )


def ensure_tables() -> None:
    """Створюємо таблиці, якщо ще нема."""
    Base.metadata.create_all(
        bind=engine,
        tables=[
            NotifierState.__table__,
            NotifierMessage.__table__,
            NotifierMessagePage.__table__,
        ],
    )
    log.debug("notifier_state/notifier_messages/notifier_message_pages tables ensured")


__all__ = ["NotifierState", "NotifierMessage", "NotifierMessagePage", "ensure_tables"]
