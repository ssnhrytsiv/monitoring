"""
Створення Google Spreadsheet від імені service account (може бути в Shared Drive).

Приклад:
  python -m scripts.drive_create_sheet_sa --sa service_account.json --title "Test sheet" --drive-id <SHARED_DRIVE_ID>

Якщо drive-id не вказано — таблиця створюється у My Drive сервіс-акаунта.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

try:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
except Exception as e:  # pragma: no cover
    print("Не встановлені google-api-python-client / google-auth. Встанови: pip install google-api-python-client google-auth")
    print(f"Деталі: {e}")
    sys.exit(1)


SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]


def create_sheet(sa_path: str, title: str, drive_id: Optional[str] = None) -> Optional[dict]:
    creds = Credentials.from_service_account_file(sa_path, scopes=SCOPES)
    drive = build("drive", "v3", credentials=creds)

    body = {
        "name": title,
        "mimeType": "application/vnd.google-apps.spreadsheet",
    }
    params = {"supportsAllDrives": True, "fields": "id,name,webViewLink"}
    if drive_id:
        body["parents"] = [drive_id]

    try:
        file = drive.files().create(body=body, **params).execute()
        return file
    except Exception as e:
        print(f"Не вдалося створити таблицю: {e!r}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Створити Google Spreadsheet від service account")
    parser.add_argument("--sa", required=True, help="Шлях до service_account.json")
    parser.add_argument("--title", required=True, help="Назва таблиці")
    parser.add_argument("--drive-id", help="ID Shared Drive (якщо потрібно створити в Shared Drive)")
    args = parser.parse_args()

    res = create_sheet(args.sa, args.title, args.drive_id)
    if not res:
        return 1

    print(f"Створено: id={res.get('id')} name={res.get('name')} link={res.get('webViewLink')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
