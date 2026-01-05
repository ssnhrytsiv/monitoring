# app/services/gsheets.py
#
# Legacy helper for gspread; не використовується в актуальному коді ( Sheets інтеграцію
# робимо через app/sheet_bot/services/gsheets_writer_transport ).
# Код залишено закоментованим як референс.
#
# import json
# from typing import Optional, List
# from app.config import GSHEET_SPREADSHEET_ID, GSHEET_CREDS_FILE, GSHEET_SUMMARY_SHEET
#
# try:
#     import gspread
#     from google.oauth2.service_account import Credentials
# except Exception:
#     gspread = None
#     Credentials = None
#
#
# def _client():
#     if not gspread or not Credentials:
#         return None
#     try:
#         with open(GSHEET_CREDS_FILE, "r", encoding="utf-8") as f:
#             data = json.load(f)
#     except Exception:
#         return None
#     scopes = [
#         "https://www.googleapis.com/auth/spreadsheets",
#         "https://www.googleapis.com/auth/drive.file",
#         "https://www.googleapis.com/auth/drive",
#     ]
#     creds = Credentials.from_service_account_info(data, scopes=scopes)
#     return gspread.authorize(creds)
#
#
# def append_summary_row(row: list) -> bool:
#     """(legacy) Append a row to fixed Summary sheet."""
#     try:
#         gc = _client()
#         if not gc:
#             return False
#         sh = gc.open_by_key(GSHEET_SPREADSHEET_ID)
#         ws = sh.worksheet(GSHEET_SUMMARY_SHEET)
#         ws.append_row(row, value_input_option="USER_ENTERED")
#         return True
#     except Exception:
#         return False
#
#
# def ensure_daily_sheet(title: str, headers: Optional[List[str]] = None):
#     """
#     Повертає worksheet з назвою `title`. Якщо аркуша нема — створює.
#     Якщо передано headers — і на аркуші порожньо, записує headers в перший рядок.
#     """
#     try:
#         gc = _client()
#         if not gc:
#             return None
#         sh = gc.open_by_key(GSHEET_SPREADSHEET_ID)
#         try:
#             ws = sh.worksheet(title)
#         except Exception:
#             ws = sh.add_worksheet(title=title, rows=1000, cols=max(8, len(headers or [])) or 8)
#             if headers:
#                 ws.append_row(headers, value_input_option="USER_ENTERED")
#         return ws
#     except Exception:
#         return None
