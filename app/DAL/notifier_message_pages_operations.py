from __future__ import annotations

import logging
import time

from sqlalchemy import delete, select, update

from app.db.session import SessionLocal
from app.notificator_bot.models import NotifierMessagePage

log = logging.getLogger("dal.notifier_message_pages")


def _current_unix_timestamp() -> int:
    return int(time.time())


def create_notification_page_session_records(
    notification_page_session_identifier: str,
    notification_page_texts: list[str],
) -> None:
    database_session = SessionLocal()
    try:
        current_unix_timestamp = _current_unix_timestamp()
        for page_number, page_text in enumerate(notification_page_texts):
            notifier_message_page_row = NotifierMessagePage(
                notification_page_session_identifier=str(notification_page_session_identifier),
                page_number=int(page_number),
                page_text=str(page_text),
                chat_id=None,
                message_id=None,
                created_at=current_unix_timestamp,
                updated_at=current_unix_timestamp,
            )
            database_session.add(notifier_message_page_row)
        database_session.commit()
    except Exception:
        database_session.rollback()
        log.exception(
            "create_notification_page_session_records failed: notification_page_session_identifier=%s",
            notification_page_session_identifier,
        )
        raise
    finally:
        database_session.close()


def bind_notification_page_session_to_message(
    notification_page_session_identifier: str,
    chat_id: int,
    message_id: int,
) -> None:
    database_session = SessionLocal()
    try:
        current_unix_timestamp = _current_unix_timestamp()
        database_session.execute(
            update(NotifierMessagePage)
            .where(
                NotifierMessagePage.notification_page_session_identifier
                == str(notification_page_session_identifier)
            )
            .values(
                chat_id=int(chat_id),
                message_id=int(message_id),
                updated_at=current_unix_timestamp,
            )
        )
        database_session.commit()
    except Exception:
        database_session.rollback()
        log.exception(
            "bind_notification_page_session_to_message failed: "
            "notification_page_session_identifier=%s chat_id=%s message_id=%s",
            notification_page_session_identifier,
            chat_id,
            message_id,
        )
        raise
    finally:
        database_session.close()


def delete_notification_page_session_records(
    notification_page_session_identifier: str,
) -> int:
    database_session = SessionLocal()
    try:
        delete_result = database_session.execute(
            delete(NotifierMessagePage).where(
                NotifierMessagePage.notification_page_session_identifier
                == str(notification_page_session_identifier)
            )
        )
        database_session.commit()
        return int(delete_result.rowcount or 0)
    except Exception:
        database_session.rollback()
        log.exception(
            "delete_notification_page_session_records failed: notification_page_session_identifier=%s",
            notification_page_session_identifier,
        )
        raise
    finally:
        database_session.close()


def delete_notification_page_records_for_message(chat_id: int, message_id: int) -> int:
    database_session = SessionLocal()
    try:
        delete_result = database_session.execute(
            delete(NotifierMessagePage).where(
                NotifierMessagePage.chat_id == int(chat_id),
                NotifierMessagePage.message_id == int(message_id),
            )
        )
        database_session.commit()
        return int(delete_result.rowcount or 0)
    except Exception:
        database_session.rollback()
        log.exception(
            "delete_notification_page_records_for_message failed: chat_id=%s message_id=%s",
            chat_id,
            message_id,
        )
        raise
    finally:
        database_session.close()


def count_notification_pages_for_message_session(
    notification_page_session_identifier: str,
    chat_id: int,
    message_id: int,
) -> int:
    database_session = SessionLocal()
    try:
        notification_page_rows = database_session.execute(
            select(NotifierMessagePage.page_number).where(
                NotifierMessagePage.notification_page_session_identifier
                == str(notification_page_session_identifier),
                NotifierMessagePage.chat_id == int(chat_id),
                NotifierMessagePage.message_id == int(message_id),
            )
        ).all()
        return len(notification_page_rows)
    finally:
        database_session.close()


def count_notification_pages_for_session(
    notification_page_session_identifier: str,
) -> int:
    database_session = SessionLocal()
    try:
        notification_page_rows = database_session.execute(
            select(NotifierMessagePage.page_number).where(
                NotifierMessagePage.notification_page_session_identifier
                == str(notification_page_session_identifier),
            )
        ).all()
        return len(notification_page_rows)
    finally:
        database_session.close()


def get_notification_page_text_for_message(
    notification_page_session_identifier: str,
    chat_id: int,
    message_id: int,
    requested_page_number: int,
) -> str | None:
    database_session = SessionLocal()
    try:
        notification_page_text_value = database_session.execute(
            select(NotifierMessagePage.page_text).where(
                NotifierMessagePage.notification_page_session_identifier
                == str(notification_page_session_identifier),
                NotifierMessagePage.chat_id == int(chat_id),
                NotifierMessagePage.message_id == int(message_id),
                NotifierMessagePage.page_number == int(requested_page_number),
            )
        ).scalar_one_or_none()
        if notification_page_text_value is None:
            return None
        return str(notification_page_text_value)
    finally:
        database_session.close()


def get_notification_page_text_for_session(
    notification_page_session_identifier: str,
    requested_page_number: int,
) -> str | None:
    database_session = SessionLocal()
    try:
        notification_page_text_value = database_session.execute(
            select(NotifierMessagePage.page_text).where(
                NotifierMessagePage.notification_page_session_identifier
                == str(notification_page_session_identifier),
                NotifierMessagePage.page_number == int(requested_page_number),
            )
        ).scalar_one_or_none()
        if notification_page_text_value is None:
            return None
        return str(notification_page_text_value)
    finally:
        database_session.close()
