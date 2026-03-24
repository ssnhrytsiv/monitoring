import asyncio
import os
import sys
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.DAL import watch_posts_operations as watch_posts_db
from app.DAL import watch_processing_operations as watch_proc_db
from app.admin_bot.db.models import WatchPost
from app.admin_bot.db.session import Base
from app.watch_bot.services import edit_watch_service


def _build_test_session_factory():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def test_reply_watch_flag_is_preserved_in_watch_info_and_pending_rows(monkeypatch):
    session_factory = _build_test_session_factory()
    monkeypatch.setattr(watch_posts_db, "WatchSessionLocal", session_factory)
    monkeypatch.setattr(watch_proc_db, "SessionLocal", session_factory)
    monkeypatch.setattr(watch_posts_db, "_ACTIVE_WATCH_INDEX_CHECKED", True)

    watch_id = watch_posts_db.create_watch(channel_id=1801542020, is_reply=True)

    watch_info = watch_posts_db.get_watch_info(watch_id)
    pending_rows = watch_proc_db.get_pending_by_channel(1801542020)

    assert watch_info["is_reply"] is True
    assert pending_rows[0]["id"] == watch_id
    assert pending_rows[0]["is_reply"] is True
    assert watch_posts_db.get_watch_is_reply(watch_id) is True


def test_manual_match_for_reply_watch_skips_coverage_capture(monkeypatch):
    captured = {}

    monkeypatch.setattr(edit_watch_service, "get_watch_channel_id", lambda wid: 1801542020)
    monkeypatch.setattr(edit_watch_service, "get_watch_is_reply", lambda wid: True)
    monkeypatch.setattr(edit_watch_service, "get_watch_source_url", lambda wid: "https://t.me/test_channel")
    monkeypatch.setattr(edit_watch_service, "SHEETS_OK", False)

    def _manual_mark_matched(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(edit_watch_service, "manual_mark_matched", _manual_mark_matched)

    result = asyncio.run(
        edit_watch_service.manual_match_watch_from_message(
            8116,
            SimpleNamespace(forward_from_message_id=31428, message_id=99),
        )
    )

    assert result is True
    assert captured["watch_id"] == 8116
    assert captured["coverage_check_at"] is None
