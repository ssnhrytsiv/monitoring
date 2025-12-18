import os
import sqlite3
from typing import List

# Шлях до БД: з env DB_PATH або за замовчуванням локальний файл
DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")

# Необов'язково: через env MEMBERSHIP_STATUS_IN можна вказати статуси через кому
# приклад: MEMBERSHIP_STATUS_IN="joined,already,requested"
def _parse_status_filter() -> List[str]:
    raw = os.getenv("MEMBERSHIP_STATUS_IN", "")
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def main():
    print(f"Using DB: {DB_PATH}")
    statuses = _parse_status_filter()
    if statuses:
        print(f"Filtering by statuses: {statuses}")

    try:
        con = sqlite3.connect(DB_PATH)
    except Exception as e:
        print(f"❌ Cannot open DB: {e}")
        return

    cur = con.cursor()
    try:
        placeholders = ",".join("?" for _ in statuses) if statuses else ""
        where_clause = f"WHERE status IN ({placeholders})" if statuses else ""
        sql = f"""
            SELECT account, COUNT(*) AS cnt
            FROM membership
            {where_clause}
            GROUP BY account
            ORDER BY cnt DESC, account
        """
        cur.execute(sql, statuses)
        rows = cur.fetchall()
    except Exception as e:
        print(f"❌ Query failed: {e}")
        con.close()
        return

    if not rows:
        print("No records found.")
        con.close()
        return

    print("\nКількість записів у membership по кожній сесії:")
    for account, cnt in rows:
        print(f"  {account}: {cnt}")

    con.close()


if __name__ == "__main__":
    main()
