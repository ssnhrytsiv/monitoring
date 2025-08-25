# app/services/gsheets.py
import json
from app.config import GSHEET_SPREADSHEET_ID, GSHEET_CREDS_FILE, GSHEET_SUMMARY_SHEET

try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None
    Credentials = None

def _client():
    if not gspread or not Credentials:
        return None
    try:
        with open(GSHEET_CREDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(data, scopes=scopes)
    return gspread.authorize(creds)

def append_summary_row(row: list) -> bool:
    """Append a row to Summary sheet. Row is a list of values."""
    try:
        gc = _client()
        if not gc:
            return False
        sh = gc.open_by_key(GSHEET_SPREADSHEET_ID)
        ws = sh.worksheet(GSHEET_SUMMARY_SHEET)
        ws.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception:
        return False