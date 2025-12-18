import os
import json
import sqlite3
import asyncio

from telethon import TelegramClient
from telethon.errors import RPCError

# Корінь проєкту, де лежать .session файли
BASE_DIR = os.getenv("BASE_DIR", ".")

DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "post_watchdog.sqlite3"))
DUP_JSON_PATH = os.getenv("DUP_JSON_PATH", os.path.join(BASE_DIR, "membership_duplicates.json"))

# Primary-акаунт, який НЕ чіпаємо
PRIMARY_ACCOUNT = "tg_session"

# API ключі Telegram
API_ID = int(os.getenv("TG_API_ID", "123456"))        # заміни або вистав через env
API_HASH = os.getenv("TG_API_HASH", "your_api_hash")  # заміни або вистав через env

# Мапа account (з таблиці membership) -> ім'я session-файлу (БЕЗ .session)
# Підлаштовуй під реальні значення account з SELECT DISTINCT account FROM membership
ACCOUNT_TO_SESSION = {
    "tg_session": "tg_session",
    "tg_session_2": "tg_session_2",
    "tg_session_3": "tg_session_3",
    "tg_session_4": "tg_session_4",
    "tg_session_5": "tg_session_5",

    # Якщо в membership є такі значення — мапимо їх на існуючі файли:
    "tg_session_2.session": "tg_session_2",
    "tg_session_3.session": "tg_session_3",
    "tg_session_4.session": "tg_session_4",
    "tg_session_5.session": "tg_session_5",
}

# Затримка між leave-запитами в секундах (щоб не ловити flood)
LEAVE_DELAY_SEC = 1.0


def load_duplicates():
    with open(DUP_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    # перетворимо ключі на int
    result = {}
    for cid_str, entries in data.items():
        try:
            cid = int(cid_str)
        except ValueError:
            continue
        result[cid] = entries
    return result


def connect_db():
    con = sqlite3.connect(DB_PATH)
    return con, con.cursor()


async def leave_for_account(account: str, channel_ids: list[int]):
    """
    Для конкретного account:
    - підʼєднатись до відповідної Telegram-сесії (на основі ACCOUNT_TO_SESSION)
    - вийти з усіх переданих channel_ids
    """
    session_name = ACCOUNT_TO_SESSION.get(account, account)
    session_path = os.path.join(BASE_DIR, f"{session_name}.session")

    print(
        f"\n[account={account}] використовуємо session_name={session_name}, "
        f"session_path={session_path}, каналів для виходу: {len(channel_ids)}"
    )

    client = TelegramClient(session_path, API_ID, API_HASH)

    try:
        await client.start()
    except Exception as e:
        print(f"[account={account}] НЕ вдалося стартувати клієнт: {e}")
        return

    async with client:
        for cid in channel_ids:
            try:
                # delete_dialog по channel_id: для каналів/супергруп це leave
                await client.delete_dialog(cid)
                print(f"[account={account}] left channel_id={cid}")
                # затримка між відписками
                await asyncio.sleep(LEAVE_DELAY_SEC)
            except RPCError as e:
                print(f"[account={account}] RPCError на channel_id={cid}: {e}")
            except Exception as e:
                print(f"[account={account}] unexpected error на channel_id={cid}: {e}")


async def main():
    print(f"Using DB: {DB_PATH}")
    print(f"Using duplicates from: {DUP_JSON_PATH}")
    print(f"PRIMARY_ACCOUNT = {PRIMARY_ACCOUNT}")
    print(f"BASE_DIR = {BASE_DIR}")

    # 1. Завантажуємо дублі
    dup_map = load_duplicates()
    if not dup_map:
        print("❌ DUP_JSON порожній або не валідний. Спочатку запусти export_membership_duplicates.py")
        return

    # 2. Побудуємо мапу: account -> [channel_id, ...] (де треба вийти)
    to_leave: dict[str, set[int]] = {}

    for cid, entries in dup_map.items():
        accounts = {e["account"] for e in entries}
        if PRIMARY_ACCOUNT not in accounts:
            # для безпеки: не чіпаємо ті канали, де primary взагалі не був
            continue
        for e in entries:
            acc = e["account"]
            if acc == PRIMARY_ACCOUNT:
                continue
            to_leave.setdefault(acc, set()).add(cid)

    if not to_leave:
        print("Немає акаунтів, які треба відписати (to_leave порожній)")
        return

    print("\nПлан відписок:")
    for acc, cids in to_leave.items():
        print(f"  {acc}: вийти з {len(cids)} каналів")

    confirm = input("\nЩоб ПРОДОВЖИТИ і реально вийти з каналів, набери 'YES': ")
    if confirm != "YES":
        print("Скасовано користувачем.")
        return

    # 3. Спочатку вийдемо з каналів у Telegram
    for acc, cids in to_leave.items():
        await leave_for_account(acc, sorted(cids))

    # 4. Потім почистимо membership у БД
    con, cur = connect_db()
    total_deleted = 0

    for acc, cids in to_leave.items():
        for cid in cids:
            cur.execute(
                "DELETE FROM membership WHERE channel_id = ? AND account = ?",
                (cid, acc),
            )
            total_deleted += cur.rowcount

    con.commit()
    con.close()
    print(f"\nГотово. З membership видалено записів: {total_deleted}")


if __name__ == "__main__":
    asyncio.run(main())
