#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import sys
from crypto_trader.config import config

def setup_logger(name="crypto_trader", log_file=None):
    """
    Configure and return a logger instance with proper formatting
    
    Args:
        name (str): Logger name
        log_file (str): Path to log file, if None uses default from config
        
    Returns:
        logging.Logger: Configured logger instance
    """
    if log_file is None:
        log_file = config.LOG_FILE
        
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, config.LOG_LEVEL))
    
    # Create handlers
    handlers = [
        logging.StreamHandler(sys.stdout)  # Console handler
    ]
    
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Configure handlers
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger 