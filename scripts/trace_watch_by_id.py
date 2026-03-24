from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show watch row and latest trace events by watch_id")
    parser.add_argument("watch_id", type=int, help="watch_posts.id")
    parser.add_argument(
        "--db-path",
        default=str(Path(__file__).resolve().parents[1] / "post_watchdog.sqlite3"),
        help="Path to post_watchdog.sqlite3",
    )
    parser.add_argument("--limit", type=int, default=20, help="Max events to show")
    return parser.parse_args()


def _print_watch_row(connection: sqlite3.Connection, watch_id: int) -> None:
    row = connection.execute(
        """
        SELECT id, status, channel_id, group_id, project, admin_id, network_id,
               time_window_start, time_window_end, created_via, created_at, updated_at
        FROM watch_posts
        WHERE id = ?
        LIMIT 1
        """,
        (watch_id,),
    ).fetchone()
    if not row:
        print(f"watch_id={watch_id} not found")
        return
    labels = [
        "id",
        "status",
        "channel_id",
        "group_id",
        "project",
        "admin_id",
        "network_id",
        "time_window_start",
        "time_window_end",
        "created_via",
        "created_at",
        "updated_at",
    ]
    print("watch:")
    for index, label in enumerate(labels):
        print(f"  {label}: {row[index]}")


def _print_events(connection: sqlite3.Connection, watch_id: int, limit: int) -> None:
    rows = connection.execute(
        """
        SELECT id, event_type, payload_json, created_at
        FROM watch_events
        WHERE watch_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (watch_id, int(max(limit, 1))),
    ).fetchall()
    print("")
    print(f"events (last {len(rows)}):")
    for row in rows:
        event_id, event_type, payload_json, created_at = row
        payload_pretty = payload_json
        try:
            payload_pretty = json.dumps(json.loads(payload_json or "{}"), ensure_ascii=False)
        except Exception:
            pass
        print(f"  [{event_id}] {created_at} {event_type} {payload_pretty}")


def main() -> int:
    args = _parse_args()
    db_path = Path(args.db_path).expanduser().resolve()
    if not db_path.exists():
        print(f"db not found: {db_path}")
        return 1

    connection = sqlite3.connect(str(db_path))
    try:
        _print_watch_row(connection, int(args.watch_id))
        _print_events(connection, int(args.watch_id), int(args.limit))
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
