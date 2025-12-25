from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from admin_bot.config import SQLALCHEMY_DATABASE_URL

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()


def get_session():
    """Короткий helper для отримання Session у сервісах/хендлерах."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_admins_nullable() -> None:
    """
    Локальна міграція для admins: tg_id робимо nullable.
    SQLite не змінює схему автоматично, тож перебудовуємо таблицю, якщо треба.
    """
    with engine.begin() as conn:
        info = list(conn.exec_driver_sql("PRAGMA table_info('admins')"))
        if not info:
            return
        # columns: cid, name, type, notnull, dflt_value, pk
        tg_col = next((c for c in info if c[1] == "tg_id"), None)
        if tg_col is None:
            return
        notnull = tg_col[3]
        if notnull == 0:
            return  # already nullable

        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS admins_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id BIGINT UNIQUE,
                username VARCHAR,
                display VARCHAR
            );
            """
        )
        conn.exec_driver_sql(
            "INSERT OR IGNORE INTO admins_new (id, tg_id, username, display) "
            "SELECT id, tg_id, username, display FROM admins;"
        )
        conn.exec_driver_sql("DROP TABLE admins;")
        conn.exec_driver_sql("ALTER TABLE admins_new RENAME TO admins;")
