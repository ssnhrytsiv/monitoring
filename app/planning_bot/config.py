import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
load_dotenv(".env.local", override=True)

PLANNING_BOT_TOKEN = os.getenv("PLANNING_BOT_TOKEN", "")

_admin_raw = os.getenv("PLANNING_ADMIN_CHAT_ID", "")
PLANNING_ADMIN_CHAT_IDS: list[int] = []
if _admin_raw:
    for part in _admin_raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            PLANNING_ADMIN_CHAT_IDS.append(int(part))
        except Exception:
            continue

# для зворотної сумісності
PLANNING_ADMIN_CHAT_ID = PLANNING_ADMIN_CHAT_IDS[0] if PLANNING_ADMIN_CHAT_IDS else None

# Список користувачів, яким дозволено використовувати inline-режим planning_bot
_inline_raw = os.getenv(
    "PLANNING_INLINE_ALLOWED_IDS", "300851736,7384359075,601395855"
)
PLANNING_INLINE_ALLOWED_IDS: list[int] = []
for part in _inline_raw.split(","):
    part = part.strip()
    if not part:
        continue
    try:
        PLANNING_INLINE_ALLOWED_IDS.append(int(part))
    except Exception:
        continue
