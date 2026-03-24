import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.DAL import watch_processing_operations as watch_proc_db
from app.admin_bot.db.models import WatchPost
from app.admin_bot.db.session import Base


def _build_test_session_factory():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def test_mark_views_access_lost_switches_watch_to_terminal_error_status(monkeypatch):
    session_factory = _build_test_session_factory()
    monkeypatch.setattr(watch_proc_db, "SessionLocal", session_factory)
    monkeypatch.setattr(watch_proc_db, "_now_str", lambda: "2026-03-22 23:11:00")

    with session_factory() as database_session:
        database_session.add(
            WatchPost(
                id=8116,
                channel_id=1801542020,
                status="matched",
                matched_message_id=31428,
                matched_session="tg_session_11",
                coverage_check_at="2026-03-22 23:10:00",
                updated_at="2026-03-22 23:00:00",
            )
        )
        database_session.commit()

    assert watch_proc_db.mark_views_access_lost(8116) is True

    with session_factory() as database_session:
        watch_row = (
            database_session.query(WatchPost)
            .filter(WatchPost.id == 8116)
            .one()
        )

    assert watch_row.status == "views_access_lost"
    assert watch_row.final_views is None
    assert watch_row.updated_at == "2026-03-22 23:11:00"


def test_mark_done_deleted_can_override_views_access_lost(monkeypatch):
    session_factory = _build_test_session_factory()
    monkeypatch.setattr(watch_proc_db, "SessionLocal", session_factory)
    monkeypatch.setattr(watch_proc_db, "_now_str", lambda: "2026-03-22 23:15:00")

    with session_factory() as database_session:
        database_session.add(
            WatchPost(
                id=8117,
                channel_id=1801542020,
                status="views_access_lost",
                matched_message_id=31429,
                matched_session="tg_session_12",
                coverage_check_at="2026-03-22 23:10:00",
                updated_at="2026-03-22 23:00:00",
            )
        )
        database_session.commit()

    previous_status = watch_proc_db.mark_done_deleted(8117)

    with session_factory() as database_session:
        watch_row = (
            database_session.query(WatchPost)
            .filter(WatchPost.id == 8117)
            .one()
        )

    assert previous_status == "views_access_lost"
    assert watch_row.status == "deleted"
    assert watch_row.deleted_at == "2026-03-22 23:15:00"
    assert watch_row.updated_at == "2026-03-22 23:15:00"


def test_reschedule_coverage_check_keeps_watch_matched_and_moves_retry_time(monkeypatch):
    session_factory = _build_test_session_factory()
    monkeypatch.setattr(watch_proc_db, "SessionLocal", session_factory)
    monkeypatch.setattr(watch_proc_db, "_now_str", lambda: "2026-03-23 00:10:00")

    with session_factory() as database_session:
        database_session.add(
            WatchPost(
                id=8118,
                channel_id=1801542020,
                status="matched",
                matched_message_id=31430,
                matched_session="tg_session_11",
                coverage_check_at="2026-03-23 00:08:00",
                updated_at="2026-03-23 00:05:00",
            )
        )
        database_session.commit()

    assert watch_proc_db.reschedule_coverage_check(8118, "2026-03-23 00:14:00") is True

    with session_factory() as database_session:
        watch_row = (
            database_session.query(WatchPost)
            .filter(WatchPost.id == 8118)
            .one()
        )

    assert watch_row.status == "matched"
    assert watch_row.coverage_check_at == "2026-03-23 00:14:00"
    assert watch_row.updated_at == "2026-03-23 00:10:00"
