from __future__ import annotations

import os
import tempfile
from sqlalchemy import select

from app.admin_bot.db.session import Base, engine, SessionLocal
from app.admin_bot.db import models as m
from app.notificator_bot.db import posts_watch_result_models as pwm
from app.DAL import watch_posts_operations as watch_posts_db
from app.DAL import watch_processing_operations as watch_proc_db
from app.DAL import watch_candidates_operations as watch_cand_db
from app.DAL import watch_events_operations as watch_events_db


def _ensure_temp_db():
    if not os.environ.get("SQLALCHEMY_DATABASE_URL"):
        fd, path = tempfile.mkstemp(prefix="watch_candidates_test", suffix=".sqlite3")
        os.close(fd)
        os.environ["SQLALCHEMY_DATABASE_URL"] = f"sqlite:///{path}"


def _setup_db():
    _ensure_temp_db()
    # Перестворюємо всі таблиці для чистого старту
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    pwm.init_schema()


def _get_watch_status(wid: int):
    with SessionLocal() as db:
        row = db.execute(
            select(m.WatchPost.status, m.WatchPost.matched_message_id).where(m.WatchPost.id == wid).limit(1)
        ).first()
        if not row:
            return None, None
        return row[0], row[1]


def _get_candidate_status(cid: int):
    cand = watch_cand_db.get_watch_candidate(cid)
    return cand.get("status") if cand else None


def _expire_candidate(cid: int):
    with SessionLocal() as db:
        db.execute(
            m.WatchCandidate.__table__.update().where(m.WatchCandidate.id == cid).values(expires_at="2000-01-01 00:00:00")
        )
        db.commit()


def _count_events(wid: int, ev_type: str) -> int:
    with SessionLocal() as db:
        row = db.execute(
            pwm.select(m.WatchEvent.id).where(m.WatchEvent.watch_id == wid, m.WatchEvent.event_type == ev_type)
        ).all()
        return len(row)


def test_candidate_accept_matches_multiple_with_same_text_hash():
    _setup_db()
    # Створюємо два вотчі
    wid1 = watch_posts_db.create_watch(channel_id=111)
    wid2 = watch_posts_db.create_watch(channel_id=222)

    text = "Test post content"
    # Додаємо два кандидати з однаковим текстом/хешем
    cid1 = watch_proc_db.insert_watch_candidate(
        watch_id=wid1,
        channel_id=111,
        message_id=5,
        similarity=0.85,
        message_text=text,
        ttl_days=1.0,
    )
    cid2 = watch_proc_db.insert_watch_candidate(
        watch_id=wid2,
        channel_id=222,
        message_id=6,
        similarity=0.86,
        message_text=text,
        ttl_days=1.0,
    )

    # Приймаємо перший — має заметчити обидва завдяки однаковому text_hash
    ok = watch_cand_db.accept_watch_candidate(cid1)
    assert ok is True

    # Обидва кандидати мають бути accepted
    assert _get_candidate_status(cid1) == "accepted"
    assert _get_candidate_status(cid2) == "accepted"

    # Обидва вотчі стали matched з відповідними message_id
    st1, mid1 = _get_watch_status(wid1)
    st2, mid2 = _get_watch_status(wid2)
    assert st1 == "matched" and mid1 == 5
    assert st2 == "matched" and mid2 == 6

    # Подія matched записана для обох
    assert _count_events(wid1, "matched") == 1
    assert _count_events(wid2, "matched") == 1


def test_list_and_get_candidate_fields():
    _setup_db()
    wid = watch_posts_db.create_watch(channel_id=333)
    cid = watch_proc_db.insert_watch_candidate(
        watch_id=wid,
        channel_id=333,
        message_id=10,
        similarity=0.75,
        message_text="Hello world",
        ttl_days=1.0,
    )
    items = watch_cand_db.list_watch_candidates(wid)
    assert len(items) == 1
    item = items[0]
    assert item["id"] == cid
    assert item["status"] == "pending"
    assert item["message_id"] == 10
    assert item["channel_id"] == 333
    assert item["similarity"] == 0.75
    assert item["text_hash"]  # має бути заповнений

    cand = watch_cand_db.get_watch_candidate(cid)
    assert cand is not None
    assert cand["id"] == cid
    assert cand["watch_id"] == wid
    assert cand["status"] == "pending"


def test_reject_and_not_pending_accept():
    _setup_db()
    wid = watch_posts_db.create_watch(channel_id=444)
    cid = watch_proc_db.insert_watch_candidate(
        watch_id=wid,
        channel_id=444,
        message_id=11,
        similarity=0.71,
        message_text="Reject me",
        ttl_days=1.0,
    )
    # Відхиляємо
    watch_cand_db.set_watch_candidate_status(cid, "rejected")
    assert _get_candidate_status(cid) == "rejected"
    # Прийняття повинно повернути False, статус не змінюється
    ok = watch_cand_db.accept_watch_candidate(cid)
    assert ok is False
    assert _get_candidate_status(cid) == "rejected"


def test_list_candidates_filters_expired():
    _setup_db()
    wid = watch_posts_db.create_watch(channel_id=555)
    cid_active = watch_proc_db.insert_watch_candidate(
        watch_id=wid,
        channel_id=555,
        message_id=12,
        similarity=0.8,
        message_text="Active",
        ttl_days=1.0,
    )
    cid_expired = watch_proc_db.insert_watch_candidate(
        watch_id=wid,
        channel_id=555,
        message_id=13,
        similarity=0.8,
        message_text="Expired",
        ttl_days=1.0,
    )
    _expire_candidate(cid_expired)

    cands = watch_cand_db.list_watch_candidates(wid)
    ids = {c["id"] for c in cands}
    assert cid_active in ids
    assert cid_expired not in ids
