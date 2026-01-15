from __future__ import annotations

import os
import time
import json
import logging
import threading
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from app.config import GSHEET_SPREADSHEET_ID, GSHEET_CREDS_FILE
from app.utils.time_utils import MOSCOW_TIME_FORMAT, moscow_now

log = logging.getLogger("services.gsheets_writer_transport")

try:
    import gspread  # type: ignore
    from google.oauth2.service_account import Credentials as SACredentials  # type: ignore
    from google.oauth2.credentials import Credentials as UserCredentials  # type: ignore
    from google.auth.transport.requests import Request  # type: ignore
    from googleapiclient.discovery import build  # type: ignore
except Exception as e:
    gspread = None  # type: ignore
    SACredentials = None  # type: ignore
    UserCredentials = None  # type: ignore
    Request = None  # type: ignore
    build = None  # type: ignore
    print("gsheets_writer: Google SDK not available:", repr(e))
    if log:
        log.error("Google SDK not available: %s", e)

HEADER = [
    "Назва каналу",
    "Посилання на канал",
    "Дата виходу і час",
    "Перегляди",
    "Дата видалення і час",
    "Назва поста",
    "Посилання",
    "Адмін",
    "Watch ID",
]
ROW_RANGE = ("A", "I")

_GC = None
_GC_SA = None
_SH_CACHE: Dict[str, Any] = {}
_WS_CACHE: Dict[str, Dict[str, Any]] = {}
_SHEETS_WITH_HEADER: set[Tuple[str, str]] = set()
_SHARE_ATTEMPTED: set[str] = set()
_REFRESH_THREAD = None
_REFRESH_STOP = None

GSHEET_DRIVE_ID = os.getenv("GSHEET_DRIVE_ID")
GSHEET_PREFER_SA = os.getenv("GSHEET_PREFER_SA", "1") == "1"
_SA_EMAIL: Optional[str] = None


def _print_err(msg: str, exc: Exception | None = None):
    if exc:
        print(f"gsheets_writer ERROR: {msg}: {exc!r}")
        log.error("%s: %s", msg, exc, exc_info=True)
    else:
        print(f"gsheets_writer ERROR: {msg}")
        log.error(msg)


def _refresh_loop():
    """
    Підтримує access token у token.json свіжим, викликаючи refresh кожен інтервал.
    Працює тільки якщо є OAuth token file і refresh_token.
    """
    global _REFRESH_STOP
    token_path = os.getenv("GSHEET_OAUTH_TOKEN_FILE", "token.json")
    interval = int(os.getenv("GSHEET_REFRESH_INTERVAL_SEC", "3600"))
    if interval < 300:
        interval = 300

    def _tick():
        from google.oauth2.credentials import Credentials  # type: ignore
        try:
            creds = Credentials.from_authorized_user_file(token_path, scopes=[
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/drive.file",
                "https://www.googleapis.com/auth/spreadsheets",
            ])
        except Exception:
            return
        if not getattr(creds, "refresh_token", None):
            return
        try:
            if Request is None:
                return
            creds.refresh(Request())
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
            log.debug("gsheets: token refreshed in background; new expiry=%s", getattr(creds, "expiry", None))
        except Exception:
            pass

    while _REFRESH_STOP and not _REFRESH_STOP.is_set():
        _tick()
        _REFRESH_STOP.wait(interval)


def _start_refresh_loop():
    """
    Стартує фоновий рефреш токена, якщо дозволено через GSHEET_REFRESH_LOOP=1.
    """
    global _REFRESH_THREAD, _REFRESH_STOP
    if os.getenv("GSHEET_REFRESH_LOOP", "0") not in {"1", "true", "yes", "on"}:
        return
    if _REFRESH_THREAD and _REFRESH_THREAD.is_alive():
        return
    _REFRESH_STOP = threading.Event()

    def _runner():
        try:
            _refresh_loop()
        finally:
            log.debug("gsheets: refresh loop stopped")

    _REFRESH_THREAD = threading.Thread(target=_runner, name="gsheets-refresh-loop", daemon=True)
    _REFRESH_THREAD.start()


