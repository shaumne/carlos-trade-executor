#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import threading
from crypto_trader.config import config
from crypto_trader.utils import setup_logger, normalize_price

logger = setup_logger("atr_strategy")

class ATRStrategy:
    """
    ATR (Average True Range) based strategy for calculating stop loss and take profit levels
    """
    
    def __init__(self, exchange_api, period=None, multiplier=None):
        """
        Initialize ATR strategy
        
        Args:
            exchange_api: Exchange API instance
            period (int, optional): ATR period
            multiplier (float, optional): ATR multiplier
        """
        self.exchange_api = exchange_api
        self.period = period or config.ATR_PERIOD
        self.multiplier = multiplier or config.ATR_MULTIPLIER
        
        # Cache for ATR values
        self._atr_cache = {}
        self._atr_cache_lock = threading.Lock()
    
    def calculate_atr(self, symbol):
        """
        Calculate ATR for a symbol
        
        Args:
            symbol (str): Trading symbol (e.g. BTC_USDT)
            
        Returns:
            float: ATR value
        """
        try:
            # Check if we have cached ATR
            current_time = time.time()
            
            with self._atr_cache_lock:
                if symbol in self._atr_cache:
                    cache_time, cached_atr = self._atr_cache[symbol]
                    # If cache is less than 1 hour old, use cached value
                    if current_time - cache_time < 3600:
                        logger.debug(f"Using cached ATR for {symbol}: {cached_atr}")
                        return cached_atr
            
            # Get current price
            current_price = self.exchange_api.get_current_price(symbol)
            
            if not current_price:
                logger.warning(f"Cannot get current price for {symbol}, using default ATR")
                # Default ATR values based on symbol
                default_atr_values = {
                    "BTC_USDT": 800.0,
                    "ETH_USDT": 50.0,
                    "SOL_USDT": 3.0,
                    "SUI_USDT": 0.1,
                    "BONK_USDT": 0.000001,
                    "DOGE_USDT": 0.01,
                    "XRP_USDT": 0.05
                }
                
                # Get default or calculate as percentage of price (3%)
                default_atr = default_atr_values.get(symbol, 0.03)
                
                with self._atr_cache_lock:
                    self._atr_cache[symbol] = (current_time, default_atr)
                
                return default_atr
            
            # Normalize price if needed
            current_price = normalize_price(current_price, symbol)
            
            # Simple approximation (3% of current price)
            # In a production-ready system, we would calculate true ATR
            # based on high-low-close data over the specified period
            atr = current_price * 0.03
            
            # Cache the result
            with self._atr_cache_lock:
                self._atr_cache[symbol] = (current_time, atr)
            
            logger.info(f"Calculated ATR for {symbol}: {atr}")
            return atr
            
        except Exception as e:
            logger.error(f"Error calculating ATR for {symbol}: {str(e)}")
            return current_price * 0.03 if current_price else 1.0
    
    def calculate_stop_loss(self, symbol, entry_price, swing_low=None):
        """
        Calculate stop loss based on ATR and swing low
        
        Args:
            symbol (str): Trading symbol
            entry_price (float): Entry price
            swing_low (float, optional): Swing low price
            
        Returns:
            float: Stop loss price
        """
        try:
            # Normalize price if needed
            entry_price = float(entry_price)
            
            if swing_low:
                swing_low = float(swing_low)
            
            # Calculate ATR
            atr = self.calculate_atr(symbol)
            
            # ATR-based stop loss
            atr_stop_loss = entry_price - (atr * self.multiplier)
            
            # If swing low provided, use the lower of the two
            if swing_low and swing_low < entry_price:
                final_stop_loss = min(atr_stop_loss, swing_low)
                # Add 1% buffer below swing low
                final_stop_loss = final_stop_loss * 0.99
            else:
                final_stop_loss = atr_stop_loss
            
            # Format to 4 decimal places
            final_stop_loss = round(float(final_stop_loss), 4)
            
            logger.info(f"Calculated stop loss for {symbol}: {final_stop_loss} (Entry: {entry_price}, ATR: {atr})")
            return final_stop_loss
            
        except Exception as e:
            logger.error(f"Error calculating stop loss for {symbol}: {str(e)}")
            # Default to 5% below entry with 4 decimal places
            return round(float(entry_price) * 0.95, 4)
    
    def calculate_take_profit(self, symbol, entry_price, resistance_level=None):
        """
        Calculate take profit based on ATR and resistance level
        
        Args:
            symbol (str): Trading symbol
            entry_price (float): Entry price
            resistance_level (float, optional): Resistance level
            
        Returns:
            float: Take profit price
        """
        try:
            # Convert entry price to float and ensure it's a valid number
            entry_price = float(entry_price)
            if entry_price <= 0:
                raise ValueError("Entry price must be positive")
            
            # Calculate ATR
            atr = self.calculate_atr(symbol)
            if not atr:
                logger.warning(f"Cannot calculate ATR for {symbol}, using default take profit")
                # Default to 3% above entry
                return round(entry_price * 1.03, 4)
            
            # Convert ATR to float and validate
            atr = float(atr)
            if atr <= 0:
                logger.warning(f"Invalid ATR value {atr} for {symbol}, using default")
                atr = entry_price * 0.02  # Default to 2% of entry price
            
            # Calculate minimum take profit distance (ATR based)
            minimum_tp_distance = entry_price + (atr * self.multiplier)
            
            # If resistance level provided and valid, use it if higher than minimum
            if resistance_level:
                try:
                    resistance_level = float(resistance_level)
                    if resistance_level > minimum_tp_distance:
                        final_take_profit = resistance_level
                    else:
                        final_take_profit = minimum_tp_distance
                except (ValueError, TypeError):
                    final_take_profit = minimum_tp_distance
            else:
                final_take_profit = minimum_tp_distance
            
            # Ensure the take profit is not too far from entry price (max 10%)
            max_tp = entry_price * 1.10
            final_take_profit = min(final_take_profit, max_tp)
            
            # Format to 4 decimal places
            final_take_profit = round(final_take_profit, 4)
            
            logger.info(f"Calculated take profit for {symbol}: {final_take_profit} (Entry: {entry_price}, ATR: {atr})")
            return final_take_profit
            
        except Exception as e:
            logger.error(f"Error calculating take profit for {symbol}: {str(e)}")
            # Default to 3% above entry with 4 decimal places
            return round(float(entry_price) * 1.03, 4)
    
    def calculate_trailing_stop(self, symbol, current_price, current_stop_loss, highest_price=None):
        """
        Calculate trailing stop based on ATR and current price
        
        Args:
            symbol (str): Trading symbol
            current_price (float): Current market price
            current_stop_loss (float): Current stop loss level
            highest_price (float, optional): Highest price seen so far
            
        Returns:
            tuple: (new_stop_loss, new_highest_price)
        """
        try:
            # Normalize price if needed
            current_price = normalize_price(current_price, symbol)
            
            # Use current price as highest if none provided
            if highest_price is None:
                highest_price = current_price
            else:
                highest_price = normalize_price(highest_price, symbol)
            
            # If current price is higher than highest tracked price, update trailing stop
            if current_price > highest_price:
                # Calculate ATR
                atr = self.calculate_atr(symbol)
                
                # New stop loss based on current price and ATR
                new_stop_loss = current_price - (atr * self.multiplier)
                
                # Only move stop loss up, never down
                if new_stop_loss > current_stop_loss:
                    logger.info(f"Updating trailing stop for {symbol} from {current_stop_loss} to {new_stop_loss}")
                    return new_stop_loss, current_price
            
            # Return current values if no update
            return current_stop_loss, highest_price
            
        except Exception as e:
            logger.error(f"Error calculating trailing stop for {symbol}: {str(e)}")
            return current_stop_loss, highest_price 