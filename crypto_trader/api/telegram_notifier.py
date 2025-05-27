#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import aiohttp
import telegram
import platform
from crypto_trader.config import config
from crypto_trader.utils import setup_logger, retry
from typing import Optional

logger = setup_logger("telegram_notifier")

class TelegramNotifier:
    """
    Handles telegram notifications with proper async management and error handling
    """
    def __init__(self, token: str = None, chat_id: str = None):
        self.token = token or config.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or config.TELEGRAM_CHAT_ID
        
        if not self.token or not self.chat_id:
            logger.warning("Telegram bot not configured (missing token or chat_id)")
            
        self.logger = setup_logger("telegram_notifier")
        self._session: Optional[aiohttp.ClientSession] = None
        self.loop = None
        
    async def __aenter__(self):
        connector = aiohttp.TCPConnector(ssl=False)
        self._session = aiohttp.ClientSession(connector=connector)
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session and not self._session.closed:
            await self._session.close()
            
    async def ensure_session(self):
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session
            
    async def close(self):
        """
        Close resources properly
        """
        if self.loop and not self.loop.is_closed():
            try:
                # Close aiohttp session
                if self._session and not self._session.closed:
                    # Create a new event loop if needed
                    if self.loop.is_closed():
                        self.loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(self.loop)
                    await self.close_session()
                
                # Close the loop
                self.loop.close()
            except Exception as e:
                logger.error(f"Error closing Telegram notifier resources: {str(e)}")
                # Make best effort to close session
                if self._session and not self._session.closed:
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        await self._session.close()
                        loop.close()
                    except Exception as e:
                        logger.error(f"Failed to close session in fallback: {str(e)}")
            
    async def close_session(self):
        if self._session and not self._session.closed:
            await self._session.close()
            
    @retry(max_retries=3, retry_delay=1)
    async def send_message(self, message: str) -> bool:
        """
        Send a message to Telegram with retries
        
        Args:
            message (str): Message to send
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            await self.ensure_session()
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            params = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            
            async with self._session.post(url, params=params) as response:
                if response.status == 200:
                    self.logger.info("Message sent successfully")
                    return True
                else:
                    error_text = await response.text()
                    self.logger.error(f"Failed to send message. Status: {response.status}, Error: {error_text}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error sending message: {str(e)}")
            return False

    @retry(max_retries=2, retry_delay=1.0)
    async def send_message_async(self, message):
        """
        Send Telegram message asynchronously with retries
        
        Args:
            message (str): Message text
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.token or not self.chat_id:
            logger.warning("Telegram bot not configured, skipping notification")
            return False
            
        try:
            # Get or create session
            session = await self.ensure_session()
            
            # Send message
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            params = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            
            async with session.post(url, params=params) as response:
                if response.status == 200:
                    logger.debug(f"Telegram message sent: {message[:50]}...")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to send message. Status: {response.status}, Error: {error_text}")
                    return False
        except Exception as e:
            # Don't log sensitive data
            logger.error(f"Failed to send Telegram message: {str(e)}")
            return False
    
    def send_message_sync(self, message):
        """
        Send Telegram message (synchronous wrapper)
        
        Args:
            message (str): Message text
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.token or not self.chat_id:
            logger.warning("Telegram bot not configured, skipping notification")
            return False
            
        try:
            # Create event loop if needed
            if not self.loop or self.loop.is_closed():
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)
            
            # Run the async method in the event loop
            return self.loop.run_until_complete(self.send_message_async(message))
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {str(e)}")
            return False 