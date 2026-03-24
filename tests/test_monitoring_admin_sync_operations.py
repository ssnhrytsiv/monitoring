import os
import sqlite3
import sys
from pathlib import Path


sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

from DAL.monitoring_admin_sync_operations import sync_monitoring_admin_tg_id


def _prepare_monitoring_db(database_path: Path) -> None:
    connection = sqlite3.connect(str(database_path))
    try:
        connection.execute(
            """
            CREATE TABLE admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id BIGINT,
                username VARCHAR,
                display VARCHAR,
                is_new INTEGER DEFAULT 0
            )
            """
        )
        connection.execute("CREATE UNIQUE INDEX ix_admins_tg_id ON admins (tg_id)")
        connection.commit()
    finally:
        connection.close()


def test_sync_monitoring_admin_tg_id_creates_admin_on_no_match(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "post_watchdog.sqlite3"
    _prepare_monitoring_db(database_path)
    monkeypatch.setenv("MONITORING_DB_PATH", str(database_path))

    connection = sqlite3.connect(str(database_path))
    try:
        connection.execute(
            "INSERT INTO admins (tg_id, username, display, is_new) VALUES (?, ?, ?, ?)",
            (987654321, "other_admin", "Другой Админ", 0),
        )
        connection.commit()
    finally:
        connection.close()

    result = sync_monitoring_admin_tg_id(
        tg_id=123456789,
        candidate_names=["Банши Ашкер"],
        preferred_username="banshi",
        preferred_display="Банши Ашкер",
    )

    assert result["status"] == "created"
    assert result["reason"] == "no_match"

    connection = sqlite3.connect(str(database_path))
    try:
        row = connection.execute(
            "SELECT tg_id, username, display, is_new FROM admins WHERE tg_id = ?",
            (123456789,),
        ).fetchone()
    finally:
        connection.close()

    assert row == (123456789, "banshi", "Банши Ашкер", 1)


def test_sync_monitoring_admin_tg_id_creates_admin_on_conflicting_match(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "post_watchdog.sqlite3"
    _prepare_monitoring_db(database_path)
    monkeypatch.setenv("MONITORING_DB_PATH", str(database_path))

    connection = sqlite3.connect(str(database_path))
    try:
        connection.execute(
            "INSERT INTO admins (tg_id, username, display, is_new) VALUES (?, ?, ?, ?)",
            (111, "existing_admin", "Игорь Футбол", 0),
        )
        connection.commit()
    finally:
        connection.close()

    result = sync_monitoring_admin_tg_id(
        tg_id=222,
        candidate_names=["Игорь Футбол"],
        preferred_username="new_igor",
        preferred_display="Игорь Футбол",
    )

    assert result["status"] == "created"
    assert result["reason"] == "tg_id_conflict"

    connection = sqlite3.connect(str(database_path))
    try:
        rows = connection.execute(
            "SELECT tg_id, username, display, is_new FROM admins ORDER BY id"
        ).fetchall()
    finally:
        connection.close()

    assert rows == [
        (111, "existing_admin", "Игорь Футбол", 0),
        (222, "new_igor", "Игорь Футбол", 1),
    ]
