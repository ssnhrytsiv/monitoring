from __future__ import annotations

import os
import tempfile

from app.notificator_bot.db import posts_watch_result_db as db


def _setup_db():
    # Використовуємо окремий тимчасовий файл БД для тестів
    if not os.environ.get("POSTS_WATCH_RESULT_DB_PATH"):
        fd, path = tempfile.mkstemp(prefix="watch_candidates_test", suffix=".sqlite3")
        os.close(fd)
        os.environ["POSTS_WATCH_RESULT_DB_PATH"] = path
    db.init()
    conn = db.raw_connection()
    cur = conn.cursor()
    for table in ["watch_events", "watch_candidates", "watch_posts", "watch_groups"]:
        cur.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()


def _get_watch_status(wid: int):
    conn = db.raw_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT status, matched_message_id FROM watch_posts WHERE id=?",
        (wid,),
    )
    row = cur.fetchone()
    conn.close()
    return row if row else (None, None)


def _get_candidate_status(cid: int):
    cand = db.get_watch_candidate(cid)
    return cand.get("status") if cand else None


def _expire_candidate(cid: int):
    conn = db.raw_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE watch_candidates SET expires_at='2000-01-01 00:00:00' WHERE id=?",
        (cid,),
    )
    conn.commit()
    conn.close()


def _count_events(wid: int, ev_type: str) -> int:
    conn = db.raw_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM watch_events WHERE watch_id=? AND event_type=?",
        (wid, ev_type),
    )
    row = cur.fetchone()
    conn.close()
    return int(row[0] or 0) if row else 0


def test_candidate_accept_matches_multiple_with_same_text_hash():
    _setup_db()
    # Створюємо два вотчі
    wid1 = db.create_watch(channel_id=111)
    wid2 = db.create_watch(channel_id=222)

    text = "Test post content"
    # Додаємо два кандидати з однаковим текстом/хешем
    cid1 = db.insert_watch_candidate(
        watch_id=wid1,
        channel_id=111,
        message_id=5,
        similarity=0.85,
        message_text=text,
        ttl_days=1.0,
    )
    cid2 = db.insert_watch_candidate(
        watch_id=wid2,
        channel_id=222,
        message_id=6,
        similarity=0.86,
        message_text=text,
        ttl_days=1.0,
    )

    # Приймаємо перший — має заметчити обидва завдяки однаковому text_hash
    ok = db.accept_watch_candidate(cid1)
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
    wid = db.create_watch(channel_id=333)
    cid = db.insert_watch_candidate(
        watch_id=wid,
        channel_id=333,
        message_id=10,
        similarity=0.75,
        message_text="Hello world",
        ttl_days=1.0,
    )
    items = db.list_watch_candidates(wid)
    assert len(items) == 1
    item = items[0]
    assert item["id"] == cid
    assert item["status"] == "pending"
    assert item["message_id"] == 10
    assert item["channel_id"] == 333
    assert item["similarity"] == 0.75
    assert item["text_hash"]  # має бути заповнений

    cand = db.get_watch_candidate(cid)
    assert cand is not None
    assert cand["id"] == cid
    assert cand["watch_id"] == wid
    assert cand["status"] == "pending"


def test_reject_and_not_pending_accept():
    _setup_db()
    wid = db.create_watch(channel_id=444)
    cid = db.insert_watch_candidate(
        watch_id=wid,
        channel_id=444,
        message_id=11,
        similarity=0.71,
        message_text="Reject me",
        ttl_days=1.0,
    )
    # Відхиляємо
    db.set_watch_candidate_status(cid, "rejected")
    assert _get_candidate_status(cid) == "rejected"
    # Прийняття повинно повернути False, статус не змінюється
    ok = db.accept_watch_candidate(cid)
    assert ok is False
    assert _get_candidate_status(cid) == "rejected"


def test_list_candidates_filters_expired():
    _setup_db()
    wid = db.create_watch(channel_id=555)
    cid_active = db.insert_watch_candidate(
        watch_id=wid,
        channel_id=555,
        message_id=12,
        similarity=0.8,
        message_text="Active",
        ttl_days=1.0,
    )
    cid_expired = db.insert_watch_candidate(
        watch_id=wid,
        channel_id=555,
        message_id=13,
        similarity=0.8,
        message_text="Expired",
        ttl_days=1.0,
    )
    _expire_candidate(cid_expired)

    cands = db.list_watch_candidates(wid)
    ids = {c["id"] for c in cands}
    assert cid_active in ids
    assert cid_expired not in ids
