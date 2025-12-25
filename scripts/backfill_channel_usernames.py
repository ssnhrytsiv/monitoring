#!/usr/bin/env python
"""
Backfill missing channel usernames into `channels.username` from existing links.

Reads .env / .env.local for DB path if needed, defaults to post_watchdog.sqlite3.

Usage:
    python scripts/backfill_channel_usernames.py [--db path/to/sqlite]
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
from pathlib import Path

from dotenv import load_dotenv


def extract_username(raw_url: str) -> str | None:
    """Return username if raw_url is a public t.me/@username link."""
    if not raw_url:
        return None
    url = raw_url.strip()
    # Skip invites
    if "+/" in url or url.lstrip().startswith(("https://t.me/+","t.me/+","+")):
        return None
    if url.startswith("@"):
        cand = url.lstrip("@")
    elif "t.me/" in url:
        cand = url.split("t.me/", 1)[1]
    else:
        return None
    cand = cand.split("/", 1)[0]
    cand = re.sub(r"[^A-Za-z0-9_]", "", cand)
    return cand or None


def backfill(db_path: Path) -> tuple[int, int]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    updated = 0
    skipped = 0
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT l.channel_id, l.raw_url
            FROM links l
            JOIN channels c ON c.channel_id = l.channel_id
            WHERE (c.username IS NULL OR c.username = '')
              AND l.raw_url IS NOT NULL
            """
        )
        rows = cur.fetchall()
        for row in rows:
            uname = extract_username(row["raw_url"])
            if not uname:
                skipped += 1
                continue
            cur.execute(
                """
                UPDATE channels
                SET username = COALESCE(?, username)
                WHERE channel_id = ? AND (username IS NULL OR username = '')
                """,
                (uname, row["channel_id"]),
            )
            if cur.rowcount:
                updated += 1
        conn.commit()
    finally:
        conn.close()
    return updated, skipped


def main() -> None:
    load_dotenv()
    load_dotenv(".env.local", override=True)

    parser = argparse.ArgumentParser(description="Backfill channels.username from links")
    parser.add_argument(
        "--db",
        default=os.getenv("DATABASE_PATH", "post_watchdog.sqlite3"),
        help="Path to SQLite DB (default: post_watchdog.sqlite3 or DATABASE_PATH env).",
    )
    args = parser.parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB file not found: {db_path}")

    updated, skipped = backfill(db_path)
    print(f"Done. Updated {updated} channel usernames. Skipped {skipped} links.")


if __name__ == "__main__":
    main()
