import os
from dotenv import load_dotenv
load_dotenv()

# ─── BOT / DATABASE CONFIG ───────────────────────────────────────────────────
API_ID        = os.getenv("API_ID", "")
API_HASH      = os.getenv("API_HASH", "")
BOT_TOKEN     = os.getenv("BOT_TOKEN", "")
MONGO_DB      = os.getenv("MONGO_DB", "")
DB_NAME       = os.getenv("DB_NAME", "telegram_downloader")

# ─── OWNER / CONTROL SETTINGS ────────────────────────────────────────────────
OWNER_ID      = list(map(int, os.getenv("OWNER_ID", "").split()))
STRING        = os.getenv("STRING", None)   # optional 4GB Premium session string
_log_group    = os.getenv("LOG_GROUP", "")
LOG_GROUP     = int(_log_group) if _log_group else None

# ─── SECURITY KEYS ───────────────────────────────────────────────────────────
MASTER_KEY    = os.getenv("MASTER_KEY", "gK8HzLfT9QpViJcYeB5wRa3DmN7P2xUq")
IV_KEY        = os.getenv("IV_KEY", "s7Yx5CpVmE3F")
