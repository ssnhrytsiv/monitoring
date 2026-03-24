from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.admin_bot.config import SQLALCHEMY_DATABASE_URL

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


def migrate_reply_flags() -> None:
    with engine.begin() as conn:
        for table_name in ("post_template", "watch_posts"):
            info = list(conn.exec_driver_sql(f"PRAGMA table_info('{table_name}')"))
            if not info:
                continue
            column_names = {str(col[1]) for col in info}
            if "is_reply" in column_names:
                continue
            conn.exec_driver_sql(
                f"ALTER TABLE {table_name} ADD COLUMN is_reply INTEGER NOT NULL DEFAULT 0"
            )


def migrate_post_template_media() -> None:
    with engine.begin() as conn:
        info = list(conn.exec_driver_sql("PRAGMA table_info('post_template')"))
        if not info:
            return
        column_names = {str(col[1]) for col in info}
        if "photo_id" in column_names:
            return
        conn.exec_driver_sql("ALTER TABLE post_template ADD COLUMN photo_id TEXT")
