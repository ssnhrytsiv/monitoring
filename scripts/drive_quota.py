from __future__ import annotations

"""
Простий скрипт для перегляду квоти Google Drive для service account.
Використання:
    python -m scripts.drive_quota
Потрібен файл service_account.json у корені проєкту та встановлений google-api-python-client.
"""

import json
import sys
from pathlib import Path

try:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
except Exception as e:
    print("google-api-python-client не встановлений або недоступний:", e)
    sys.exit(1)


def main() -> int:
    creds_path = Path("service_account.json")
    if not creds_path.exists():
        print("service_account.json не знайдено у корені проєкту.")
        return 1

    scopes = ["https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(str(creds_path), scopes=scopes)
    svc = build("drive", "v3", credentials=creds)

    about = svc.about().get(fields="storageQuota").execute()
    print(json.dumps(about.get("storageQuota", {}), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
