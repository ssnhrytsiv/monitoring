#!/usr/bin/env python3
from __future__ import annotations

import os
import json
import sqlite3
import logging
from typing import List, Any, Optional

import gspread
from gspread.exceptions import WorksheetNotFound
from google.oauth2.service_account import Credentials

log = logging.getLogger("channels_table")

# Paths/env (зчитуються під час виклику, не при імпорті)
DB_PATH_DEFAULT = "post_watchdog.sqlite3"
SQL_FILE_DEFAULT = os.path.join(os.path.dirname(__file__), "channels_table.sql")
SHEET_NAME_DEFAULT = "Канали"

# Колонки після рефакторингу:
# 1) Назва канала
# 2) Посилання
# 3) Адмін
# 4) Дублікати (лише display name'и)
# 5) Нотатки
# 6) ID Канала (прихований стовпець)
HEADERS = [
    "Назва канала",
    "Посилання",
    "Адмін",
    "Дублікати",
    "Нотатки",
    "ID Канала",  # приховуємо цей стовпець
]

def load_sql(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def fetch_rows(db_path: str, sql_path: str) -> List[List[Any]]:
    sql = load_sql(sql_path)
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        data: List[List[Any]] = []
        for r in rows:
            # SQL повертає у порядку:
            # 0) title
            # 1) links_all
            # 2) admin_text
            # 3) duplicates_names
            # 4) notes
            # 5) channel_id
            data.append([
                r[0],  # Назва канала
                r[1],  # Посилання
                r[2],  # Адмін
                r[3],  # Дублікати (лише display name'и, кожен з нового рядка)
                r[4],  # Нотатки
                r[5],  # ID Канала (буде приховано)
            ])
        return data
    finally:
        con.close()

def get_client() -> gspread.Client:
    creds_path = os.getenv("GSHEET_CREDS_FILE") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path or not os.path.exists(creds_path):
        raise RuntimeError("Set GSHEET_CREDS_FILE or GOOGLE_APPLICATION_CREDENTIALS to service_account.json")
    with open(creds_path, "r", encoding="utf-8") as f:
        info = json.load(f)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/drive.file",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)

def ensure_ws(gc: gspread.Client, spreadsheet_id: str, sheet_name: str, headers: List[str]) -> gspread.Worksheet:
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(sheet_name)
    except WorksheetNotFound:
        # Створюємо аркуш без запису заголовків тут, щоб уникнути дублювання.
        ws = sh.add_worksheet(title=sheet_name, rows="2000", cols=str(len(headers)))
    return ws

def _max_line_len(s: str) -> int:
    if not s:
        return 0
    # Довжина найдовшого рядка (враховує переноси)
    return max((len(line) for line in str(s).splitlines()), default=0)

def _estimate_col_widths_px(headers: List[str], rows: List[List[Any]]) -> List[int]:
    """
    Оцінюємо ширину кожного стовпця в пікселях за максимальною довжиною рядка серед
    заголовка та всіх клітинок стовпця. Груба оцінка під Arial 10pt.
    Налаштовується змінними оточення:
      GSHEET_CHAR_PX, GSHEET_COL_PAD_PX, GSHEET_MIN_COL_PX, GSHEET_MAX_COL_PX
    """
    ncols = len(headers)
    # базові параметри
    CHAR_PX = float(os.getenv("GSHEET_CHAR_PX", "7.2"))          # ~середня ширина символа
    PAD_PX = int(os.getenv("GSHEET_COL_PAD_PX", "24"))           # відступ зліва+справа
    MIN_PX = int(os.getenv("GSHEET_MIN_COL_PX", "48"))           # мінімум
    MAX_PX = int(os.getenv("GSHEET_MAX_COL_PX", "720"))          # максимум (щоб не розтягувало на весь екран)

    # попередній підрахунок довжин у символах
    max_chars: List[int] = [0] * ncols

    for ci in range(ncols):
        max_chars[ci] = max(max_chars[ci], _max_line_len(headers[ci]))

    for row in rows:
        # ряд може бути коротшим/довшим (страхуємося)
        for ci in range(min(ncols, len(row))):
            val = row[ci]
            if val is None:
                continue
            max_chars[ci] = max(max_chars[ci], _max_line_len(str(val)))

    # переводимо в пікселі, обрізаємо за MIN/MAX
    widths_px: List[int] = []
    for ci in range(ncols):
        px = int(max_chars[ci] * CHAR_PX + PAD_PX)
        # трошки запасу для стовпців із довгими URL/іменами
        if headers[ci] in ("Посилання", "Дублікати"):
            px = int(px * 1.1 + 8)
        px = max(MIN_PX, min(px, MAX_PX))
        widths_px.append(px)

    return widths_px

def apply_formatting(ws: gspread.Worksheet, nrows: int, ncols: int, col_widths_px: Optional[List[int]] = None) -> None:
    sheet_id = ws._properties["sheetId"]
    requests = []

    # Freeze first row + show gridlines
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"frozenRowCount": 1, "hideGridlines": False},
            },
            "fields": "gridProperties.frozenRowCount,gridProperties.hideGridlines",
        }
    })

    # Header: bold + CENTER (по ширині) + TOP (по висоті) + wrap + light gray bg
    requests.append({
        "repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": ncols},
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {"bold": True},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "TOP",
                    "wrapStrategy": "WRAP",
                    "backgroundColor": {"red": 0.93, "green": 0.93, "blue": 0.93},
                }
            },
            "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment,wrapStrategy,backgroundColor)",
        }
    })

    # Body: TOP + wrap
    if nrows > 1:
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": nrows, "startColumnIndex": 0, "endColumnIndex": ncols},
                "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}},
                "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)",
            }
        })

    # Borders: outer + inner
    requests.append({
        "updateBorders": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": max(nrows, 1), "startColumnIndex": 0, "endColumnIndex": ncols},
            "top":    {"style": "SOLID", "color": {"red": 0.6, "green": 0.6, "blue": 0.6}},
            "bottom": {"style": "SOLID", "color": {"red": 0.6, "green": 0.6, "blue": 0.6}},
            "left":   {"style": "SOLID", "color": {"red": 0.6, "green": 0.6, "blue": 0.6}},
            "right":  {"style": "SOLID", "color": {"red": 0.6, "green": 0.6, "blue": 0.6}},
            "innerHorizontal": {"style": "SOLID", "color": {"red": 0.85, "green": 0.85, "blue": 0.85}},
            "innerVertical":   {"style": "SOLID", "color": {"red": 0.85, "green": 0.85, "blue": 0.85}},
        }
    })

    # Auto filter
    requests.append({
        "setBasicFilter": {
            "filter": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": max(nrows, 1), "startColumnIndex": 0, "endColumnIndex": ncols}
            }
        }
    })

    # Застосувати розраховану ширину стовпців (замість autoResizeDimensions)
    if col_widths_px and len(col_widths_px) == ncols:
        for idx in range(ncols):
            requests.append({
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": idx,
                        "endIndex": idx + 1
                    },
                    "properties": {"pixelSize": int(col_widths_px[idx])},
                    "fields": "pixelSize",
                }
            })

    # Приховати останній стовпець (ID Канала)
    requests.append({
        "updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": ncols - 1, "endIndex": ncols},
            "properties": {"hiddenByUser": True},
            "fields": "hiddenByUser",
        }
    })

    ws.spreadsheet.batch_update({"requests": requests})

