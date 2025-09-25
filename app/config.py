import os
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION = os.getenv("SESSION_NAME", "tg_session")

CONTROL_PEER = os.getenv("CONTROL_CHAT", "")
REPORT_CHAT = os.getenv("REPORT_CHAT", "")

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