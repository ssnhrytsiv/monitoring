import sqlite3
import time
from pathlib import Path

DB_PATH = Path("post_watchdog.sqlite3")

CHAT_ID = 300851736
BATCH_ID = "adminbot:300851736:seed_demo"
OWNER_DISPLAY = "Евгений"
OWNER_USERNAME = ""


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found: {DB_PATH}")

    now = int(time.time())
    urls = [f"https://t.me/+demo{i+1:03d}" for i in range(130)]

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys=OFF;")

    for idx, url in enumerate(urls, start=1):
        con.execute(
            "INSERT INTO link_queue(url, state, tries, added_ts, next_try_ts, last_error, batch_id, origin_chat, origin_msg, owner_display, owner_username) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (url, "queued", 0, now, now, None, BATCH_ID, CHAT_ID, 0, OWNER_DISPLAY, OWNER_USERNAME),
        )

    con.commit()
    con.close()
    print(f"Enqueued {len(urls)} URLs into link_queue for batch {BATCH_ID}")


if __name__ == "__main__":
    main()
