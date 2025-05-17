#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import functools
from crypto_trader.config import config
from crypto_trader.utils.logger import setup_logger

logger = setup_logger("retry")

def retry(max_retries=None, retry_delay=None, exceptions=(Exception,), 
          on_retry=None, retry_condition=None):
    """
    Retry decorator to retry function calls that raise exceptions
    
    Args:
        max_retries (int): Maximum number of retries, defaults to config.MAX_RETRIES
        retry_delay (float): Delay between retries in seconds, defaults to config.RETRY_DELAY
        exceptions (tuple): Tuple of exceptions to catch and retry on
        on_retry (callable): Function to call when retrying, takes (exception, retry_count) as args
        retry_condition (callable): Function that returns True if we should retry (takes exception as arg)
        
    Returns:
        decorator: The retry decorator
    """
    max_retries = max_retries if max_retries is not None else config.MAX_RETRIES
    retry_delay = retry_delay if retry_delay is not None else config.RETRY_DELAY
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retry_count = 0
            last_exception = None
            
            while retry_count <= max_retries:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    # Check if we should retry
                    if retry_condition and not retry_condition(e):
                        logger.debug(f"Not retrying {func.__name__} due to condition")
                        raise e
                    
                    retry_count += 1
                    
                    if retry_count <= max_retries:
                        # Calculate delay with exponential backoff
                        delay = retry_delay * (2 ** (retry_count - 1))
                        
                        logger.warning(
                            f"Retry {retry_count}/{max_retries} for {func.__name__}: {str(e)}. "
                            f"Retrying in {delay:.2f}s"
                        )
                        
                        # Execute on_retry callback if provided
                        if on_retry:
                            on_retry(e, retry_count)
                            
                        # Wait before retrying
                        time.sleep(delay)
                    else:
                        logger.error(f"Max retries ({max_retries}) exceeded for {func.__name__}")
                        raise last_exception
            
            # This should not be reached
            raise last_exception
            
        return wrapper
        
    return decorator

# Example usage:
# @retry(max_retries=3, retry_delay=1.0)
# def api_call():
#     # Some code that might raise an exception
#     pass 