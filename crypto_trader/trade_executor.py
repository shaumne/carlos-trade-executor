#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import signal
import sys
import logging
import asyncio

from crypto_trader.api import TelegramNotifier, CryptoExchangeAPI, GoogleSheetManager
from crypto_trader.strategies import PositionManager
from crypto_trader.utils import setup_logger
from crypto_trader.config import config

# Set up logger
logger = setup_logger("trade_executor", logging.INFO)

class TradeExecutor:
    """
    Main trade execution controller that coordinates all components
    """
    
    def __init__(self):
        """Initialize trade executor with all required components"""
        
        logger.info("Initializing Trade Executor")
        
        # Initialize components
        try:
            # Telegram notifier for alerts
            self.telegram = TelegramNotifier()  # No need to pass token and chat_id, will get from config
            logger.info("Initialized Telegram notifier")
            
            # Exchange API for trading
            self.exchange_api = CryptoExchangeAPI()
            logger.info("Initialized Exchange API")
            
            # Google Sheet manager for signals and reporting
            self.sheet_manager = GoogleSheetManager()
            logger.info("Initialized Google Sheet Manager")
            
            # Position manager for tracking and executing trades
            self.position_manager = PositionManager(
                self.exchange_api, 
                self.sheet_manager,
                self.telegram
            )
            logger.info("Initialized Position Manager")
            
            # Runtime control
            self.running = False
            self.check_interval = config.TRADE_CHECK_INTERVAL
            
            # Register signal handlers for graceful shutdown
            signal.signal(signal.SIGINT, self.handle_shutdown)
            signal.signal(signal.SIGTERM, self.handle_shutdown)
            
            # Initialization complete
            logger.info("Trade Executor initialized successfully")
            
        except Exception as e:
            logger.critical(f"Initialization failed: {str(e)}")
            raise
    
    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info(f"Received shutdown signal {signum}, stopping...")
        self.running = False
    
    def process_signals(self):
        """Process trade signals from the sheet"""
        try:
            # Get signals from the sheet
            signals = self.sheet_manager.get_trade_signals()
            
            if not signals:
                logger.debug("No trade signals found")
                return 0
            
            count = 0
            
            # Process signals
            for signal in signals:
                symbol = signal.get('symbol')
                action = signal.get('action')
                
                logger.info(f"Processing {action} signal for {symbol}")
                
                # Execute based on action
                if action == "BUY":
                    # Skip if already have an active position
                    if self.position_manager.has_active_position(symbol):
                        logger.debug(f"Skipping BUY for {symbol} - already have an active position")
                        continue
                    
                    # Execute buy
                    success = self.position_manager.execute_buy(signal)
                    if success:
                        count += 1
                        logger.info(f"BUY executed successfully for {symbol}")
                    else:
                        logger.warning(f"BUY execution failed for {symbol}")
                
                elif action == "SELL":
                    # Execute sell
                    success = self.position_manager.execute_sell(signal)
                    if success:
                        count += 1
                        logger.info(f"SELL executed successfully for {symbol}")
                    else:
                        logger.warning(f"SELL execution failed for {symbol}")
                
                # Small delay between trades
                time.sleep(0.5)
            
            return count
            
        except Exception as e:
            logger.error(f"Error processing trade signals: {str(e)}")
            return 0
    
    def monitor_positions(self):
        """Check active positions for take profit/stop loss conditions"""
        try:
            return self.position_manager.check_positions()
        except Exception as e:
            logger.error(f"Error monitoring positions: {str(e)}")
            return 0
    
    async def send_telegram_message(self, message):
        """Send a Telegram message asynchronously"""
        if self.telegram:
            try:
                await self.telegram.send_message_async(message)
            except Exception as e:
                logger.error(f"Error sending Telegram message: {str(e)}")

    def run(self):
        """Main execution loop"""
        logger.info("Starting Trade Executor")
        
        # Create event loop for async operations
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Send startup notification
        if self.telegram:
            loop.run_until_complete(self.send_telegram_message("🤖 Trading Bot Started"))
        
        self.running = True
        last_report_time = 0
        
        try:
            while self.running:
                # Process any new trade signals
                signals_processed = self.process_signals()
                
                # Monitor active positions
                positions_checked = self.monitor_positions()
                
                # Every 5 minutes, log status report
                current_time = time.time()
                if current_time - last_report_time > 300:  # 5 minutes
                    # Get count of active positions
                    active_positions = len(self.position_manager.positions)
                    
                    logger.info(f"Status Report: {active_positions} active positions")
                    last_report_time = current_time
                
                # Sleep until next check cycle
                logger.debug(f"Completed trade cycle, next check in {self.check_interval} seconds")
                time.sleep(self.check_interval)
                
        except KeyboardInterrupt:
            logger.info("Trade Executor stopped by user")
        except Exception as e:
            logger.critical(f"Trade Executor crashed: {str(e)}")
            
            # Send crash notification
            if self.telegram:
                loop.run_until_complete(self.send_telegram_message(f"⚠️ Trading Bot Crashed: {str(e)}"))
            
            raise
        finally:
            self.cleanup()
            loop.close()
    
    def cleanup(self):
        """Clean up resources before exit"""
        logger.info("Cleaning up resources")
        
        # Close connections in reverse order of initialization
        try:
            # First close position manager as it depends on other components
            if hasattr(self, 'position_manager'):
                self.position_manager.close()
                logger.debug("Position manager closed")
            
            # Then close sheet manager
            if hasattr(self, 'sheet_manager'):
                self.sheet_manager.close()
                logger.debug("Sheet manager closed")
            
            # Then close exchange API
            if hasattr(self, 'exchange_api'):
                self.exchange_api.close()
                logger.debug("Exchange API closed")
            
            # Finally close telegram notifier
            if hasattr(self, 'telegram'):
                # Create a new event loop for async cleanup
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self.telegram.close())
                    logger.debug("Telegram notifier closed")
                except Exception as e:
                    logger.error(f"Error closing telegram notifier: {str(e)}")
                finally:
                    loop.close()
                
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
        
        logger.info("Trade Executor shutdown complete")

def main():
    """Entry point for the application"""
    try:
        # Initialize and run the executor
        executor = TradeExecutor()
        executor.run()
    except Exception as e:
        logger.critical(f"Fatal error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main() 