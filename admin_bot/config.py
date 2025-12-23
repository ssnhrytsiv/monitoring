import os
from dotenv import load_dotenv

# Load environment from root .env/.env.local similar to main app
load_dotenv()
load_dotenv(".env.local", override=True)


ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "")

# Telethon/DB settings (reuse same defaults as основний застосунок)
API_ID = int(os.getenv("API_ID", "0") or "0")
API_HASH = os.getenv("API_HASH", "")
SESSION_NAME = os.getenv("SESSION_NAME", "tg_session")
DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")

# SQLAlchemy database URL (SQLite file by default)
SQLALCHEMY_DATABASE_URL = os.getenv(
    "SQLALCHEMY_DATABASE_URL",
    f"sqlite:///{DB_PATH}",
)
