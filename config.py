"""Configuration settings for the geopolitical market monitor."""
import os
from dotenv import load_dotenv

load_dotenv()

def get_env_int(name: str, default: str) -> int:
    """Safely get an integer environment variable."""
    val = os.getenv(name, default).strip()
    if not val:
        return int(default)
    try:
        return int(val)
    except ValueError:
        print(f"[WARN] Invalid integer for {name}: '{val}'. Using default: {default}")
        return int(default)

def get_env_float(name: str, default: str) -> float:
    """Safely get a float environment variable."""
    val = os.getenv(name, default).strip()
    if not val:
        return float(default)
    try:
        return float(val)
    except ValueError:
        print(f"[WARN] Invalid float for {name}: '{val}'. Using default: {default}")
        return float(default)

# API Endpoints
POLYMARKET_GAMMA_BASE = os.getenv(
    "POLYMARKET_GAMMA_BASE", "https://gamma-api.polymarket.com"
)
POLYMARKET_CLOB_BASE = os.getenv(
    "POLYMARKET_CLOB_BASE", "https://clob.polymarket.com"
)
KALSHI_BASE = os.getenv(
    "KALSHI_BASE", "https://api.elections.kalshi.com/trade-api/v2"
)
KALSHI_WS_BASE = os.getenv(
    "KALSHI_WS_BASE", "wss://api.elections.kalshi.com/trade-api/ws/v2"
)

# Monitoring Parameters
# Alert when probability changes by this many percentage points (e.g., 10 = alert on 30%->40%)
PROBABILITY_CHANGE_THRESHOLD = get_env_float("PROBABILITY_CHANGE_THRESHOLD", "1.0")

# Polling and Rate Limiting
POLYMARKET_POLL_INTERVAL = get_env_int("POLYMARKET_POLL_INTERVAL", "60")  # seconds
KALSHI_POLL_INTERVAL = get_env_int("KALSHI_POLL_INTERVAL", "60")  # seconds
POLYMARKET_RATE_LIMIT = get_env_int("POLYMARKET_RATE_LIMIT", "10")  # requests per second
KALSHI_RATE_LIMIT = get_env_int("KALSHI_RATE_LIMIT", "5")  # requests per second

# Geopolitical Keywords (case-insensitive matching)
GEOPOLITICAL_KEYWORDS = [
    "invasion",
    "treaty",
    "election",
    "strike",
    "sovereignty",
    "war",
    "peace",
    "military",
    "terror",
    "negotiation",
    "middle east",
    "geopolitics",
    "conflict",
    "sanctions",
    "embargo",
    "diplomacy",
    "alliance",
    "coup",
    "revolution",
    "uprising",
]

# Data Retention
DATA_RETENTION_HOURS = get_env_int("DATA_RETENTION_HOURS", "24")

# Volume Filter
MIN_VOLUME = get_env_float("MIN_VOLUME", "250000.0")  # Minimum market volume in USD

# Spread Filter — exclude markets with bid-ask spread above this (0.05 = 5 cents)
MAX_SPREAD = get_env_float("MAX_SPREAD", "0.0")  # 0 = disabled

# Platform Toggles
ENABLE_POLYMARKET = os.getenv("ENABLE_POLYMARKET", "true").lower() == "true"
ENABLE_KALSHI = os.getenv("ENABLE_KALSHI", "false").lower() == "true"

# Tag Exclusion Filter (comma-separated tag slugs, e.g. "crypto-prices,sports-nba")
EXCLUDE_TAGS = [t.strip() for t in os.getenv("EXCLUDE_TAGS", "").split(",") if t.strip()]

# Event Tracking
TRACK_EVENT_SLUG = os.getenv("TRACK_EVENT_SLUG", "")
MIN_TRADE_USD = get_env_float("MIN_TRADE_USD", "1000.0")

# Persistence
STATE_FILE = os.getenv("STATE_FILE", "")  # Empty = default ~/.polymarket_monitor/state.json

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_MESSAGE_THREAD_ID = get_env_int("TELEGRAM_MESSAGE_THREAD_ID", "0") or None  # 0 = disabled
TELEGRAM_RATE_LIMIT = get_env_float("TELEGRAM_RATE_LIMIT", "1.0")
TELEGRAM_SEND_STATUS = os.getenv("TELEGRAM_SEND_STATUS", "false").lower() == "true"
TELEGRAM_SCHEDULE_HOUR = get_env_int("TELEGRAM_SCHEDULE_HOUR", "12")
TELEGRAM_ALLOWED_CHATS = [
    c.strip() for c in os.getenv("TELEGRAM_ALLOWED_CHATS", "").split(",") if c.strip()
]
TELEGRAM_TIMEZONE = os.getenv("TELEGRAM_TIMEZONE", "Asia/Singapore").strip()

# Kalshi Authentication (if required)
KALSHI_API_KEY = os.getenv("KALSHI_API_KEY", "").strip()
KALSHI_API_SECRET = os.getenv("KALSHI_API_SECRET", "").strip()
