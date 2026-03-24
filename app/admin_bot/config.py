import os

from dotenv import load_dotenv

from app.utils.project_paths import PROJECT_ROOT, normalize_sqlite_url, resolve_project_path

# Load environment from root .env/.env.local similar to main app
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.local", override=True)


ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "")

# Telethon/DB settings (reuse same defaults as основний застосунок)
API_ID = int(os.getenv("API_ID", "0") or "0")
API_HASH = os.getenv("API_HASH", "")
SESSION_NAME = os.getenv("SESSION_NAME", "tg_session")
DB_PATH = str(resolve_project_path(os.getenv("DB_PATH", "post_watchdog.sqlite3")))

# SQLAlchemy database URL (SQLite file by default)
SQLALCHEMY_DATABASE_URL = normalize_sqlite_url(
    os.getenv("SQLALCHEMY_DATABASE_URL"),
    default_path=DB_PATH,
)


def _parse_ids(val: str | None) -> list[int]:
    if not val:
        return []
    out = []
    for part in val.split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.append(int(p))
        except Exception:
            continue
    return out


# Allow-list for admin bot commands (tg_id); empty -> allow all
ADMIN_ALLOWED_IDS = _parse_ids(os.getenv("ADMIN_ALLOWED_IDS"))
