#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import aiohttp
import telegram
import platform
from crypto_trader.config import config
from crypto_trader.utils import setup_logger, retry

logger = setup_logger("telegram_notifier")

class TelegramNotifier:
    """
    Handles telegram notifications with proper async management and error handling
    """
    def __init__(self, bot_token=None, chat_id=None):
        self.bot_token = bot_token or config.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or config.TELEGRAM_CHAT_ID
        self.bot = None
        self.loop = None
        self._session = None
        
        if not self.bot_token or not self.chat_id:
            logger.error("Telegram configuration missing! Please check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables")
            if not self.bot_token:
                logger.error("TELEGRAM_BOT_TOKEN is not set")
            if not self.chat_id:
                logger.error("TELEGRAM_CHAT_ID is not set")
            return
            
        try:
            self.bot = telegram.Bot(token=self.bot_token)
            
            # Configure asyncio for Windows
            if platform.system() == 'Windows':
                # Use SelectorEventLoop on Windows for aiodns compatibility
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
                logger.info("Using Windows SelectorEventLoop for asyncio")
            
            # Get or create an event loop
            try:
                self.loop = asyncio.get_event_loop()
                if self.loop.is_closed():
                    raise RuntimeError("Event loop is closed")
            except RuntimeError:
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)
                
            logger.info("Telegram bot initialized successfully")
            
            # Send test message
            self.send_message("🤖 Trading Bot Started - Telegram notifications are active")
        except Exception as e:
            logger.error(f"Failed to initialize Telegram bot: {str(e)}")
    
    async def _get_session(self):
        """
        Get or create aiohttp session for API calls
        """
        if self._session is None or self._session.closed:
            # Configure connection pool
            connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session
    
    async def close_session(self):
        """
        Close aiohttp session properly
        """
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    async def send_message_async(self, message):
        """
        Send Telegram message asynchronously
        
        Args:
            message (str): Message text
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.bot or not self.chat_id:
            logger.warning("Telegram bot not configured, skipping notification")
            return False
            
        try:
            # Get or create session
            session = await self._get_session()
            
            # Create a new bot instance with the session
            temp_bot = telegram.Bot(token=self.bot_token)
            temp_bot._session = session  # Set the session
            
            # Send message
            await temp_bot.send_message(
                chat_id=self.chat_id, 
                text=message, 
                parse_mode='HTML'
            )
            
            logger.debug(f"Telegram message sent: {message[:50]}...")
            return True
        except Exception as e:
            # Don't log sensitive data
            logger.error(f"Failed to send Telegram message: {str(e)}")
            return False
    
    @retry(max_retries=2, retry_delay=1.0)
    def send_message(self, message):
        """
        Send Telegram message (synchronous wrapper)
        
        Args:
            message (str): Message text
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.bot or not self.chat_id:
            logger.warning("Telegram bot not configured, skipping notification")
            return False
            
        try:
            # Run the async method in the event loop
            if self.loop and not self.loop.is_closed():
                return self.loop.run_until_complete(self.send_message_async(message))
            else:
                # Create a new loop if the current one is closed
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)
                return self.loop.run_until_complete(self.send_message_async(message))
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {str(e)}")
            return False
            
    def close(self):
        """
        Close resources properly
        """
        if self.loop and not self.loop.is_closed():
            try:
                # Close aiohttp session
                if self._session:
                    self.loop.run_until_complete(self.close_session())
                
                # Close the loop
                self.loop.close()
            except Exception as e:
                logger.error(f"Error closing Telegram notifier resources: {str(e)}")
                # Make best effort to close session
                import asyncio
                if self._session and not self._session.closed:
                    try:
                        asyncio.run(self._session.close())
                    except:
                        pass 