def _client(service_only: bool = False):
    global _GC
    global _GC_SA
    global _SA_EMAIL
    if gspread is None or SACredentials is None:
        _print_err("Google SDK is not installed (gspread / google-auth). pip install gspread google-auth")
        return None

    # 1) Service Account (примусово, щоб створення йшло через SA)
    if _GC_SA is None:
        try:
            if not GSHEET_CREDS_FILE or not os.path.exists(GSHEET_CREDS_FILE):
                _print_err(f"Credentials file not found: {GSHEET_CREDS_FILE!r}")
            else:
                with open(GSHEET_CREDS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                scopes = [
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive.file",
                    "https://www.googleapis.com/auth/drive",
                ]
                creds_sa = SACredentials.from_service_account_info(data, scopes=scopes)
                _GC_SA = gspread.authorize(creds_sa)
                _SA_EMAIL = data.get("client_email")
                log.info("gsheets: using service account credentials (client_email=%s)", data.get("client_email"))
        except Exception as e:
            _print_err("Failed to authorize Google client (service account)", e)
            _GC_SA = None

    if not service_only and GSHEET_PREFER_SA and _GC_SA is not None:
        return _GC_SA

    if service_only:
        return _GC_SA

    if _GC is not None:
        return _GC

    # 2) OAuth token.json (user credentials)
    token_path = os.getenv("GSHEET_OAUTH_TOKEN_FILE", "token.json")
    if UserCredentials is not None and os.path.exists(token_path):
        try:
            creds = UserCredentials.from_authorized_user_file(token_path, scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive.file",
                "https://www.googleapis.com/auth/drive",
            ])
            if creds and creds.expired and creds.refresh_token and Request is not None:
                try:
                    creds.refresh(Request())
                except Exception as refresh_exc:
                    _print_err(f"Failed to refresh OAuth token from {token_path}", refresh_exc)
                    raise
                with open(token_path, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
            _GC = gspread.authorize(creds)
            log.info("gsheets: using OAuth token credentials from %s (client_id=%s)", token_path, creds.client_id)
            return _GC
        except Exception as e:
            _print_err(f"Failed to load OAuth token from {token_path}", e)
            _GC = None

    # fallback до SA, якщо OAuth не вдалось
    return _GC_SA


def create_spreadsheet(title: str) -> Optional[Dict[str, str]]:
    """
    Створює новий Spreadsheet і повертає {"spreadsheet_id": ..., "title": ...}.
    """
    # 1) Пробуємо через OAuth користувача (token.json) + Drive API, щоб створювати в Shared Drive
    if build and UserCredentials is not None:
        token_path = os.getenv("GSHEET_OAUTH_TOKEN_FILE", "token.json")
        if os.path.exists(token_path):
            try:
                scopes = [
                    "https://www.googleapis.com/auth/drive",
                    "https://www.googleapis.com/auth/drive.file",
                    "https://www.googleapis.com/auth/spreadsheets",
                ]
                creds_user = UserCredentials.from_authorized_user_file(token_path, scopes=scopes)
                if creds_user and creds_user.expired and creds_user.refresh_token and Request is not None:
                    creds_user.refresh(Request())
                    with open(token_path, "w", encoding="utf-8") as f:
                        f.write(creds_user.to_json())
                drive = build("drive", "v3", credentials=creds_user)
                body = {
                    "name": title,
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                }
                if GSHEET_DRIVE_ID:
                    body["parents"] = [GSHEET_DRIVE_ID]
                    log.info("gsheets: creating spreadsheet via OAuth in shared drive %s (title=%s)", GSHEET_DRIVE_ID, title)
                else:
                    log.info("gsheets: creating spreadsheet via OAuth in MyDrive (title=%s)", title)
                file = drive.files().create(
                    body=body,
                    fields="id,name",
                    supportsAllDrives=True,
                ).execute()
                # Поділимось на service account, щоб усі подальші операції міг виконувати SA
                sa_email = _SA_EMAIL
                if not sa_email and GSHEET_CREDS_FILE and os.path.exists(GSHEET_CREDS_FILE):
                    try:
                        with open(GSHEET_CREDS_FILE, "r", encoding="utf-8") as f:
                            sa_email = json.load(f).get("client_email")
                    except Exception:
                        sa_email = None
                if sa_email:
                    try:
                        drive.permissions().create(
                            fileId=file.get("id"),
                            supportsAllDrives=True,
                            body={
                                "type": "user",
                                "role": "writer",
                                "emailAddress": sa_email,
                            },
                            sendNotificationEmail=False,
                        ).execute()
                        log.info("gsheets: shared newly created sheet %s with service account %s", file.get("id"), sa_email)
                    except Exception as share_exc:
                        _print_err(f"Failed to share spreadsheet {file.get('id')} with SA {sa_email}", share_exc)
                return {"spreadsheet_id": file.get("id"), "title": file.get("name")}
            except Exception as e:
                _print_err("Failed to create spreadsheet via Drive API (OAuth)", e)

    # 2) Спроба через service account + Drive API
    if build and GSHEET_CREDS_FILE and os.path.exists(GSHEET_CREDS_FILE):
        try:
            scopes = [
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/drive.file",
                "https://www.googleapis.com/auth/spreadsheets",
            ]
            creds_sa = SACredentials.from_service_account_file(GSHEET_CREDS_FILE, scopes=scopes)
            drive = build("drive", "v3", credentials=creds_sa)
            body = {
                "name": title,
                "mimeType": "application/vnd.google-apps.spreadsheet",
            }
            if GSHEET_DRIVE_ID:
                body["parents"] = [GSHEET_DRIVE_ID]
                log.info("gsheets: creating spreadsheet in shared drive %s (title=%s) via SA", GSHEET_DRIVE_ID, title)
            else:
                log.info("gsheets: creating spreadsheet in MyDrive of service account (title=%s)", title)
            file = drive.files().create(
                body=body,
                fields="id,name",
                supportsAllDrives=True,
            ).execute()
            return {"spreadsheet_id": file.get("id"), "title": file.get("name")}
        except Exception as e:
            _print_err("Failed to create spreadsheet via Drive API (service account)", e)
    elif build is None:
        log.error("google-api-python-client is not installed; fallback to gspread create (без Shared Drive)")
    elif not GSHEET_CREDS_FILE or not os.path.exists(GSHEET_CREDS_FILE):
        _print_err("Cannot create spreadsheet: GSHEET_CREDS_FILE is missing", None)

    # 3) Фолбек через gspread (OAuth -> SA)
    gc = _client(service_only=False)
    if not gc:
        return None
    try:
        sh = gc.create(title)
        return {"spreadsheet_id": sh.id, "title": sh.title}
    except Exception as e:
        _print_err("Failed to create spreadsheet", e)
        return None


def _share_existing_with_sa(spreadsheet_id: str) -> bool:
    """
    Додає сервісний акаунт як writer до існуючої таблиці через OAuth-токен користувача.
    Викликаємо лише раз на кожний spreadsheet_id, щоб не плодити зайві запити.
    """
    if not spreadsheet_id or spreadsheet_id in _SHARE_ATTEMPTED:
        return False
    _SHARE_ATTEMPTED.add(spreadsheet_id)

    sa_email = _SA_EMAIL
    if not sa_email and GSHEET_CREDS_FILE and os.path.exists(GSHEET_CREDS_FILE):
        try:
            with open(GSHEET_CREDS_FILE, "r", encoding="utf-8") as f:
                sa_email = json.load(f).get("client_email")
        except Exception:
            sa_email = None
    if not sa_email:
        return False

    token_path = os.getenv("GSHEET_OAUTH_TOKEN_FILE", "token.json")
    if not os.path.exists(token_path) or UserCredentials is None or build is None:
        return False
    try:
        scopes = [
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/drive.file",
        ]
        creds_user = UserCredentials.from_authorized_user_file(token_path, scopes=scopes)
        if creds_user and creds_user.expired and creds_user.refresh_token and Request is not None:
            creds_user.refresh(Request())
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(creds_user.to_json())
        drive = build("drive", "v3", credentials=creds_user)
        drive.permissions().create(
            fileId=spreadsheet_id,
            supportsAllDrives=True,
            body={
                "type": "user",
                "role": "writer",
                "emailAddress": sa_email,
            },
            sendNotificationEmail=False,
        ).execute()
        log.info("gsheets: auto-shared spreadsheet %s with service account %s", spreadsheet_id, sa_email)
        return True
    except Exception as e:
        _print_err(f"Failed to auto-share spreadsheet {spreadsheet_id} with SA {sa_email}", e)
        return False


def _open_spreadsheet(spreadsheet_id: Optional[str] = None):
    try:
        key = spreadsheet_id or GSHEET_SPREADSHEET_ID
        if not key:
            _print_err("GSHEET_SPREADSHEET_ID is empty")
            return None
        if key in _SH_CACHE:
            return _SH_CACHE[key]
        gc = _client()
        if not gc:
            return None
        sh = gc.open_by_key(key)
        log.info("gsheets: opened spreadsheet key=%s title=%s", key, getattr(sh, 'title', None))
        _SH_CACHE[key] = sh
        return sh
    except Exception as e:
        _print_err(f"Failed to open spreadsheet by key {spreadsheet_id or GSHEET_SPREADSHEET_ID}", e)
        if spreadsheet_id and spreadsheet_id in _SH_CACHE:
            _SH_CACHE.pop(spreadsheet_id, None)
        sid = spreadsheet_id or GSHEET_SPREADSHEET_ID
        # Якщо бракує прав – спробуємо разово розшарити на сервісний акаунт через OAuth і повторити
        if sid and _share_existing_with_sa(sid):
            log.info("gsheets: retrying open after auto-share sid=%s", sid)
            return _open_spreadsheet(spreadsheet_id)
        return None


def _auto_resize_columns(ws) -> None:
    try:
        sheet_id = ws.id
    except Exception:
        sheet_id = getattr(getattr(ws, "_properties", {}), "get", lambda *_: None)("sheetId")
    if sheet_id is None:
        return
    start_col = 0
    end_col = len(HEADER)
    req = [
        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": start_col,
                    "endIndex": end_col,
                }
            }
        }
    ]
    try:
        ws.spreadsheet.batch_update({"requests": req})
    except Exception:
        pass


