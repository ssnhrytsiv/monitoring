from __future__ import annotations

import os
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import GSHEET_SPREADSHEET_ID, GSHEET_CREDS_FILE

log = logging.getLogger("services.gsheets_writer_transport")

# Ліниво імпортуємо SDK — щоб у разі відсутності пакетів дати зрозуміле повідомлення
try:
    import gspread  # type: ignore
    from google.oauth2.service_account import Credentials  # type: ignore
except Exception as e:
    gspread = None  # type: ignore
    Credentials = None  # type: ignore
    print("gsheets_writer: Google SDK not available:", repr(e))
    if log:
        log.error("Google SDK not available: %s", e)

# --- Константи: шапка аркуша та A1-діапазон повного рядка
HEADER = [
    "Назва каналу",             # A
    "Посилання на канал",       # B
    "Дата виходу і час",        # C  (у клітинках зберігаємо ЛИШЕ час)
    "Перегляди",                # D  (форматуємо тис. розділювачем — пробіл)
    "Дата видалення і час",     # E  (у клітинках зберігаємо ЛИШЕ час)
    "Назва поста",              # F
    "Посилання",                # G
    "Адмін",                    # H
    "Watch ID",                 # I
]
ROW_RANGE = ("A", "I")

# --- Кеш клієнтів/об'єктів
_GC = None          # gspread client (authorize)
_SH = None          # spreadsheet object (open_by_key)
_WS_CACHE: Dict[str, Any] = {}      # title -> worksheet
_SHEETS_WITH_HEADER: set[str] = set()

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


# -------------------- низькорівневий транспорт --------------------

def _print_err(msg: str, exc: Exception | None = None):
    """Лог помилки."""
    if exc:
        print(f"gsheets_writer ERROR: {msg}: {exc!r}")
        log.error("%s: %s", msg, exc, exc_info=True)
    else:
        print(f"gsheets_writer ERROR: {msg}")
        log.error(msg)


def _client():
    """Створити/повернути авторизований клієнт gspread (кешований)."""
    global _GC
    if gspread is None or Credentials is None:
        _print_err("Google SDK is not installed (gspread / google-auth). pip install gspread google-auth")
        return None
    if _GC is not None:
        return _GC
    try:
        if not GSHEET_CREDS_FILE or not os.path.exists(GSHEET_CREDS_FILE):
            _print_err(f"Credentials file not found: {GSHEET_CREDS_FILE!r}")
            return None
        with open(GSHEET_CREDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(data, scopes=scopes)
        _GC = gspread.authorize(creds)
        return _GC
    except Exception as e:
        _print_err("Failed to authorize Google client", e)
        _GC = None
        return None


def _open_spreadsheet():
    """Відкрити (або повернути з кешу) Google Spreadsheet по ключу."""
    global _SH
    try:
        if _SH is not None:
            return _SH
        gc = _client()
        if not gc:
            return None
        if not GSHEET_SPREADSHEET_ID:
            _print_err("GSHEET_SPREADSHEET_ID is empty")
            return None
        _SH = gc.open_by_key(GSHEET_SPREADSHEET_ID)
        return _SH
    except Exception as e:
        _print_err(f"Failed to open spreadsheet by key {GSHEET_SPREADSHEET_ID}", e)
        _SH = None
        return None


def _apply_default_sheet_formatting(ws) -> None:
    """
    Форматує аркуш:
      - A1:I1 жирним та по центру;
      - A2:I3000 — по центру (горизонтально) і по середині (вертикально);
      - додає фільтр на діапазон A1:I3000;
      - авто-підбір ширини колонок A..I під вміст.
    Безпечна до багаторазового виклику.
    """
    try:
        sheet_id = ws.id  # gspread>=5
    except Exception:
        sheet_id = getattr(getattr(ws, "_properties", {}), "get", lambda *_: None)("sheetId")

    if sheet_id is None:
        _print_err("_apply_default_sheet_formatting: cannot resolve sheetId")
        return

    start_col = 0                      # A
    end_col = len(HEADER)              # I -> 9
    head_start_row = 0                 # 1-й рядок (0-індекс)
    head_end_row = 1
    body_start_row = 1                 # 2-й рядок
    body_end_row = 3000                # ексклюзивно (покриє 2..3000)

    requests = [
        # 1) A1:I1 — жирний і по центру
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": head_start_row,
                    "endRowIndex": head_end_row,
                    "startColumnIndex": start_col,
                    "endColumnIndex": end_col,
                },
                "cell": {
                    "userEnteredFormat": {
                        "horizontalAlignment": "CENTER",
                        "textFormat": {"bold": True},
                    }
                },
                "fields": "userEnteredFormat(horizontalAlignment,textFormat.bold)",
            }
        },
        # 2) A2:I3000 — по центру (горизонтально і вертикально)
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": body_start_row,
                    "endRowIndex": body_end_row,
                    "startColumnIndex": start_col,
                    "endColumnIndex": end_col,
                },
                "cell": {
                    "userEnteredFormat": {
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment)",
            }
        },
        # 3) Базовий фільтр на A1:I3000
        {
            "setBasicFilter": {
                "filter": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": head_start_row,
                        "endRowIndex": body_end_row,
                        "startColumnIndex": start_col,
                        "endColumnIndex": end_col,
                    }
                }
            }
        },
        # 4) Авто-підбір ширини колонок A..I
        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": start_col,
                    "endIndex": end_col,
                }
            }
        },
    ]

    try:
        ws.spreadsheet.batch_update({"requests": requests})
        log.debug("gsheets: formatting applied on sheetId=%s", sheet_id)
    except Exception as e:
        _print_err("Failed to apply default sheet formatting", e)


