#!/usr/bin/env python
"""
Remove specific invite hashes (and related channel records) from the SQLite DB.
Usage:
    python scripts/cleanup_specific_invites.py --db post_watchdog.sqlite3 --hashes h1 h2 ...
If --hashes не задані, використовується вбудований список з відомими "зламаними" інвайтами.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path
from typing import Iterable, List

from dotenv import load_dotenv

DEFAULT_HASHES = [
    "ZZ-RIEqNL7A4ZjBi",
    "RpafWdE_T40xN2Fi",
    "NLS-Nue3hGI1NTRi",
    "dEu9x_Fjll81NWUy",
    "tp2-m028Y1JiYzcy",
    "6MZaU0P5cBcyZDM6",
]


def cleanup(db_path: Path, hashes: Iterable[str]) -> dict:
    hashes = [h.strip() for h in hashes if h.strip()]
    if not hashes:
        return {"invite_hashes": 0, "channels": 0}

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "CREATE TEMP TABLE bad_hashes(invite_hash TEXT PRIMARY KEY);"
        )
        cur.executemany(
            "INSERT INTO bad_hashes(invite_hash) VALUES (?)",
            [(h,) for h in hashes],
        )
        cur.execute(
            "CREATE TEMP TABLE bad_ids AS "
            "SELECT channel_id FROM invite_cache WHERE invite_hash IN (SELECT invite_hash FROM bad_hashes);"
        )

        # Delete invite-related rows first
        cur.execute(
            "DELETE FROM invite_cache_status WHERE invite_hash IN (SELECT invite_hash FROM bad_hashes);"
        )
        cur.execute(
            "DELETE FROM invite_owners WHERE invite_hash IN (SELECT invite_hash FROM bad_hashes);"
        )
        cur.execute(
            "DELETE FROM invite_cache WHERE invite_hash IN (SELECT invite_hash FROM bad_hashes);"
        )
        invite_deleted = cur.rowcount

        # If there are channel_ids, clean related tables
        cur.execute("SELECT COUNT(*) FROM bad_ids;")
        bad_ids_cnt = cur.fetchone()[0]
        if bad_ids_cnt:
            for table in [
                "membership",
                "links",
                "admin_channels",
                "network_channels",
                "owner_conflicts",
                "channels",
            ]:
                cur.execute(
                    f"DELETE FROM {table} WHERE channel_id IN (SELECT channel_id FROM bad_ids);"
                )
            cur.execute("SELECT COUNT(*) FROM bad_ids;")
        channels_deleted = bad_ids_cnt

        cur.execute("DROP TABLE bad_ids;")
        cur.execute("DROP TABLE bad_hashes;")
        conn.commit()
    finally:
        conn.close()

    return {"invite_hashes": invite_deleted, "channels": channels_deleted}


def main() -> None:
    load_dotenv()
    load_dotenv(".env.local", override=True)
    parser = argparse.ArgumentParser(description="Cleanup specific invite hashes and related channels.")
    parser.add_argument(
        "--db",
        default=os.getenv("DATABASE_PATH", "post_watchdog.sqlite3"),
        help="Path to SQLite DB (default: post_watchdog.sqlite3 or DATABASE_PATH env).",
    )
    parser.add_argument(
        "--hashes",
        nargs="*",
        default=None,
        help="Invite hashes to delete (space-separated). If omitted, uses built-in list.",
    )
    args = parser.parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB file not found: {db_path}")

    hashes: List[str] = args.hashes if args.hashes else DEFAULT_HASHES
    res = cleanup(db_path, hashes)
    print(f"Done. Deleted invite hashes: {res['invite_hashes']}, related channels: {res['channels']}.")


if __name__ == "__main__":
    main()
