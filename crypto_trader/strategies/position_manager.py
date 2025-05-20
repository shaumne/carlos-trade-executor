#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import threading
from datetime import datetime

from crypto_trader.config import config
from crypto_trader.utils import setup_logger, format_quantity
from crypto_trader.strategies.atr_strategy import ATRStrategy

logger = setup_logger("position_manager")

class Position:
    """Data class for representing a trading position"""
    
    def __init__(self, symbol, order_id, row_index, quantity=0, price=0, 
                 stop_loss=0, take_profit=0, status="ORDER_PLACED",
                 tp_order_id=None, sl_order_id=None):
        self.symbol = symbol
        self.order_id = order_id
        self.row_index = row_index
        self.quantity = quantity
        self.price = price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.highest_price = price  # For trailing stop loss
        self.status = status
        self.tp_order_id = tp_order_id  # Take profit order ID
        self.sl_order_id = sl_order_id  # Stop loss order ID
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        
    def update_tp_sl(self, take_profit=None, stop_loss=None):
        """Update take profit and stop loss levels"""
        if take_profit is not None:
            self.take_profit = take_profit
        
        if stop_loss is not None:
            self.stop_loss = stop_loss
            
        self.updated_at = datetime.now()
    
    def update_status(self, status):
        """Update position status"""
        self.status = status
        self.updated_at = datetime.now()

