import os
import sqlite3

DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")

# Акаунт, який залишаємо як основний
PRIMARY_ACCOUNT = "tg_session"

def main():
    print(f"Using DB: {DB_PATH}")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Знайдемо channel_id з більше ніж одним account
    cur.execute("""
        SELECT channel_id, COUNT(DISTINCT account) AS acc_count
        FROM membership
        GROUP BY channel_id
        HAVING acc_count > 1
        ORDER BY acc_count DESC, channel_id
    """)
    rows = cur.fetchall()
    print(f"Знайдено channel_id з дублікатами акаунтів: {len(rows)}\n")

    total_deleted = 0

    for channel_id, acc_count in rows:
        cur.execute("""
            SELECT account, status, ts
            FROM membership
            WHERE channel_id = ?
            ORDER BY account
        """, (channel_id,))
        records = cur.fetchall()

        accounts = [r[0] for r in records]
        print(f"channel_id={channel_id}, акаунтів={acc_count}, accounts={accounts}")

        # Якщо PRIMARY_ACCOUNT немає серед них – пропускаємо
        if PRIMARY_ACCOUNT not in accounts:
            print(f"  ⚠ PRIMARY_ACCOUNT={PRIMARY_ACCOUNT} відсутній для цього channel_id, пропускаємо")
            print()
            continue

        # Залишаємо тільки PRIMARY_ACCOUNT, решту видаляємо
        for account, status, ts in records:
            if account == PRIMARY_ACCOUNT:
                print(f"  ✓ залишаємо {account} ({status})")
                continue
            print(f"  ✗ видаляємо {account} ({status})")
            cur.execute(
                "DELETE FROM membership WHERE channel_id = ? AND account = ?",
                (channel_id, account),
            )
            total_deleted += 1

        print()

    con.commit()
    con.close()
    print(f"\nГотово. Видалено записів: {total_deleted}")

if __name__ == "__main__":
    main()
