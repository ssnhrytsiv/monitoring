#!/usr/bin/env python3
"""
Синхронізація url_cache з таблицею links:
- видаляє записи url_cache зі статусами joined/already, якщо їхніх URL немає в links;
"""

import os
import sqlite3

DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")


def main():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA busy_timeout=3000;")

    # Видалити joined/already, яких немає в links
    delete_sql = """
        DELETE FROM url_cache
        WHERE status IN ('joined','already')
          AND url NOT IN (SELECT raw_url FROM links)
    """
    cur = con.execute(delete_sql)
    deleted = cur.rowcount or 0

    con.commit()
    print(f"Done. url_cache deleted={deleted}, inserted=0, db={DB_PATH}")


if __name__ == "__main__":
    main()
