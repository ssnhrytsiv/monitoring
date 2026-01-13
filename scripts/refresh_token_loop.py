"""
Periodic OAuth token refresher.

Runs in a loop, refreshing token.json (or GSHEET_OAUTH_TOKEN_FILE) every interval.
Useful when you want to proactively renew the access token using the stored refresh_token.
"""

import os
import time
from datetime import datetime
from typing import Sequence

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


SCOPES: Sequence[str] = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
)
TOKEN_PATH = os.getenv("GSHEET_OAUTH_TOKEN_FILE", "token.json")
INTERVAL_SEC = int(os.getenv("GSHEET_REFRESH_INTERVAL_SEC", "3600"))


def refresh_once() -> bool:
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    except Exception as e:
        print(f"[{datetime.now()}] failed to load credentials from {TOKEN_PATH}: {e}")
        return False

    if not creds.refresh_token:
        print(f"[{datetime.now()}] no refresh_token in {TOKEN_PATH}, cannot refresh")
        return False

    try:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        print(f"[{datetime.now()}] refreshed ok, new expiry={creds.expiry}")
        return True
    except Exception as e:
        print(f"[{datetime.now()}] refresh failed: {e}")
        return False


def main() -> None:
    print(
        f"Starting token refresher: token_file={TOKEN_PATH}, interval={INTERVAL_SEC}s, scopes={list(SCOPES)}"
    )
    while True:
        refresh_once()
        time.sleep(max(60, INTERVAL_SEC))


if __name__ == "__main__":
    main()
