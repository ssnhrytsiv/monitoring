import sqlite3
import time
from pathlib import Path

DB_PATH = Path("post_watchdog.sqlite3")

ADMIN_DISPLAY = "Евгений"
ADMIN_USERNAME = None
TG_ID = 300851736  # за потреби заміни на актуальний


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found: {DB_PATH}")

    now = int(time.time())
    statuses = [
        "joined",
        "already",
        "requested",
        "invalid",
        "blocked",
        "too_many",
        "error",
    ]

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys=OFF;")

    # Адмін
    cur = con.execute("SELECT id FROM admins WHERE display=? LIMIT 1", (ADMIN_DISPLAY,))
    row = cur.fetchone()
    if row:
        admin_id = row[0]
    else:
        con.execute(
            "INSERT INTO admins(tg_id, username, display) VALUES(?,?,?)",
            (TG_ID, ADMIN_USERNAME or "", ADMIN_DISPLAY),
        )
        admin_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

    base_channel = 900000000
    records = []
    for i in range(130):
        cid = base_channel + i
        title = f"Demo Channel {i+1}"
        url = f"https://t.me/+demo{i+1:03d}"
        status = statuses[i % len(statuses)]
        records.append((cid, title, url, status))

    for idx, (cid, title, url, status) in enumerate(records):
        con.execute(
            "INSERT OR IGNORE INTO channels(channel_id, username, title, owner_admin_id, owner_username, last_status, created_at, updated_at) "
            "VALUES(?,?,?,?,?, ?, datetime('now'),datetime('now'))",
            (cid, f"demo{idx+1}", title, admin_id, ADMIN_USERNAME or "", status),
        )
        con.execute(
            "INSERT OR REPLACE INTO membership(channel_id, account, status, ts) VALUES(?,?,?,?)",
            (cid, "tg_session.session", status, now),
        )
        con.execute(
            "INSERT OR REPLACE INTO url_cache(url, status, ts) VALUES(?,?,?)",
            (url, status, now),
        )
        con.execute(
            "INSERT OR IGNORE INTO links(channel_id, raw_url, kind, batch_msg_id, owner_admin_id, owner_username, added_at) "
            "VALUES(?,?,?,?,?,?,datetime('now'))",
            (cid, url, "seed_demo", 0, admin_id, ADMIN_USERNAME or "",),
        )

    con.commit()
    con.close()
    print(f"Seeded {len(records)} links for admin '{ADMIN_DISPLAY}' (id={admin_id})")


if __name__ == "__main__":
    main()
