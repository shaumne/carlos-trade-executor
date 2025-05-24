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
import asyncio
import signal

from crypto_trader.trade_executor import main as executor_main

# Store active clients for cleanup
active_clients = set()

def register_client(client):
    active_clients.add(client)
    
def unregister_client(client):
    active_clients.discard(client)

async def cleanup():
    """Clean up all active client sessions"""
    cleanup_tasks = []
    for client in active_clients:
        if hasattr(client, 'close'):
            cleanup_tasks.append(client.close())
    if cleanup_tasks:
        await asyncio.gather(*cleanup_tasks, return_exceptions=True)

def signal_handler(sig, frame):
    """Handle shutdown signals"""
    print("\nShutting down gracefully...")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(cleanup())
    sys.exit(0)

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
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Parse command line arguments
        args = parse_args()
        
        # Set log level
        os.environ["LOG_LEVEL"] = args.log_level
        
        # Run the executor
        loop = asyncio.get_event_loop()
        loop.run_until_complete(executor_main())
    except Exception as e:
        print(f"Error in main: {e}")
    finally:
        # Ensure cleanup runs
        loop.run_until_complete(cleanup())
        loop.close()

if __name__ == "__main__":
    main() 