"""
Crypto Trader - Automated cryptocurrency trading bot with Google Sheets integration

This package provides a modular framework for cryptocurrency trading automation:

1. API modules for exchange communication and Telegram notifications
2. Strategy modules for trade entry/exit logic and position management 
3. Google Sheets integration for trade signals and reporting
4. Configuration management and utilities

Author: [Author Name]
"""

__version__ = '1.0.0'

from crypto_trader.api import TelegramNotifier, CryptoExchangeAPI, GoogleSheetManager
from crypto_trader.strategies import ATRStrategy, Position, PositionManager
from crypto_trader.utils import setup_logger, normalize_price, format_quantity, parse_number, retry

__all__ = [
    'TelegramNotifier',
    'CryptoExchangeAPI',
    'GoogleSheetManager',
    'ATRStrategy',
    'Position',
    'PositionManager',
    'setup_logger',
    'normalize_price',
    'format_quantity',
    'parse_number',
    'retry'
] 