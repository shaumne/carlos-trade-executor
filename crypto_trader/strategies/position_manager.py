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
        self.is_open = True  # Position is open by default when created
        self.exit_price = None
        self.exit_time = None
        self.exit_type = None  # 'tp', 'sl', or 'manual'
        self.pnl = None  # Realized profit/loss
        
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
        
        # If status indicates position is closed, update is_open
        if status in ["SOLD", "CLOSED", "CANCELLED"]:
            self.is_open = False
    
    def close_position(self, exit_price, exit_type="manual"):
        """Close the position with exit details"""
        self.is_open = False
        self.exit_price = exit_price
        self.exit_time = datetime.now()
        self.exit_type = exit_type
        self.status = "SOLD"
        
        # Calculate PnL if we have entry and exit prices
        if self.price and exit_price and self.quantity:
            self.pnl = (exit_price - self.price) * self.quantity
        
        self.updated_at = datetime.now()
    
    @property
    def duration(self):
        """Get position duration in seconds"""
        if self.exit_time:
            return (self.exit_time - self.created_at).total_seconds()
        return (datetime.now() - self.created_at).total_seconds()
    
    def __str__(self):
        """String representation of the position"""
        return (f"Position({self.symbol}, {self.status}, "
                f"qty={self.quantity}, price={self.price}, "
                f"tp={self.take_profit}, sl={self.stop_loss}, "
                f"is_open={self.is_open})")

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
        """Execute a buy trade based on the signal"""
        try:
            symbol = signal['symbol']
            row_index = signal['row_index']
            take_profit = float(signal['take_profit'])
            stop_loss = float(signal['stop_loss'])
            
            # Check if we already have a position
            if self.has_active_position(symbol):
                logger.warning(f"Already have an active position for {symbol}, skipping buy")
                return False
            
            # Check if we have sufficient balance
            if not self.exchange_api.has_sufficient_balance():
                logger.error(f"Insufficient balance for trade {symbol}")
                self.sheet_manager.update_trade_status(row_index, "INSUFFICIENT_BALANCE")
                return False
            
            try:
                # Get current price from API
                current_price = self.exchange_api.get_current_price(symbol)
                if not current_price:
                    logger.error(f"Could not get current price for {symbol}, skipping buy")
                    return False
                
                # Use trade amount in USDT
                trade_amount = self.exchange_api.trade_amount
                logger.info(f"Placing market buy order for {symbol} with ${trade_amount} USDT")
                
                # Create market buy order
                order_id = self.exchange_api.buy_coin(symbol, trade_amount)
                
                if not order_id:
                    logger.error(f"Failed to create buy order for {symbol}")
                    self.sheet_manager.update_trade_status(row_index, "ORDER_FAILED")
                    return False
                
                # Estimate initial quantity (will be updated with actual quantity)
                estimated_quantity = trade_amount / current_price if current_price > 0 else 0
                logger.info(f"Estimated quantity: {estimated_quantity} (${trade_amount} / {current_price})")
                
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
                
                # Add to position manager
                self.add_position(position)
                
                # Update sheet with initial order info
                self.sheet_manager.update_trade_status(
                    row_index,
                    "ORDER_PLACED",
                    order_id,
                    purchase_price=current_price,
                    quantity=estimated_quantity,
                    stop_loss=stop_loss,
                    take_profit=take_profit
                )
                
                # IMPORTANT: Wait for buy order to be filled before placing TP/SL orders
                logger.info(f"Waiting for BUY order {order_id} to be filled before placing TP/SL orders")
                is_filled = self._monitor_order(position)
                
                if is_filled:
                    # Get actual quantity and price from filled order
                    order_details = self.exchange_api.get_order_details(order_id)
                    if order_details:
                        actual_quantity = float(order_details.get('cumulative_quantity', estimated_quantity))
                        actual_price = float(order_details.get('avg_price', current_price))
                        
                        # Update position with actual values
                        position.quantity = actual_quantity
                        position.price = actual_price
                        position.status = "POSITION_ACTIVE"
                        
                        logger.info(f"BUY order filled! Using actual quantity ({actual_quantity}) for TP/SL orders")
                        
                        # Place TP/SL orders with actual quantity
                        tp_order_id, sl_order_id = self._place_tp_sl_orders(
                            position,
                            take_profit,
                            stop_loss
                        )
                        
                        if tp_order_id or sl_order_id:
                            position.tp_order_id = tp_order_id
                            position.sl_order_id = sl_order_id
                            logger.info(f"TP/SL orders created for {symbol}: TP={tp_order_id}, SL={sl_order_id}")
                            
                            # Update sheet with TP/SL order IDs
                            notes = f"TP Order: {tp_order_id or 'Failed'}, SL Order: {sl_order_id or 'Failed'}"
                            self.sheet_manager.update_cell(row_index, "Notes", notes)
                            
                            # Send detailed notification
                            if self.telegram_notifier:
                                self.telegram_notifier.send_message(
                                    f"🟢 BUY Order Filled!\n"
                                    f"Symbol: {symbol}\n"
                                    f"Entry Price: {actual_price}\n"
                                    f"Quantity: {actual_quantity}\n"
                                    f"TP: {take_profit}\n"
                                    f"SL: {stop_loss}\n"
                                    f"TP Order ID: {tp_order_id or 'N/A'}\n"
                                    f"SL Order ID: {sl_order_id or 'N/A'}\n"
                                    f"Main Order ID: {order_id}"
                                )
                    else:
                        logger.warning(f"Could not get order details for {order_id}")
                        
                    return True
                else:
                    logger.warning(f"BUY order was not filled, cannot place TP/SL orders")
                    # Remove position if not filled
                    self.remove_position(symbol)
                    return False
                    
            except Exception as e:
                logger.error(f"Error executing buy trade for {symbol}: {str(e)}")
                self.sheet_manager.update_trade_status(row_index, "ERROR")
                return False
                
        except Exception as e:
            logger.error(f"Error in execute_buy: {str(e)}")
            return False
    
    def execute_sell(self, signal):
        """Execute a sell trade based on the signal"""
        try:
            symbol = signal['symbol']
            row_index = signal['row_index']
            current_price = float(signal.get('last_price', 0))
            
            # Get position details
            position = self.get_position(symbol)
            if not position:
                # Try to get quantity from balance if no position found
                base_currency = symbol.split('_')[0]
                try:
                    balance = self.exchange_api.get_coin_balance(base_currency)
                    if balance and float(balance) > 0:
                        quantity = float(balance)
                        logger.info(f"No position found but got balance of {quantity} {base_currency}")
                        
                        # Create temporary position object
                        position = Position(
                            symbol=symbol,
                            order_id='manual',
                            row_index=row_index,
                            quantity=quantity,
                            status="POSITION_ACTIVE"
                        )
                    else:
                        logger.warning(f"No position or balance found for {symbol}")
                        return False
                except Exception as e:
                    logger.error(f"Error getting balance for {base_currency}: {str(e)}")
                    return False
            
            # Cancel any existing TP/SL orders
            if position.tp_order_id or position.sl_order_id:
                self._cancel_tp_sl_orders(position)
            
            # Get current price if not provided
            if current_price <= 0:
                current_price = self.exchange_api.get_current_price(symbol)
                if not current_price:
                    logger.error(f"Could not get current price for {symbol}")
                    return False
            
            # Execute sell order
            logger.info(f"Selling {position.quantity} {symbol} at {current_price}")
            sell_order_id = self.exchange_api.sell_coin(symbol, position.quantity)
            
            if not sell_order_id:
                logger.error(f"Failed to create sell order for {symbol}")
                return False
            
            # Monitor the sell order
            is_filled = self._monitor_order(position, order_id=sell_order_id)
            
            if is_filled:
                # Get actual sell details
                sell_details = self.exchange_api.get_order_details(sell_order_id)
                if sell_details:
                    actual_sell_price = float(sell_details.get('avg_price', current_price))
                    actual_sell_quantity = float(sell_details.get('cumulative_quantity', position.quantity))
                else:
                    actual_sell_price = current_price
                    actual_sell_quantity = position.quantity
                
                # Update sheet with sell information
                self.sheet_manager.update_trade_status(
                    row_index,
                    "SOLD",
                    sell_price=actual_sell_price,
                    quantity=actual_sell_quantity,
                    sell_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                
                # Move to archive and clean up the coin line
                self.sheet_manager.move_to_archive(row_index)
                
                # Clean up the coin line in the main sheet
                self.sheet_manager.clean_coin_line(row_index)
                
                # Send notification
                if self.telegram_notifier:
                    entry_price = position.price
                    profit_loss = ((actual_sell_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
                    
                    self.telegram_notifier.send_message(
                        f"🔴 SELL Order Filled!\n"
                        f"Symbol: {symbol}\n"
                        f"Sell Price: {actual_sell_price}\n"
                        f"Quantity: {actual_sell_quantity}\n"
                        f"P/L: {profit_loss:.2f}%\n"
                        f"Order ID: {sell_order_id}"
                    )
                
                # Remove position
                self.remove_position(symbol)
                logger.info(f"Successfully sold {symbol}")
                return True
            else:
                logger.warning(f"Sell order was not filled for {symbol}")
                return False
                
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
    
    def _place_tp_sl_orders(self, position, take_profit, stop_loss):
        """
        Place TP and SL orders for a position using proper order types
        
        Args:
            position (Position): Position object
            take_profit (float): Take profit price
            stop_loss (float): Stop loss price
            
        Returns:
            tuple: (tp_order_id, sl_order_id) or (None, None) if failed
        """
        try:
            symbol = position.symbol
            quantity = position.quantity
            
            if quantity <= 0:
                logger.error(f"Invalid quantity for {symbol}: {quantity}")
                return None, None
            
            # Get base currency
            base_currency = symbol.split('_')[0]
            
            # Verify actual balance
            actual_balance = self.exchange_api.get_coin_balance(base_currency)
            if actual_balance:
                try:
                    actual_balance_float = float(actual_balance)
                    if actual_balance_float < quantity:
                        logger.warning(f"Actual balance ({actual_balance_float}) is less than expected quantity ({quantity}). Using actual balance.")
                        quantity = actual_balance_float * 0.99  # Use 99% of balance
                except Exception as e:
                    logger.error(f"Error converting balance to float: {str(e)}")
            
            # Format quantity based on coin type
            if base_currency == "SUI":
                # Use decimal format for SUI
                formatted_quantity = "{:.2f}".format(quantity).rstrip('0').rstrip('.')
                if float(formatted_quantity) == 0:
                    formatted_quantity = "{:.2f}".format(quantity)  # Keep all decimals
                logger.info(f"Using decimal format for SUI: {formatted_quantity}")
            elif base_currency in ["BONK", "SHIB", "DOGE", "PEPE"]:
                # For meme coins, use integer for large amounts, decimal for small
                if quantity > 1:
                    formatted_quantity = "{:.2f}".format(quantity)
                else:
                    formatted_quantity = "{:.2f}".format(quantity)
                logger.info(f"Using adaptive format for meme coin {base_currency}: {formatted_quantity}")
            elif base_currency in ["BTC", "ETH", "SOL"]:
                # Use 2 decimals for major coins
                formatted_quantity = "{:.2f}".format(quantity)
                logger.info(f"Using 2 decimal places for {base_currency}: {formatted_quantity}")
            else:
                # Default to 2 decimal format
                formatted_quantity = "{:.2f}".format(quantity)
                logger.info(f"Using 2 decimal format for {base_currency}: {formatted_quantity}")
            
            # Verify formatted quantity
            if float(formatted_quantity) <= 0:
                logger.error(f"Invalid formatted quantity: {formatted_quantity} for {symbol}")
                return None, None
            
            tp_order_id = None
            sl_order_id = None
            
            try:
                # Place Take Profit order with proper TAKE_PROFIT type
                tp_params = {
                    "instrument_name": symbol,
                    "side": "SELL",
                    "type": "TAKE_PROFIT_LIMIT",  # Using TAKE_PROFIT_LIMIT type
                    "price": "{:.2f}".format(take_profit),
                    "quantity": formatted_quantity,
                    "trigger_price": "{:.2f}".format(take_profit),  # Using trigger_price instead of ref_price
                    "trigger_price_type": "MARK_PRICE"  # Using trigger_price_type
                }
                
                tp_response = self.exchange_api.send_request("private/create-order", tp_params)
                
                if tp_response and tp_response.get("code") == 0:
                    tp_order_id = tp_response["result"]["order_id"]
                    logger.info(f"Successfully placed TP order for {symbol} at {take_profit}, order ID: {tp_order_id}")
                else:
                    logger.error(f"Failed to place TP order: {tp_response}")
                    
                    # Try with regular TAKE_PROFIT type
                    logger.info(f"Trying with regular TAKE_PROFIT type")
                    tp_params["type"] = "TAKE_PROFIT"
                    
                    tp_retry_response = self.exchange_api.send_request("private/create-order", tp_params)
                    
                    if tp_retry_response and tp_retry_response.get("code") == 0:
                        tp_order_id = tp_retry_response["result"]["order_id"]
                        logger.info(f"Successfully placed TP order with TAKE_PROFIT type, order ID: {tp_order_id}")
                
                # Place Stop Loss order with proper STOP_LOSS type
                sl_params = {
                    "instrument_name": symbol,
                    "side": "SELL",
                    "type": "STOP_LOSS_LIMIT",  # Using STOP_LOSS_LIMIT type
                    "price": "{:.2f}".format(stop_loss),
                    "quantity": formatted_quantity,
                    "trigger_price": "{:.2f}".format(stop_loss),  # Using trigger_price instead of ref_price
                    "trigger_price_type": "MARK_PRICE"  # Using trigger_price_type
                }
                
                sl_response = self.exchange_api.send_request("private/create-order", sl_params)
                
                if sl_response and sl_response.get("code") == 0:
                    sl_order_id = sl_response["result"]["order_id"]
                    logger.info(f"Successfully placed SL order for {symbol} at {stop_loss}, order ID: {sl_order_id}")
                else:
                    logger.error(f"Failed to place SL order: {sl_response}")
                    
                    # Try with regular STOP_LOSS type
                    logger.info(f"Trying with regular STOP_LOSS type")
                    sl_params["type"] = "STOP_LOSS"
                    
                    sl_retry_response = self.exchange_api.send_request("private/create-order", sl_params)
                    
                    if sl_retry_response and sl_retry_response.get("code") == 0:
                        sl_order_id = sl_retry_response["result"]["order_id"]
                        logger.info(f"Successfully placed SL order with STOP_LOSS type, order ID: {sl_order_id}")
                
                return tp_order_id, sl_order_id
                
            except Exception as e:
                logger.error(f"Error placing TP/SL orders for {symbol}: {str(e)}")
                return None, None
                
        except Exception as e:
            logger.error(f"Error in _place_tp_sl_orders for {symbol}: {str(e)}")
            return None, None
            
    def _cancel_tp_sl_orders(self, position):
        """
        Cancel existing TP/SL orders for a position
        
        Args:
            position (Position): Position object
            
        Returns:
            bool: True if successful, False otherwise
        """
        success = True
        
        try:
            # Cancel stop loss order if exists
            if position.sl_order_id:
                if self.exchange_api.cancel_order(position.sl_order_id):
                    logger.info(f"Successfully cancelled stop loss order {position.sl_order_id}")
                    position.sl_order_id = None
                else:
                    logger.error(f"Failed to cancel stop loss order {position.sl_order_id}")
                    success = False
            
            # Cancel take profit order if exists
            if position.tp_order_id:
                if self.exchange_api.cancel_order(position.tp_order_id):
                    logger.info(f"Successfully cancelled take profit order {position.tp_order_id}")
                    position.tp_order_id = None
                else:
                    logger.error(f"Failed to cancel take profit order {position.tp_order_id}")
                    success = False
            
            # Wait a moment after cancelling orders
            time.sleep(1)
            
            return success
            
        except Exception as e:
            logger.exception(f"Error cancelling TP/SL orders: {str(e)}")
            return False
    
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