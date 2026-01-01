"""
Отримання OAuth токена для Google Drive.

Використання:
    python -m scripts.drive_oauth_setup --secret client_secret_....json --token token.json

Після завершення з'явиться файл token.json з access+refresh token'ом.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except Exception as e:  # pragma: no cover - залежність може бути не встановлена
    print("Не знайдено google-auth-oauthlib. Встанови: pip install google-auth-oauthlib google-api-python-client")
    print(f"Деталі: {e}")
    sys.exit(1)


# За замовчуванням даємо доступ і до Drive, і до Sheets (потрібно для запису).
DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Отримати token.json для Google Drive OAuth")
    parser.add_argument("--secret", required=True, help="Шлях до client_secret_....json")
    parser.add_argument("--token", default="token.json", help="Куди зберегти token.json (default: token.json)")
    parser.add_argument(
        "--scopes",
        help=(
            "Перелік scope через кому. "
            "Якщо не вказано, використовуються Drive+Spreadsheets."
        ),
    )
    args = parser.parse_args()

    secret_path = Path(args.secret)
    if not secret_path.exists():
        print(f"Файл client_secret не знайдено: {secret_path}")
        return 1

    scopes = (
        [s.strip() for s in args.scopes.split(",") if s.strip()]
        if args.scopes
        else DEFAULT_SCOPES
    )

    flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), scopes)
    creds = flow.run_local_server(port=0)
    token_path = Path(args.token)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"Token збережено у {token_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
