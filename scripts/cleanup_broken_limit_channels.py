#!/usr/bin/env python
"""
Remove "broken" channel rows caused by "You have joined too many channels/supergroups".
Deletes matching channel_ids from related tables:
  channels, membership, links, channel_links, admin_channels,
  network_channels, subscriptions, owner_conflicts, invite_map, invite_status, invite_owners.

Usage:
    python scripts/cleanup_broken_limit_channels.py [--db path/to/post_watchdog.sqlite3]
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

SQL = """
CREATE TEMP TABLE bad_ids AS
  SELECT channel_id FROM channels
  WHERE title LIKE '%You have joined too many channels/supergroups%';

DELETE FROM membership        WHERE channel_id IN (SELECT channel_id FROM bad_ids);
DELETE FROM links             WHERE channel_id IN (SELECT channel_id FROM bad_ids);
DELETE FROM channel_links     WHERE channel_id IN (SELECT channel_id FROM bad_ids);
DELETE FROM admin_channels    WHERE channel_id IN (SELECT channel_id FROM bad_ids);
DELETE FROM network_channels  WHERE channel_id IN (SELECT channel_id FROM bad_ids);
DELETE FROM subscriptions     WHERE channel_id IN (SELECT channel_id FROM bad_ids);
DELETE FROM owner_conflicts   WHERE channel_id IN (SELECT channel_id FROM bad_ids);
-- invite maps (capture hashes before deleting invite_map)
CREATE TEMP TABLE bad_hashes AS
    SELECT invite_hash FROM invite_map WHERE channel_id IN (SELECT channel_id FROM bad_ids);
DELETE FROM invite_status     WHERE invite_hash IN (SELECT invite_hash FROM bad_hashes);
DELETE FROM invite_owners     WHERE invite_hash IN (SELECT invite_hash FROM bad_hashes);
DELETE FROM invite_map        WHERE invite_hash IN (SELECT invite_hash FROM bad_hashes);
DROP TABLE bad_hashes;

DELETE FROM channels          WHERE channel_id IN (SELECT channel_id FROM bad_ids);

DROP TABLE bad_ids;
"""


def run_cleanup(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        # count before
        cur.execute(
            "SELECT COUNT(*) FROM channels WHERE title LIKE '%You have joined too many channels/supergroups%';"
        )
        before = cur.fetchone()[0]
        cur.executescript(SQL)
        conn.commit()
    finally:
        conn.close()
    return before


def main() -> None:
    load_dotenv()
    load_dotenv(".env.local", override=True)

    parser = argparse.ArgumentParser(description="Cleanup broken channels (too many channels limit).")
    parser.add_argument(
        "--db",
        default=os.getenv("DATABASE_PATH", "post_watchdog.sqlite3"),
        help="Path to SQLite DB (default: post_watchdog.sqlite3 or DATABASE_PATH env).",
    )
    args = parser.parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB file not found: {db_path}")

    removed = run_cleanup(db_path)
    print(f"Done. Removed {removed} broken channel rows (and related records).")


if __name__ == "__main__":
    main()