def export_channels_table(logger: Optional[logging.Logger] = None) -> bool:
    """
    Виконує повний експорт у Google Sheet.
    Повертає True при успіху, False при помилці (помилка залогується).
    """
    log_local = logger or log
    try:
        spreadsheet_id = os.getenv("GSHEET_CHANNELS_SPREADSHEET_ID")
        if not spreadsheet_id:
            raise RuntimeError("GSHEET_CHANNELS_SPREADSHEET_ID is not set")

        db_path = os.getenv("DB_PATH", DB_PATH_DEFAULT)
        sql_path = os.getenv("CHANNELS_SQL_PATH", SQL_FILE_DEFAULT)
        sheet_name = os.getenv("GSHEET_CHANNELS_SHEET", SHEET_NAME_DEFAULT)

        rows = fetch_rows(db_path, sql_path)
        log_local.info("channels_export: fetched rows=%d", len(rows))

        gc = get_client()
        ws = ensure_ws(gc, spreadsheet_id, sheet_name, HEADERS)

        # Full rewrite
        ws.clear()
        ws.update("A1", [HEADERS], value_input_option="RAW")

        if rows:
            chunk = 3000
            start = 2
            for i in range(0, len(rows), chunk):
                part = rows[i:i+chunk]
                ws.update(f"A{start+i}", part, value_input_option="RAW")

        nrows = (len(rows) + 1) if rows else 1

        # Обчислити ширини за вмістом (заголовок + тіло)
        col_widths_px = _estimate_col_widths_px(HEADERS, rows)

        # Застосувати форматування + ширини
        apply_formatting(ws, nrows=nrows, ncols=len(HEADERS), col_widths_px=col_widths_px)

        log_local.info("channels_export: done sheet='%s' spreadsheet='%s'", sheet_name, spreadsheet_id)
        return True
    except Exception:
        log_local.exception("channels_export: failed")
        return False