def _apply_default_sheet_formatting(ws) -> None:
    try:
        sheet_id = ws.id
    except Exception:
        sheet_id = getattr(getattr(ws, "_properties", {}), "get", lambda *_: None)("sheetId")

    if sheet_id is None:
        _print_err("_apply_default_sheet_formatting: cannot resolve sheetId")
        return

    start_col = 0
    end_col = len(HEADER)
    head_start_row = 0
    head_end_row = 1
    body_start_row = 1
    body_end_row = 3000
    rows_start = 0
    rows_end = 3000

    requests = [
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
                        "wrapStrategy": "CLIP"
                    }
                },
                "fields": "userEnteredFormat(wrapStrategy)",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": rows_start,
                    "endIndex": rows_end,
                },
                "properties": {
                    "pixelSize": 24
                },
                "fields": "pixelSize"
            }
        },
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


def _get_or_create_worksheet(sh, title: str, spreadsheet_id: Optional[str]):
    global _WS_CACHE, _SHEETS_WITH_HEADER
    ssid = spreadsheet_id or getattr(sh, "id", None) or GSHEET_SPREADSHEET_ID or ""
    cache = _WS_CACHE.setdefault(ssid, {})
    header_key = (ssid, title)
    try:
        ws = cache.get(title)
        created_now = False

        if ws is None:
            try:
                ws = sh.worksheet(title)
            except Exception:
                ws = sh.add_worksheet(title=title, rows=1000, cols=len(HEADER))
                created_now = True
            cache[title] = ws

        if header_key in _SHEETS_WITH_HEADER:
            return ws

        if created_now:
            try:
                ws.update(f"{ROW_RANGE[0]}1:{ROW_RANGE[1]}1", [HEADER], value_input_option="RAW")
                log.debug("gsheets: header set on NEW sheet='%s' A1:I1", title)
            except Exception as e:
                _print_err(f"Failed to set header on new sheet '{title}'", e)

            try:
                _apply_default_sheet_formatting(ws)
            except Exception as e:
                _print_err(f"Failed to apply formatting on new sheet '{title}'", e)

            _SHEETS_WITH_HEADER.add(header_key)
            return ws

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

        _SHEETS_WITH_HEADER.add(header_key)
        return ws

    except Exception as e:
        _print_err(f"Failed to get/create worksheet '{title}'", e)
        if title in cache:
            cache.pop(title, None)
        return None