class PositionManager:
    """
    Manages trading positions with thread safety, monitoring, and trailing stops
    """
    
    def __init__(self, exchange_api, sheet_manager, telegram_notifier=None):
        """
        Initialize position manager
        
        Args:
            exchange_api: Exchange API instance
            sheet_manager: Sheet manager instance
            telegram_notifier: Telegram notifier instance (optional)
        """
        self.exchange_api = exchange_api
        self.sheet_manager = sheet_manager
        self.telegram_notifier = telegram_notifier
        self.positions = {}  # symbol -> Position
        self.positions_lock = threading.Lock()
        self.atr_strategy = ATRStrategy(exchange_api)
        self.last_check_time = time.time()
        self.check_interval = 60  # Check positions every 60 seconds
        self._stop_event = threading.Event()
        
        # Start background position monitoring thread
        self._monitoring_thread = threading.Thread(
            target=self.update_positions_periodically,
            daemon=True
        )
        self._monitoring_thread.start()
        logger.info("Position monitoring thread started")
        
    def get_position(self, symbol):
        """
        Get a position by symbol
        
        Args:
            symbol (str): Trading symbol
            
        Returns:
            Position: Position object or None if not found
        """
        with self.positions_lock:
            return self.positions.get(symbol)
    
    def has_active_position(self, symbol):
        """
        Check if there's an active position for a symbol
        
        Args:
            symbol (str): Trading symbol
            
        Returns:
            bool: True if position exists, False otherwise
        """
        with self.positions_lock:
            return symbol in self.positions
    
    def add_position(self, position):
        """
        Add a new position
        
        Args:
            position (Position): Position to add
            
        Returns:
            bool: True if added, False if position already exists
        """
        with self.positions_lock:
            if position.symbol in self.positions:
                logger.warning(f"Position already exists for {position.symbol}")
                return False
            
            self.positions[position.symbol] = position
            logger.info(f"Added position for {position.symbol}")
            return True
    
    def update_position(self, symbol, **kwargs):
        """
        Update position attributes
        
        Args:
            symbol (str): Trading symbol
            **kwargs: Attributes to update
            
        Returns:
            bool: True if updated, False if position not found
        """
        with self.positions_lock:
            if symbol not in self.positions:
                logger.warning(f"Cannot update: No position found for {symbol}")
                return False
            
            position = self.positions[symbol]
            
            # Update position attributes
            for key, value in kwargs.items():
                if hasattr(position, key):
                    setattr(position, key, value)
            
            position.updated_at = datetime.now()
            return True
    
    def remove_position(self, symbol):
        """
        Remove a position
        
        Args:
            symbol (str): Trading symbol
            
        Returns:
            Position: Removed position or None if not found
        """
        with self.positions_lock:
            if symbol not in self.positions:
                return None
            
            position = self.positions.pop(symbol)
            logger.info(f"Removed position for {symbol}")
            return position
    
    def execute_buy(self, signal):
        """
        Execute a buy order based on a signal
        
        Args:
            signal (dict): Buy signal data
            
        Returns:
            bool: True if successful, False otherwise
        """
        symbol = signal['symbol']
        row_index = signal['row_index']
        
        # Check if we already have an active position
        if self.has_active_position(symbol):
            logger.warning(f"Already have an active position for {symbol}, skipping buy")
            return False
        
        # Check if we have sufficient balance
        if not self.exchange_api.has_sufficient_balance():
            logger.error(f"Insufficient balance for trade {symbol}")
            self.sheet_manager.update_trade_status(row_index, "INSUFFICIENT_BALANCE")
            return False
        
        try:
            # Get current price
            current_price = self.exchange_api.get_current_price(symbol)
            if not current_price:
                logger.error(f"Could not get current price for {symbol}, skipping buy")
                return False
            
            # Calculate stop loss and take profit
            stop_loss = signal.get('stop_loss')
            take_profit = signal.get('take_profit')
            resistance_up = signal.get('resistance_up')
            resistance_down = signal.get('resistance_down')
            
            # If stop loss or take profit are not provided, calculate them
            if not stop_loss or stop_loss == 0:
                stop_loss = self.atr_strategy.calculate_stop_loss(
                    symbol, current_price, resistance_down
                )
            
            if not take_profit or take_profit == 0:
                take_profit = self.atr_strategy.calculate_take_profit(
                    symbol, current_price, resistance_up
                )
            
            # Execute buy order
            order_id = self.exchange_api.buy_coin(symbol)
            
            if not order_id:
                logger.error(f"Failed to create buy order for {symbol}")
                self.sheet_manager.update_trade_status(row_index, "ORDER_FAILED")
                return False
            
            # Estimate quantity based on trade amount
            estimated_quantity = config.TRADE_AMOUNT / current_price if current_price > 0 else 0
            
            # Update trade status in sheet
            self.sheet_manager.update_trade_status(
                row_index, 
                "ORDER_PLACED", 
                order_id, 
                purchase_price=current_price, 
                quantity=estimated_quantity,
                stop_loss=stop_loss,
                take_profit=take_profit
            )
            
            # Create position object
            position = Position(
                symbol=symbol,
                order_id=order_id,
                row_index=row_index,
                quantity=estimated_quantity,
                price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                status="ORDER_PLACED"
            )
            
            # Add to positions
            self.add_position(position)
            
            # Monitor the order
            is_filled = self._monitor_order(position)
            
            if is_filled:
                # Place TP/SL orders
                self._place_tp_sl_orders(position)
                
                # Send notification
                self._notify_order_filled(position)
            else:
                # Remove position if not filled
                self.remove_position(symbol)
                
            return is_filled
            
        except Exception as e:
            logger.error(f"Error executing buy for {symbol}: {str(e)}")
            self.sheet_manager.update_trade_status(row_index, "ERROR")
            return False
    
    def execute_sell(self, signal):
        """
        Execute a sell order based on a signal
        
        Args:
            signal (dict): Sell signal data
            
        Returns:
            bool: True if successful, False otherwise
        """
        symbol = signal['symbol']
        row_index = signal['row_index']
        original_symbol = signal['original_symbol']
        order_id_from_sheet = signal.get('order_id', '')
        
        try:
            # Check if we have this position in our tracking
            position = self.get_position(symbol)
            
            if not position:
                logger.info(f"No tracked position for {symbol}, checking balance")
                
                # Get balance from exchange
                base_currency = original_symbol
                balance = self.exchange_api.get_balance(base_currency)
                
                if balance <= 0:
                    logger.warning(f"No balance found for {base_currency}, cannot sell")
                    return False
                
                # Create temporary position for the sell
                position = Position(
                    symbol=symbol,
                    order_id=order_id_from_sheet or "manual",
                    row_index=row_index,
                    quantity=balance,
                    price=0,  # Unknown entry price
                    status="POSITION_ACTIVE"
                )
            
            # Cancel any TP/SL orders
            self._cancel_tp_sl_orders(position)
            
            # Execute sell order
            sell_order_id = self.exchange_api.sell_coin(symbol, position.quantity)
            
            if not sell_order_id:
                logger.error(f"Failed to create sell order for {symbol}")
                return False
            
            # Update sheet
            self.sheet_manager.update_trade_status(
                row_index,
                "SOLD",
                sell_price=self.exchange_api.get_current_price(symbol),
                quantity=position.quantity
            )
            
            # Move to archive
            self.sheet_manager.move_to_archive(row_index)
            
            # Send notification
            if self.telegram_notifier:
                self.telegram_notifier.send_message(
                    f"🔴 SELL Order placed:\n"
                    f"Symbol: {symbol}\n"
                    f"Quantity: {position.quantity}\n"
                    f"Order ID: {sell_order_id}"
                )
            
            # Remove position
            self.remove_position(symbol)
            
            return True
            
        except Exception as e:
            logger.error(f"Error executing sell for {symbol}: {str(e)}")
            return False
    
    def _monitor_order(self, position, max_checks=30, check_interval=5):
        """
        Monitor order until it's filled or timeout
        
        Args:
            position (Position): Position to monitor
            max_checks (int): Maximum number of status checks
            check_interval (float): Time between checks in seconds
            
        Returns:
            bool: True if order filled, False otherwise
        """
        order_id = position.order_id
        symbol = position.symbol
        checks = 0
        
        logger.info(f"Monitoring order {order_id} for {symbol}")
        
        while checks < max_checks:
            try:
                # Get order details
                method = "private/get-order-detail"
                params = {"order_id": order_id}
                order_detail = self.exchange_api.send_request(method, params)
                
                if not order_detail or order_detail.get("code") != 0:
                    logger.warning(f"Could not get details for order {order_id}")
                    time.sleep(check_interval)
                    checks += 1
                    continue
                
                result = order_detail.get("result", {})
                status = result.get("status")
                cumulative_quantity = float(result.get("cumulative_quantity", 0))
                avg_price = float(result.get("avg_price", 0))
                
                logger.debug(f"Order {order_id} status: {status}")
                
                # MARKET emirleri için özel kontrol
                # Eğer emir CANCELED ama bir miktar alım yapılmışsa, başarılı sayılır
                if status == "CANCELED" and cumulative_quantity > 0:
                    logger.info(f"Market order {order_id} executed with quantity {cumulative_quantity} before cancellation")
                    position.quantity = cumulative_quantity
                    position.price = avg_price
                    position.status = "POSITION_ACTIVE"
                    return True
                
                # Normal FILLED kontrolü
                elif status == "FILLED":
                    position.quantity = cumulative_quantity
                    position.price = avg_price
                    position.status = "POSITION_ACTIVE"
                    logger.info(f"Order {order_id} filled: {cumulative_quantity} @ {avg_price}")
                    return True
                
                # Gerçekten iptal edilmiş ve hiç işlem yapılmamış
                elif status == "CANCELED" and cumulative_quantity == 0:
                    if checks >= 2:  # En az 2 kontrol yap
                        logger.warning(f"Order {order_id} cancelled with no execution")
                        return False
                
                # Diğer durumlar için bekle
                else:
                    logger.debug(f"Order {order_id} status: {status}, waiting...")
                    time.sleep(check_interval)
                    checks += 1
                    continue
                
            except Exception as e:
                logger.error(f"Error checking order {order_id}: {str(e)}")
                time.sleep(check_interval)
                checks += 1
                continue
        
        logger.warning(f"Monitoring timed out for order {order_id}")
        return False
    
    def _place_tp_sl_orders(self, position):
        """
        Place take profit and stop loss orders
        
        Args:
            position (Position): Position to place orders for
            
        Returns:
            tuple: (tp_order_id, sl_order_id)
        """
        symbol = position.symbol
        quantity = position.quantity
        
        try:
            logger.info(f"Placing TP/SL orders for {symbol}: TP={position.take_profit}, SL={position.stop_loss}")
            
            # Format quantity
            formatted_quantity = format_quantity(quantity, symbol)
            
            # Check API for actual balance to be safe
            base_currency = symbol.split('_')[0]
            actual_balance = self.exchange_api.get_coin_balance(base_currency)
            
            if actual_balance:
                try:
                    actual_balance_float = float(actual_balance)
                    if actual_balance_float < quantity:
                        logger.warning(f"Actual balance ({actual_balance_float}) is less than expected quantity ({quantity})")
                        formatted_quantity = format_quantity(actual_balance_float * 0.99, symbol)
                        logger.info(f"Using 99% of actual balance: {formatted_quantity}")
                except Exception as e:
                    logger.error(f"Error converting balance to float: {str(e)}")
            
            # Update TP/SL values in Google Sheets
            self.sheet_manager.update_trade_status(
                position.row_index,
                "UPDATE_TP_SL",
                take_profit=position.take_profit,
                stop_loss=position.stop_loss
            )
            
            # NOTE: This method would be implemented differently depending on exchange API
            # For Crypto.com, we'll use limit orders for now (exchange may support TP/SL orders)
            tp_order_id = None
            sl_order_id = None
            
            # Store TP/SL order IDs
            position.tp_order_id = tp_order_id
            position.sl_order_id = sl_order_id
            
            # Send notification
            if self.telegram_notifier:
                self.telegram_notifier.send_message(
                    f"🟢 Position Active:\n"
                    f"Symbol: {symbol}\n"
                    f"Entry Price: {position.price}\n"
                    f"Quantity: {position.quantity}\n"
                    f"Take Profit: {position.take_profit}\n"
                    f"Stop Loss: {position.stop_loss}"
                )
            
            return tp_order_id, sl_order_id
            
        except Exception as e:
            logger.error(f"Error placing TP/SL orders for {symbol}: {str(e)}")
            return None, None
    
    def _cancel_tp_sl_orders(self, position):
        """
        Cancel take profit and stop loss orders
        
        Args:
            position (Position): Position to cancel orders for
            
        Returns:
            bool: True if successful, False otherwise
        """
        success = True
        
        # Cancel take profit order if exists
        if position.tp_order_id:
            try:
                cancelled = self.exchange_api.cancel_order(position.tp_order_id)
                if cancelled:
                    logger.info(f"Cancelled TP order {position.tp_order_id} for {position.symbol}")
                else:
                    logger.warning(f"Failed to cancel TP order {position.tp_order_id} for {position.symbol}")
                    success = False
            except Exception as e:
                logger.error(f"Error cancelling TP order: {str(e)}")
                success = False
        
        # Cancel stop loss order if exists
        if position.sl_order_id:
            try:
                cancelled = self.exchange_api.cancel_order(position.sl_order_id)
                if cancelled:
                    logger.info(f"Cancelled SL order {position.sl_order_id} for {position.symbol}")
                else:
                    logger.warning(f"Failed to cancel SL order {position.sl_order_id} for {position.symbol}")
                    success = False
            except Exception as e:
                logger.error(f"Error cancelling SL order: {str(e)}")
                success = False
        
        return success
    
    def check_positions(self):
        """
        Check all active positions for take profit or stop loss conditions
        
        Returns:
            int: Number of positions checked
        """
        symbols_to_check = []
        
        # Get a thread-safe copy of symbols to check
        with self.positions_lock:
            symbols_to_check = list(self.positions.keys())
        
        count = 0
        
        # Check each position
        for symbol in symbols_to_check:
            position = self.get_position(symbol)
            
            if not position or position.status != "POSITION_ACTIVE":
                continue
                
            try:
                # Get current price
                current_price = self.exchange_api.get_current_price(symbol)
                
                if not current_price:
                    logger.warning(f"Could not get current price for {symbol}")
                    continue
                
                # Update trailing stop if needed
                new_stop_loss, new_highest_price = self.atr_strategy.calculate_trailing_stop(
                    symbol, current_price, position.stop_loss, position.highest_price
                )
                
                # If stop loss updated, update position and sheet
                if new_stop_loss != position.stop_loss:
                    self.update_position(
                        symbol, 
                        stop_loss=new_stop_loss, 
                        highest_price=new_highest_price
                    )
                    
                    # Update sheet
                    self.sheet_manager.update_trade_status(
                        position.row_index,
                        "UPDATE_TP_SL",
                        stop_loss=new_stop_loss,
                        take_profit=position.take_profit
                    )
                    
                    logger.info(f"Updated trailing stop for {symbol}: {new_stop_loss}")
                
                # Check for stop loss hit
                if current_price <= position.stop_loss:
                    logger.info(f"Stop loss triggered for {symbol} at {current_price}")
                    self.execute_sell({"symbol": symbol, "action": "SELL", "row_index": position.row_index, "original_symbol": symbol.split('_')[0]})
                
                # Check for take profit hit
                elif current_price >= position.take_profit:
                    logger.info(f"Take profit triggered for {symbol} at {current_price}")
                    self.execute_sell({"symbol": symbol, "action": "SELL", "row_index": position.row_index, "original_symbol": symbol.split('_')[0]})
                
                count += 1
                
            except Exception as e:
                logger.error(f"Error checking position for {symbol}: {str(e)}")
        
        return count
    
    def _notify_order_filled(self, position):
        """
        Send notification for filled order
        
        Args:
            position (Position): Position with filled order
        """
        if not self.telegram_notifier:
            return
            
        self.telegram_notifier.send_message(
            f"🟢 BUY Order Filled!\n"
            f"Symbol: {position.symbol}\n"
            f"Entry Price: {position.price}\n"
            f"Quantity: {position.quantity}\n"
            f"Take Profit: {position.take_profit}\n"
            f"Stop Loss: {position.stop_loss}\n"
            f"Order ID: {position.order_id}"
        )
    
    def update_position_status(self):
        """
        Update status of all open positions by checking related orders
        
        Returns:
            int: Number of positions that were closed
        """
        closed_count = 0
        current_time = time.time()
        
        # Only check every check_interval seconds
        if current_time - self.last_check_time < self.check_interval:
            return 0
            
        self.last_check_time = current_time
        
        logger.debug("Checking open position statuses...")
        
        # Get a copy of the positions to avoid modification during iteration
        with self.positions_lock:
            positions_to_check = {symbol: pos for symbol, pos in self.positions.items() if pos.is_open}
        
        # For each open position
        for symbol, position in positions_to_check.items():
            # Skip closed positions
            if not position.is_open:
                continue
                
            # Check if TP or SL order was filled
            tp_filled = False
            sl_filled = False
            
            # Check TP order if exists
            if position.tp_order_id:
                tp_status = self.exchange_api.get_order_status(position.tp_order_id)
                if tp_status == "FILLED":
                    tp_filled = True
                    logger.info(f"TP order {position.tp_order_id} for {position.symbol} was filled!")
            
            # Check SL order if exists
            if position.sl_order_id:
                sl_status = self.exchange_api.get_order_status(position.sl_order_id)
                if sl_status == "FILLED":
                    sl_filled = True
                    logger.info(f"SL order {position.sl_order_id} for {position.symbol} was filled!")
            
            # If either TP or SL was filled, close position and cancel other orders
            if tp_filled or sl_filled:
                # Get current price for PnL calculation
                current_price = self.exchange_api.get_current_price(position.symbol)
                
                with self.positions_lock:
                    # Mark position as closed
                    position.is_open = False
                    position.exit_time = datetime.now().isoformat()
                    position.exit_price = current_price
                    
                    # Set exit type
                    if tp_filled:
                        position.exit_type = "tp"
                        # Cancel SL order if exists
                        if position.sl_order_id:
                            logger.info(f"TP hit, cancelling SL order {position.sl_order_id}")
                            self.exchange_api.cancel_order(position.sl_order_id)
                            position.sl_order_id = None
                    elif sl_filled:
                        position.exit_type = "sl"
                        # Cancel TP order if exists
                        if position.tp_order_id:
                            logger.info(f"SL hit, cancelling TP order {position.tp_order_id}")
                            self.exchange_api.cancel_order(position.tp_order_id)
                            position.tp_order_id = None
                    
                    # Calculate PnL if price is available
                    if position.exit_price and position.entry_price:
                        price_diff = position.exit_price - position.entry_price
                        position.pnl = price_diff * position.quantity
                        
                        logger.info(f"Position closed: {position.symbol} - PnL: {position.pnl}")
                    
                    # Update sheet status
                    row_index = self._get_row_index_for_symbol(position.symbol)
                    if row_index:
                        exit_type = "TAKE_PROFIT" if tp_filled else "STOP_LOSS"
                        self.sheet_manager.update_trade_status(
                            row_index,
                            exit_type,
                            position.exit_price,
                            pnl=position.pnl
                        )
                
                # Send notification
                if self.telegram_notifier:
                    exit_type = "Take Profit ✅" if tp_filled else "Stop Loss 🔴"
                    self.telegram_notifier.send_message(
                        f"{exit_type} triggered for {position.symbol}\n"
                        f"Exit Price: {position.exit_price}\n"
                        f"PnL: {position.pnl:.2f} USD"
                    )
                
                closed_count += 1
        
        if closed_count > 0:
            logger.info(f"Closed {closed_count} positions during status update")
        
        return closed_count
    
    def update_positions_periodically(self):
        """
        Background thread to periodically check position status
        and handle TP/SL order completion
        """
        logger.info("Starting periodic position status monitoring")
        
        try:
            while not self._stop_event.is_set():
                try:
                    # Update position statuses
                    closed_count = self.update_position_status()
                    
                    # If any positions were closed, run check_positions immediately
                    if closed_count > 0:
                        self.check_positions()
                    
                    # Sleep before next check (5 minutes)
                    for _ in range(30):  # 30 x 10 = 300 seconds = 5 minutes
                        if self._stop_event.is_set():
                            break
                        time.sleep(10)
                        
                except Exception as e:
                    logger.error(f"Error in position monitoring thread: {e}")
                    time.sleep(60)  # Wait a minute before retrying
        except Exception as e:
            logger.exception(f"Fatal error in position monitoring thread: {e}")
        
        logger.info("Position monitoring thread stopped")
    
    def _get_row_index_for_symbol(self, symbol):
        """Helper to get row index for a symbol from sheet data"""
        try:
            sheet_data = self.sheet_manager.get_all_records()
            for i, record in enumerate(sheet_data):
                if record.get('symbol') == symbol:
                    return i + 2  # +2 because sheet is 1-indexed and we have a header row
        except:
            pass
        return None
    
    def close(self):
        """Properly clean up resources"""
        logger.info("Shutting down position manager...")
        self._stop_event.set()
        if self._monitoring_thread and self._monitoring_thread.is_alive():
            self._monitoring_thread.join(timeout=5.0)
        logger.info("Position manager shutdown complete") 