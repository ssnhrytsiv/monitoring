import os
import sqlite3

DB_PATH = "/Users/nazarhrytsiv/Downloads/tg_monitor_package_v13_full/post_watchdog.sqlite3"

def main():
    print(f"Using DB: {DB_PATH}")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Знайти channel_id, де є більше ніж один account
    cur.execute("""
        SELECT channel_id, COUNT(DISTINCT account) AS acc_count
        FROM membership
        GROUP BY channel_id
        HAVING acc_count > 1
        ORDER BY acc_count DESC, channel_id
    """)
    rows = cur.fetchall()
    print(f"Знайдено channel_id з дублікатами акаунтів: {len(rows)}\n")

    for channel_id, acc_count in rows:
        print(f"channel_id={channel_id}, акаунтів={acc_count}")
        cur.execute("""
            SELECT account, status, ts
            FROM membership
            WHERE channel_id = ?
            ORDER BY account
        """, (channel_id,))
        for account, status, ts in cur.fetchall():
            print(f"  account={account:20s} status={status:10s} ts={ts}")
        print()

    con.close()

if __name__ == "__main__":
    main()