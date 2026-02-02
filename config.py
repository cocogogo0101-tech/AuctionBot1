# config.py
"""
Configuration file for AuctionBot.
Contains all default settings, constants, and environment variable handling.
"""

from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# ==================== BOT SETTINGS ====================
# Bot token is read and sanitized in bot.py

# ==================== AUCTION DEFAULTS ====================
DEFAULT_COMMISSION = int(os.getenv("DEFAULT_COMMISSION", "20"))
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "Credits")
DEFAULT_MIN_INCREMENT = 50_000  # Default minimal bid increase (50K)
DEFAULT_START_BID = 250_000     # Default starting bid (250K)
DEFAULT_AUCTION_DURATION_MIN = 5  # Default auction duration in minutes

# ==================== TIMING SETTINGS ====================
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "2"))  # Cooldown between bids per user
COUNTDOWN_SECONDS = 3           # Final countdown duration before auction ends
INACTIVITY_THRESHOLD = 30       # Seconds of inactivity before starting countdown
PROMO_MIN_INTERVAL = 45         # Minimum seconds between promotional messages

# ==================== AUCTION BEHAVIOR ====================
MAX_BID_HISTORY_DISPLAY = 10    # Number of top bids to show in logs
PANEL_UPDATE_DELAY = 0.5        # Delay before updating panel after bid (seconds)

# ==================== RATE LIMITING ====================
MAX_BIDS_PER_MINUTE = 30        # Maximum bids allowed per user per minute (anti-spam)

# ==================== PERMISSIONS ====================
REQUIRED_BOT_PERMISSIONS = [
    "send_messages",
    "embed_links",
    "read_message_history",
    "add_reactions",
    "manage_messages",  # For deleting old panels
    "view_channel",
]

# ==================== DEBUG SETTINGS ====================
DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() == "true"
VERBOSE_LOGGING = os.getenv("VERBOSE_LOGGING", "False").lower() == "true"

# ==================== DATABASE SETTINGS ====================
DB_RETRY_ATTEMPTS = 3           # Number of retry attempts for DB operations
DB_RETRY_DELAY = 2              # Delay between retry attempts (seconds)

# ==================== COLORS (for embeds) ====================
COLOR_AUCTION_ACTIVE = 0x2F3136  # Dark gray for active auctions
COLOR_AUCTION_ENDED = 0xFFAA00   # Orange for ended auctions
COLOR_ERROR = 0xFF0000           # Red for errors
COLOR_SUCCESS = 0x00FF00         # Green for success
COLOR_INFO = 0x3498DB            # Blue for info
COLOR_WARNING = 0xFFFF00         # Yellow for warnings

# ==================== MESSAGES ====================
# Arabic error messages
MSG_NO_PERMISSION_AR = "ما عندك صلاحية لتنفيذ هذا الأمر"
MSG_COOLDOWN_AR = "انتظر شوية قبل المزايدة مرة ثانية"
MSG_NO_ACTIVE_AUCTION_AR = "ما فيه مزاد نشط حالياً"
MSG_ALREADY_HIGHEST_AR = "أنت بالفعل أعلى مزايد 👑"
MSG_INVALID_AMOUNT_AR = "المبلغ المدخل غير صحيح"
MSG_MIN_INCREMENT_AR = "لازم تزيد على الأقل {amount} عن أعلى مزايدة"
MSG_NO_ROLE_AR = "ما عندك رتبة رواد المزاد. تقدر تقدم على طلب الرتبة من {link}"
MSG_AUCTION_EXISTS_AR = "يوجد بالفعل مزاد نشط"
MSG_BID_ACCEPTED_AR = "المزايدة قُبلت: **{amount} {currency}**"
MSG_AUCTION_ENDED_AR = "🏁 **انتهى المزاد!**"
MSG_WINNER_AR = "الفائز: <@{user_id}> بمبلغ **{amount} {currency}**"
MSG_NO_BIDS_AR = "لم يتم تقديم أي مزايدات. السلعة لم تُباع."

# English messages (for admin commands)
MSG_INVALID_FORMAT_EN = "Invalid format. Examples: 250k / 2.5m / 1,000,000"
MSG_BOT_RESTRICTED_EN = "This bot is restricted to the configured server"
MSG_CONFIG_UPDATED_EN = "Configuration updated successfully"
MSG_AUCTION_OPENED_EN = "Auction opened successfully"
MSG_AUCTION_ENDED_EN = "Auction ended and logged"
MSG_BID_REMOVED_EN = "Last bid removed successfully"
MSG_NO_BIDS_TO_REMOVE_EN = "No bids to remove"

# ==================== VALIDATION ====================
MIN_BID_AMOUNT = 1_000          # Minimum allowed bid (1K)
MAX_BID_AMOUNT = 1_000_000_000_000  # Maximum allowed bid (1T)
MIN_AUCTION_DURATION = 1        # Minimum auction duration (minutes)
MAX_AUCTION_DURATION = 1440     # Maximum auction duration (24 hours)

# ==================== FEATURE FLAGS ====================
ENABLE_PROMO_MESSAGES = True    # Enable/disable promotional messages
ENABLE_COUNTDOWN_MESSAGES = True  # Enable/disable countdown messages in chat
ENABLE_AUTO_DELETE_OLD_PANELS = True  # Auto-delete old auction panels
ENABLE_BID_CONFIRMATIONS = True  # Send ephemeral confirmations for bids

# ==================== EXPORT ====================
__all__ = [
    'DEFAULT_COMMISSION',
    'DEFAULT_CURRENCY',
    'DEFAULT_MIN_INCREMENT',
    'DEFAULT_START_BID',
    'DEFAULT_AUCTION_DURATION_MIN',
    'COOLDOWN_SECONDS',
    'COUNTDOWN_SECONDS',
    'INACTIVITY_THRESHOLD',
    'PROMO_MIN_INTERVAL',
    'DEBUG_MODE',
    'VERBOSE_LOGGING',
    'REQUIRED_BOT_PERMISSIONS',
    'COLOR_AUCTION_ACTIVE',
    'COLOR_AUCTION_ENDED',
    'COLOR_ERROR',
    'COLOR_SUCCESS',
    'COLOR_INFO',
    'COLOR_WARNING',
]
