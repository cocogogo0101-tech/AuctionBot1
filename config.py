# config.py
from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

DATABASE_URL = os.getenv("DATABASE_URL", "")

# defaults (can be overridden via in-server config commands)
DEFAULT_COMMISSION = int(os.getenv("DEFAULT_COMMISSION", "20"))
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "Credits")
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "2"))

# UI / defaults
DEFAULT_MIN_INCREMENT = 50_000
DEFAULT_START_BID = 250_000
DEFAULT_AUCTION_DURATION_MIN = 5
