#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Crypto Trader Bot - Main entry point

This is the main entry point for the Crypto Trader Bot.
It provides a command line interface to start the trading bot.

Usage:
    python main.py [--log-level LEVEL]

Options:
    --log-level LEVEL    Set logging level (DEBUG, INFO, WARNING, ERROR) [default: INFO]
"""

import os
import sys
import argparse
import logging

from crypto_trader.trade_executor import main as executor_main

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="Crypto Trader Bot")
    parser.add_argument(
        "--log-level", 
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set logging level"
    )
    return parser.parse_args()

def main():
    """Main entry point"""
    # Parse command line arguments
    args = parse_args()
    
    # Set log level
    os.environ["LOG_LEVEL"] = args.log_level
    
    # Run the executor
    executor_main()

if __name__ == "__main__":
    main() 