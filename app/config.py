import os
import logging
from dotenv import load_dotenv

# Базовий .env + локальні override (.env.local) для зручності розробки
load_dotenv()
load_dotenv(".env.local", override=True)

log = logging.getLogger("config")

ENV_MODE = os.getenv("ENV", "").lower()

def _pick_env(name: str, default: str = "") -> str:
    """
    Повертає значення змінної залежно від режиму:
      - якщо ENV=prod/production і є {NAME}_PROD -> повертає його;
      - якщо є {NAME}_LOCAL -> повертає його;
      - інакше бере NAME або default.
    """
    if ENV_MODE in ("prod", "production"):
        return os.getenv(f"{name}_PROD", os.getenv(name, default))
    return os.getenv(f"{name}_LOCAL", os.getenv(name, default))

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION = os.getenv("SESSION_NAME", "tg_session")

CONTROL_PEER = _pick_env("CONTROL_CHAT", "")
REPORT_CHAT = _pick_env("REPORT_CHAT", "")
BOT_TOKEN = _pick_env("BOT_TOKEN", "")

DEFAULT_FIND_INTERVAL = os.getenv("DEFAULT_FIND_INTERVAL", "30m")
DEFAULT_MON_INTERVAL  = os.getenv("DEFAULT_MON_INTERVAL", "1h")
DEFAULT_FIND_WINDOW   = os.getenv("DEFAULT_FIND_WINDOW", "72h")
DEFAULT_MON_WINDOW    = os.getenv("DEFAULT_MON_WINDOW", "24h")

DEFAULT_MODE = os.getenv("DEFAULT_MODE", "exact_strict")
DEFAULT_FUZZ = int(os.getenv("DEFAULT_FUZZ", "85"))
CASE_SENSITIVE = os.getenv("CASE_SENSITIVE", "false").lower() in ("1", "true", "yes")
WHOLE_WORD     = os.getenv("WHOLE_WORD", "false").lower() in ("1", "true", "yes")

DB_PATH = os.getenv("DB_PATH", "post_watchdog.sqlite3")

GSHEET_SPREADSHEET_ID = os.getenv("GSHEET_SPREADSHEET_ID", "")
GSHEET_CREDS_FILE     = os.getenv("GSHEET_CREDS_FILE", "service_account.json")
GSHEET_JOBS_SHEET     = os.getenv("GSHEET_JOBS_SHEET", "Jobs")
GSHEET_SUMMARY_SHEET  = os.getenv("GSHEET_SUMMARY_SHEET", "Summary")


GSHEET_CHANNELS_SPREADSHEET_ID= os.getenv("GSHEET_CHANNELS_SPREADSHEET_ID", "")
GSHEET_CHANNELS_SHEET= os.getenv("GSHEET_CHANNELS_SHEET", "Канали")


PLUGINS_PACKAGE = "app.plugins"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

WATCH_VIEWS_ENABLED = os.getenv("WATCH_VIEWS_ENABLED", "1").strip().lower() not in {"0","false","no","off"}

# helpers
def _as_bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    s = str(val).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return default

# Коли true – контрольний чат обробляє Aiogram‑бот, а головна Telethon‑сесія не запускається
CONTROL_VIA_BOT = _as_bool(_pick_env("CONTROL_VIA_BOT", "1"), default=True)
