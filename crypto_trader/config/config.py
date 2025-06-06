#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import os.path
from pathlib import Path
from dotenv import load_dotenv

# Get the project root directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables from .env file in project root
env_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=env_path)

# API Credentials
CRYPTO_API_KEY = os.getenv("CRYPTO_API_KEY")
CRYPTO_API_SECRET = os.getenv("CRYPTO_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
    print("Warning: Telegram credentials not found in .env file")
    print(f"Looking for .env file at: {env_path}")
    print(f"Current environment variables:")
    print(f"TELEGRAM_BOT_TOKEN: {'Set' if TELEGRAM_BOT_TOKEN else 'Not Set'}")
    print(f"TELEGRAM_CHAT_ID: {'Set' if TELEGRAM_CHAT_ID else 'Not Set'}")

# Trading Parameters
TRADE_AMOUNT = float(os.getenv("TRADE_AMOUNT", "10"))  # Default trade amount in USDT
TRADE_CHECK_INTERVAL = int(os.getenv("TRADE_CHECK_INTERVAL", "5"))  # Default 5 seconds
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "5"))  # Process in batches
ATR_PERIOD = int(os.getenv("ATR_PERIOD", "14"))  # Default ATR period
ATR_MULTIPLIER = float(os.getenv("ATR_MULTIPLIER", "2.0"))  # Default ATR multiplier

# Google Sheets Configuration
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME", "Trading")
ARCHIVE_WORKSHEET_NAME = os.getenv("ARCHIVE_WORKSHEET_NAME", "Archive")

# API URLs
TRADING_BASE_URL = "https://api.crypto.com/exchange/v1/"
ACCOUNT_BASE_URL = "https://api.crypto.com/v2/"

# Coin Type Configurations
# Coins that typically use integer formats
INTEGER_COINS = ["SUI", "BONK", "SHIB", "DOGE", "PEPE"]
# Coins that typically use decimal formats with precision
DECIMAL_COINS = {
    "BTC": 6,
    "ETH": 6,
    "SOL": 4,
    "LTC": 4,
    "XRP": 2
}
# Default decimal precision if not specified
DEFAULT_PRECISION = 2

# Log Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.path.join(os.path.expanduser("~"), "crypto_trader.log")

# Retry Configuration
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("RETRY_DELAY", "1.0"))  # seconds

# Price Normalization Configuration
# Coins that need special price normalization due to decimal issues
NORMALIZATION_COINS = ["SUI", "DOGE", "BONK", "SHIB", "PEPE"]
# Threshold values for normalization
NORMALIZATION_THRESHOLD_HIGH = 10000
NORMALIZATION_THRESHOLD_LOW = 1000
# Divisor values for normalization
NORMALIZATION_DIVISOR_HIGH = 100000
NORMALIZATION_DIVISOR_LOW = 1000 