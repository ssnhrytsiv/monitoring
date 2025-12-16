import sqlite3
import json

DB_PATH = "/Users/nazarhrytsiv/Downloads/tg_monitor_package_v13_full/post_watchdog.sqlite3"
OUT_PATH = "membership_duplicates.json"

def main():
    print(f"Using DB: {DB_PATH}")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("""
        SELECT channel_id, COUNT(DISTINCT account) AS acc_count
        FROM membership
        GROUP BY channel_id
        HAVING acc_count > 1
        ORDER BY acc_count DESC, channel_id
    """)
    rows = cur.fetchall()
    print(f"Знайдено channel_id з дублікатами акаунтів: {len(rows)}\n")

    dup_map = {}

    for channel_id, acc_count in rows:
        cur.execute("""
            SELECT account, status, ts
            FROM membership
            WHERE channel_id = ?
            ORDER BY account
        """, (channel_id,))
        recs = cur.fetchall()
        dup_map[str(channel_id)] = [
            {"account": acc, "status": status, "ts": ts}
            for (acc, status, ts) in recs
        ]

    con.close()

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(dup_map, f, ensure_ascii=False, indent=2)

    print(f"\nЗбережено {len(dup_map)} channel_id у {OUT_PATH}")

if __name__ == "__main__":
    main()