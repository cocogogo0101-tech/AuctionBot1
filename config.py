# config.py
from dotenv import load_dotenv
import os

load_dotenv()

# Bot token should be read in bot.py and sanitized there.
DEFAULT_COMMISSION = int(os.getenv("DEFAULT_COMMISSION", "20"))
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "Credits")
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "2"))

# Auction defaults
DEFAULT_MIN_INCREMENT = 50_000  # default minimal increase
DEFAULT_START_BID = 250_000
DEFAULT_AUCTION_DURATION_MIN = 5