import os
from zoneinfo import ZoneInfo
from datetime import datetime

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip().strip('"').strip("'")
API_KEYS = [
    k.strip() for k in [
        os.environ.get("GEMINI_API_KEY", ""),
        os.environ.get("GEMINI_API_KEY_2", "")
    ] if k.strip()
]

ADMIN_IDS = [1745425595, 7850454902]
ADMIN_NAMES = {
    1745425595: "SACHIN SHARMA (मुख्य व्यवस्थापक)",
    7850454902: "सह-व्यवस्थापक (Co-Admin)"
}

CHANNEL_LINK = "https://t.me/UPSCHTML"
CHANNEL_NAME = "@UPSCHTML"
AUTHOR_NAME = "SACHIN SHARMA"

IST = ZoneInfo("Asia/Kolkata")

def get_ist_now():
    return datetime.now(IST)
  