def _get_or_create_worksheet(sh, title: str):
    """
    Відкрити аркуш з назвою `title` або створити, якщо нема.
    Гарантуємо шапку у першому рядку та застосовуємо форматування ОДИН раз.
    """
    global _WS_CACHE, _SHEETS_WITH_HEADER
    try:
        ws = _WS_CACHE.get(title)
        created_now = False

        if ws is None:
            # Спробувати відкрити існуючий аркуш
            try:
                ws = sh.worksheet(title)
            except Exception:
                # Немає — створити
                ws = sh.add_worksheet(title=title, rows=1000, cols=len(HEADER))
                created_now = True
            _WS_CACHE[title] = ws

        # Якщо для цього аркуша ми вже один раз забезпечили шапку/формат — все, кінець.
        if title in _SHEETS_WITH_HEADER:
            return ws

        if created_now:
            # Поставити шапку + формат один раз, без GET A1:1
            try:
                ws.update(f"{ROW_RANGE[0]}1:{ROW_RANGE[1]}1", [HEADER], value_input_option="RAW")
                log.debug("gsheets: header set on NEW sheet='%s' A1:I1", title)
            except Exception as e:
                _print_err(f"Failed to set header on new sheet '{title}'", e)

            try:
                _apply_default_sheet_formatting(ws)
            except Exception as e:
                _print_err(f"Failed to apply formatting on new sheet '{title}'", e)

            _SHEETS_WITH_HEADER.add(title)
            return ws

        # Якщо аркуш існує, але ще не знаємо про шапку — зробимо один контроль і закешуємо
        try:
            current = ws.row_values(1)
        except Exception:
            current = []
        try:
            if current != HEADER:
                ws.update(f"{ROW_RANGE[0]}1:{ROW_RANGE[1]}1", [HEADER], value_input_option="RAW")
                log.debug("gsheets: header enforced on sheet='%s' A1:I1", title)
        except Exception as e:
            _print_err(f"Failed to enforce header on existing sheet '{title}'", e)

        try:
            _apply_default_sheet_formatting(ws)
        except Exception as e:
            _print_err(f"Failed to apply formatting on existing sheet '{title}'", e)

        _SHEETS_WITH_HEADER.add(title)
        return ws

    except Exception as e:
        _print_err(f"Failed to get/create worksheet '{title}'", e)
        if title in _WS_CACHE:
            _WS_CACHE.pop(title, None)
        return None


# -------------------- Публічний транспортний API --------------------

def ensure_daily_sheet(sheet_title: str) -> bool:
    """Створити/переконатися, що аркуш існує і має шапку/формат."""
    sh = _open_spreadsheet()
    if not sh:
        return False
    ws = _get_or_create_worksheet(sh, sheet_title)
    return ws is not None


def append_rows(sheet_title: str, rows: List[List[str]]) -> None:
    """Додати ПАЧКУ рядків у кінець аркуша (USER_ENTERED)."""
    if not rows:
        return
    sh = _open_spreadsheet()
    if not sh:
        return
    ws = _get_or_create_worksheet(sh, sheet_title)
    if not ws:
        return
    try:
        if hasattr(ws, "append_rows"):
            ws.append_rows(rows, value_input_option="USER_ENTERED")
        else:
            for r in rows:
                ws.append_row(r, value_input_option="USER_ENTERED")
        log.debug("gsheets: appended %s rows to '%s'", len(rows), sheet_title)
    except Exception as e:
        _print_err(f"append_rows failed for sheet '{sheet_title}'", e)


def read_col_I(sheet_title: str) -> List[str]:
    """Прочитати всю колонку I (1-based індексація рядків у результаті флаша)."""
    sh = _open_spreadsheet()
    if not sh:
        return []
    ws = _get_or_create_worksheet(sh, sheet_title)
    if not ws:
        return []
    try:
        return ws.col_values(9)
    except Exception as e:
        _print_err(f"read_col_I failed for sheet '{sheet_title}'", e)
        return []


def batch_update_values(sheet_title: str, data: List[Dict[str, Any]]) -> None:
    """
    Один spreadsheets.values.batchUpdate для набору A1-діапазонів з valueInputOption=USER_ENTERED.
    data: [{"range": "'<sheet>'!C10:C10", "values": [["12:34:56"]]}, ...]
    """
    if not data:
        return
    sh = _open_spreadsheet()
    if not sh:
        return
    try:
        sh.values_batch_update({"data": data, "valueInputOption": "USER_ENTERED"})
        log.debug("gsheets: values_batch_update ranges=%s on '%s'", len(data), sheet_title)
    except Exception as e:
        _print_err(f"values_batch_update failed for sheet '{sheet_title}'", e)


def sheet_title_from_time_window_start(tws: str | None) -> str:
    """Повертає назву аркуша (YYYY-MM-DD) з time_window_start або поточної дати (Europe/Moscow)."""
    if tws:
        try:
            dt = datetime.strptime(tws, "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")