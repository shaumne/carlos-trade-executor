#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from crypto_trader.config import config
from crypto_trader.utils.logger import setup_logger

logger = setup_logger("price_utils")

def normalize_price(price, symbol):
    """
    Normalize price values for coins that have decimal place issues
    
    Args:
        price (float): The price to normalize
        symbol (str): Trading symbol (e.g. BTC_USDT)
        
    Returns:
        float: Normalized price
    """
    # Extract the base currency from symbol
    base_currency = symbol.split('_')[0]
    
    # Check if this coin needs normalization
    if base_currency in config.NORMALIZATION_COINS:
        original_price = price
        
        # Apply normalization if price is too high
        if price > config.NORMALIZATION_THRESHOLD_LOW:
            if price > config.NORMALIZATION_THRESHOLD_HIGH:
                price = price / config.NORMALIZATION_DIVISOR_HIGH
            else:
                price = price / config.NORMALIZATION_DIVISOR_LOW
                
            logger.info(f"Normalized price for {symbol} from {original_price} to {price}")
            
    return price

def format_quantity(quantity, symbol):
    """
    Format quantity based on coin requirements
    
    Args:
        quantity (float): The quantity to format
        symbol (str): Trading symbol (e.g. BTC_USDT)
        
    Returns:
        str: Formatted quantity string suitable for trading
    """
    # Extract the base currency from symbol
    base_currency = symbol.split('_')[0]
    
    # Format based on coin type
    if base_currency in config.INTEGER_COINS:
        if quantity > 1:
            # Use integer format for quantities > 1
            formatted_quantity = str(int(quantity))
        else:
            # For small values, keep decimals but prevent scientific notation
            formatted_quantity = "{:.8f}".format(quantity).rstrip('0').rstrip('.')
    else:
        # Use precision from config or default
        precision = config.DECIMAL_COINS.get(base_currency, config.DEFAULT_PRECISION)
        formatted_quantity = ("{:." + str(precision) + "f}").format(quantity).rstrip('0').rstrip('.')
        
        # Ensure we don't have empty string after stripping
        if not formatted_quantity:
            formatted_quantity = "0"
    
    logger.debug(f"Formatted quantity for {symbol}: {formatted_quantity} (original: {quantity})")
    return formatted_quantity

def parse_number(value_str):
    """
    Parse number strings correctly handling international formats
    
    Args:
        value_str: String representation of a number
        
    Returns:
        float: Parsed number
    """
    try:
        if not value_str or str(value_str).strip() == '':
            return 0.0
            
        # Clean and normalize
        value_str = str(value_str).strip().replace(' ', '')
        
        # Handle Turkish/European format: comma as decimal separator
        if ',' in value_str:
            # Replace dots (thousand separator) and replace comma with dot
            value_str = value_str.replace('.', '').replace(',', '.')
        
        # Convert to float
        value = float(value_str)
        
        # Check for potential format errors - e.g., 3,62 read as 362
        if value > 100 and ',' in str(value_str):
            # Original value was probably something like 3,62, fix it
            return value / 10.0
            
        return value
        
    except Exception as e:
        logger.error(f"Error parsing number '{value_str}': {str(e)}")
        return 0.0 