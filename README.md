# Crypto Trader Bot

Automated cryptocurrency trading bot with Google Sheets integration for trade signals.

## Features

- **API Integration**: Connects to Crypto.com Exchange API for real-time trading
- **Google Sheets Integration**: Reads trade signals from spreadsheets and updates results
- **Telegram Notifications**: Real-time alerts for trades and bot status
- **Thread-Safe Trading**: Manages concurrent operations safely
- **Modular Architecture**: Well-organized code for easy maintenance and extension
- **ATR-Based Strategies**: Calculates stop-loss and take-profit levels using Average True Range
- **Trailing Stop-Loss**: Automatically adjusts stop-loss levels as price increases
- **Comprehensive Error Handling**: Resilient to API failures and network issues

## Installation

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/crypto-trader.git
   cd crypto-trader
   ```

2. Install the package:
   ```
   pip install -e .
   ```

3. Create a `.env` file with your API credentials:
   ```
   CRYPTO_API_KEY=your_api_key
   CRYPTO_API_SECRET=your_api_secret
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token
   TELEGRAM_CHAT_ID=your_telegram_chat_id
   GOOGLE_SHEET_ID=your_google_sheet_id
   GOOGLE_WORKSHEET_NAME=Trading
   GOOGLE_CREDENTIALS_FILE=credentials.json
   TRADE_AMOUNT=10
   ```

4. Place your Google API Service Account credentials in `credentials.json`.

## Usage

Start the bot with the default configuration:

```
python main.py
```

Set a specific log level:

```
python main.py --log-level DEBUG
```

## Google Sheet Format

The bot expects a Google Sheet with the following columns:

- `TRADE`: Set to "YES" to enable trading for a coin
- `Coin`: Cryptocurrency symbol (e.g., "BTC", "ETH", "SUI")
- `Buy Signal`: "BUY" to purchase, "SELL" to sell, "WAIT" for no action
- `Tradable`: "YES" to allow trading, "NO" to disable
- `Take Profit`: Take profit price level (optional)
- `Stop-Loss`: Stop loss price level (optional)
- `Resistance Up`: Upper resistance level (optional)
- `Resistance Down`: Lower support level (optional)

## Architecture

The codebase follows a modular design with the following components:

- `crypto_trader/api/`: API integrations for exchange, Google Sheets, Telegram
- `crypto_trader/strategies/`: Trading strategy implementations
- `crypto_trader/utils/`: Helper utilities and tools
- `crypto_trader/config/`: Configuration management

## License

MIT License

## Contributors

- Your Name <your.email@example.com> 