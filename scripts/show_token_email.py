"""
Виводить e-mail облікового запису з token.json (OAuth).

Використання:
    python -m scripts.show_token_email --token token.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
except Exception as e:
    print("Не знайдено google-auth/ google-api-python-client. Встанови: pip install google-auth google-auth-oauthlib google-api-python-client")
    print(f"Деталі: {e}")
    sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Показати e-mail з token.json")
    parser.add_argument("--token", default="token.json", help="Шлях до token.json (default: token.json)")
    args = parser.parse_args()

    token_path = Path(args.token)
    if not token_path.exists():
        print(f"Файл {token_path} не знайдено")
        return 1

    creds = Credentials.from_authorized_user_file(str(token_path), scopes=["https://www.googleapis.com/auth/drive"])
    # спробуємо через Drive API отримати email
    try:
        svc = build("drive", "v3", credentials=creds)
        info = svc.about().get(fields="user/emailAddress").execute()
        email = info["user"]["emailAddress"]
        print(f"Email: {email}")
    except Exception as e:
        print(f"Не вдалося отримати email через API: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