def ensure_daily_sheet(sheet_title: str, spreadsheet_id: Optional[str] = None) -> bool:
    sh = _open_spreadsheet(spreadsheet_id)
    if not sh:
        return False
    ws = _get_or_create_worksheet(sh, sheet_title, spreadsheet_id)
    return ws is not None


# Опційний фоновий рефреш токена, щоб не запускати окрему команду
_start_refresh_loop()


def append_rows(sheet_title: str, rows: List[List[str]], spreadsheet_id: Optional[str] = None) -> None:
    if not rows:
        return
    sh = _open_spreadsheet(spreadsheet_id)
    if not sh:
        return
    ws = _get_or_create_worksheet(sh, sheet_title, spreadsheet_id)
    if not ws:
        return
    try:
        if hasattr(ws, "append_rows"):
            ws.append_rows(rows, value_input_option="USER_ENTERED")
        else:
            for r in rows:
                ws.append_row(r, value_input_option="USER_ENTERED")
        log.debug("gsheets: appended %s rows to '%s'", len(rows), sheet_title)
        try:
            _auto_resize_columns(ws)
            log.debug("gsheets: auto-resize columns after append on '%s'", sheet_title)
        except Exception as e:
            _print_err(f"auto-resize after append failed for sheet '{sheet_title}'", e)
    except Exception as e:
        _print_err(f"append_rows failed for sheet '{sheet_title}'", e)


def read_col_I(sheet_title: str, spreadsheet_id: Optional[str] = None) -> List[str]:
    sh = _open_spreadsheet(spreadsheet_id)
    if not sh:
        return []
    ws = _get_or_create_worksheet(sh, sheet_title, spreadsheet_id)
    if not ws:
        return []
    try:
        return ws.col_values(9)
    except Exception as e:
        _print_err(f"read_col_I failed for sheet '{sheet_title}'", e)
        return []


def batch_update_values(sheet_title: str, data: List[Dict[str, Any]], spreadsheet_id: Optional[str] = None) -> None:
    if not data:
        return
    sh = _open_spreadsheet(spreadsheet_id)
    if not sh:
        return
    try:
        sh.values_batch_update({"data": data, "valueInputOption": "USER_ENTERED"})
        log.debug("gsheets: values_batch_update ranges=%s on '%s'", len(data), sheet_title)
    except Exception as e:
        _print_err(f"values_batch_update failed for sheet '{sheet_title}'", e)


def sheet_title_from_time_window_start(tws: str | None) -> str:
    if tws:
        try:
            dt = datetime.strptime(tws, "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    return moscow_now().strftime("%Y-%m-%d")
