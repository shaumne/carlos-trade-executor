#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import gspread
import threading
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials

from crypto_trader.config import config
from crypto_trader.utils import setup_logger, retry, parse_number

logger = setup_logger("google_sheet_manager")

class GoogleSheetManager:
    """
    Handles interactions with Google Sheets with proper error handling and batch operations
    """
    
    def __init__(self, sheet_id=None, credentials_file=None,
                 worksheet_name=None, archive_worksheet_name=None):
        """
        Initialize Google Sheets manager
        
        Args:
            sheet_id (str, optional): Google Sheet ID
            credentials_file (str, optional): Path to credentials file
            worksheet_name (str, optional): Name of the main worksheet
            archive_worksheet_name (str, optional): Name of the archive worksheet
        """
        self.sheet_id = sheet_id or config.GOOGLE_SHEET_ID
        self.credentials_file = credentials_file or config.GOOGLE_CREDENTIALS_FILE
        self.worksheet_name = worksheet_name or config.GOOGLE_WORKSHEET_NAME
        self.archive_worksheet_name = archive_worksheet_name or config.ARCHIVE_WORKSHEET_NAME
        
        self.client = None
        self.sheet = None
        self.worksheet = None
        self.archive_worksheet = None
        
        self._headers = None
        self._headers_lock = threading.Lock()
        
        # Connect to Google Sheets
        self._connect_to_sheets()
        
    @retry(max_retries=3, retry_delay=2.0, 
           exceptions=(gspread.exceptions.APIError,), 
           retry_condition=lambda e: e.response.status_code == 429)
    def _connect_to_sheets(self):
        """
        Connect to Google Sheets API with retry mechanism
        """
        # Define scope for Google Sheets API
        scope = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ]
        
        # Authenticate with Google
        try:
            credentials = ServiceAccountCredentials.from_json_keyfile_name(
                self.credentials_file, scope
            )
            
            self.client = gspread.authorize(credentials)
            self.sheet = self.client.open_by_key(self.sheet_id)
            
            logger.info(f"Connected to Google Sheet: {self.sheet.title}")
            
            # Get or create worksheets
            self._setup_worksheets()
            
            # Ensure required columns exist
            self._ensure_required_columns()
            
            # Cache headers
            self._cache_headers()
            
        except Exception as e:
            logger.error(f"Failed to connect to Google Sheets: {str(e)}")
            raise
    
    def _setup_worksheets(self):
        """
        Setup main and archive worksheets
        """
        try:
            # Get main worksheet
            try:
                self.worksheet = self.sheet.worksheet(self.worksheet_name)
                logger.info(f"Found main worksheet: {self.worksheet_name}")
            except gspread.exceptions.WorksheetNotFound:
                logger.warning(f"Main worksheet '{self.worksheet_name}' not found, using first worksheet")
                self.worksheet = self.sheet.get_worksheet(0)
                self.worksheet_name = self.worksheet.title
                logger.info(f"Using worksheet: {self.worksheet_name}")
                
            # Get or create archive worksheet
            try:
                self.archive_worksheet = self.sheet.worksheet(self.archive_worksheet_name)
                logger.info(f"Found archive worksheet: {self.archive_worksheet_name}")
            except gspread.exceptions.WorksheetNotFound:
                logger.info(f"Creating archive worksheet: {self.archive_worksheet_name}")
                # Create archive worksheet
                self.archive_worksheet = self.sheet.add_worksheet(
                    title=self.archive_worksheet_name,
                    rows=1000,
                    cols=25  # Increased number of columns
                )
                
                # Set archive headers
                archive_headers = [
                    "TRADE", "Coin", "Last Price", "Buy Target", "Buy Recommendation",
                    "Sell Target", "Stop-Loss", "Order Placed?", "Order Place Date",
                    "Order PURCHASE Price", "Order PURCHASE Quantity", "Order PURCHASE Date",
                    "Order SOLD", "SOLD Price", "SOLD Quantity", "SOLD Date", "Notes",
                    "RSI", "Method", "Resistance Up", "Resistance Down", "Last Updated",
                    "RSI Sparkline", "RSI DATA", "Return %"  # Added Return %
                ]
                self.archive_worksheet.update('A1', [archive_headers])
                logger.info("Archive worksheet created with headers")
                
        except Exception as e:
            logger.error(f"Error setting up worksheets: {str(e)}")
            raise
    
    def _ensure_required_columns(self):
        """
        Ensure that required columns exist in the worksheet
        """
        required_columns = ["order_id", "Tradable"]
        
        try:
            headers = self.worksheet.row_values(1)
            
            # Find columns that need to be added
            missing_columns = [col for col in required_columns if col not in headers]
            
            if missing_columns:
                # Add missing columns
                for col in missing_columns:
                    next_col = len(headers) + 1
                    self.worksheet.update_cell(1, next_col, col)
                    headers.append(col)
                    logger.info(f"Added '{col}' column to worksheet")
            
            logger.info("All required columns exist in worksheet")
            return headers
            
        except Exception as e:
            logger.error(f"Error ensuring required columns: {str(e)}")
            raise
    
    def _cache_headers(self):
        """
        Cache headers for faster column lookups
        """
        with self._headers_lock:
            try:
                self._headers = self.worksheet.row_values(1)
                logger.debug(f"Cached {len(self._headers)} headers from worksheet")
            except Exception as e:
                logger.error(f"Failed to cache headers: {str(e)}")
                self._headers = None
    
    def get_column_index(self, column_name):
        """
        Get the 1-indexed column number for a given column name
        
        Args:
            column_name (str): Name of the column
            
        Returns:
            int: 1-indexed column number
            
        Raises:
            ValueError: If column not found
        """
        with self._headers_lock:
            # Use cached headers if available
            if self._headers is not None:
                headers = self._headers
            else:
                # Fallback to fetching headers
                headers = self.worksheet.row_values(1)
                self._headers = headers
            
            if column_name in headers:
                return headers.index(column_name) + 1  # 1-indexed
            else:
                raise ValueError(f"Column '{column_name}' not found in worksheet!")
    
    @retry(max_retries=3, retry_delay=2.0, 
           exceptions=(gspread.exceptions.APIError,),
           retry_condition=lambda e: e.response.status_code == 429)
    def get_trade_signals(self):
        """
        Get coins marked for trading from the worksheet
        
        Returns:
            list: Trade signals with required data
        """
        try:
            # Get all records from the sheet
            all_records = self.worksheet.get_all_records()
            
            if not all_records:
                logger.error("No data found in the worksheet")
                return []
            
            # Find rows with actionable signals in 'Buy Signal' column
            trade_signals = []
            for idx, row in enumerate(all_records):
                # Check if TRADE is YES
                trade_value = row.get('TRADE', '').upper()
                is_active = trade_value in ['YES', 'Y', 'TRUE', '1']
                buy_signal = row.get('Buy Signal', '').upper()
                
                # Check if Tradable is YES - if column exists, default to YES if not found
                tradable_value = row.get('Tradable', 'YES').upper()
                tradable = tradable_value in ['YES', 'Y', 'TRUE', '1']
                
                # Skip if not active or not tradable
                if not is_active or not tradable:
                    continue
                
                symbol = row.get('Coin', '')
                if not symbol:
                    continue
                    
                # Format for API: append _USDT if not already in pair format
                if '_' not in symbol and '/' not in symbol:
                    formatted_pair = f"{symbol}_USDT"
                elif '/' in symbol:
                    formatted_pair = symbol.replace('/', '_')
                else:
                    formatted_pair = symbol
                
                # Create base signal data
                signal_data = {
                    'symbol': formatted_pair,
                    'original_symbol': symbol,
                    'row_index': idx + 2,  # +2 for header and 1-indexing
                    'action': buy_signal
                }
                
                # Process based on signal type
                if buy_signal == 'BUY':
                    # Parse numeric values
                    try:
                        # Try to get resistance values with proper number parsing
                        resistance_up = parse_number(row.get('Resistance Up', '0'))
                        resistance_down = parse_number(row.get('Resistance Down', '0'))
                        
                        # Get take profit and stop loss
                        take_profit = parse_number(row.get('Take Profit', '0')) 
                        stop_loss = parse_number(row.get('Stop-Loss', '0'))
                        
                        # Get buy target if available
                        buy_target = parse_number(row.get('Buy Target', '0'))
                        
                        # Add to signal data
                        signal_data.update({
                            'take_profit': take_profit,
                            'stop_loss': stop_loss,
                            'buy_target': buy_target,
                            'resistance_up': resistance_up,
                            'resistance_down': resistance_down
                        })
                        
                    except ValueError as e:
                        logger.error(f"Error parsing values for {symbol}: {str(e)}")
                        continue
                    
                elif buy_signal == 'SELL':
                    # Get the order_id from the sheet to sell the correct position
                    order_id = row.get('order_id', '')
                    signal_data['order_id'] = order_id
                
                trade_signals.append(signal_data)
            
            logger.info(f"Found {len(trade_signals)} trade signals")
            return trade_signals
                
        except Exception as e:
            logger.error(f"Error getting trade signals: {str(e)}")
            return []
    
    @retry(max_retries=2, retry_delay=1.0, 
           exceptions=(gspread.exceptions.APIError,),
           retry_condition=lambda e: e.response.status_code == 429)
    def batch_update_cells(self, updates):
        """
        Update multiple cells in a batch to reduce API calls
        
        Args:
            updates (list): List of (row, col, value) tuples
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not updates:
            return True
            
        try:
            # Convert updates to cell list format
            cells = []
            for row, col, value in updates:
                cell = self.worksheet.cell(row, col)
                cell.value = value
                cells.append(cell)
            
            # Update all cells in one request
            self.worksheet.update_cells(cells)
            logger.info(f"Updated {len(cells)} cells in batch")
            return True
            
        except Exception as e:
            logger.error(f"Error in batch update: {str(e)}")
            
            # Try individual updates as fallback
            logger.warning("Falling back to individual cell updates")
            try:
                success = True
                for row, col, value in updates:
                    try:
                        self.worksheet.update_cell(row, col, value)
                    except Exception as e:
                        logger.error(f"Failed to update cell at ({row}, {col}): {str(e)}")
                        success = False
                return success
            except Exception as e:
                logger.error(f"Fallback update failed: {str(e)}")
                return False
    
    def update_trade_status(self, row_index, status, order_id=None, purchase_price=None, 
                           quantity=None, sell_price=None, sell_date=None, 
                           stop_loss=None, take_profit=None):
        """
        Update trade status in Google Sheet using batch updates
        
        Args:
            row_index (int): Row index (1-indexed)
            status (str): Status to update
            order_id (str, optional): Order ID
            purchase_price (float, optional): Purchase price
            quantity (float, optional): Quantity
            sell_price (float, optional): Sell price
            sell_date (str, optional): Sell date
            stop_loss (float, optional): Stop loss price
            take_profit (float, optional): Take profit price
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info(f"Updating trade status for row {row_index}: {status}")

            def format_number_for_sheet(value):
                if value is None:
                    return ""
                if isinstance(value, (int, float)):
                    # Prevent scientific notation, use 8 decimals max
                    return "{:.8f}".format(value).rstrip("0").rstrip(".")
                return str(value)
            
            # Prepare batch updates
            updates = []
            
            # Order Placed? column
            order_placed_col = self.get_column_index('Order Placed?')
            updates.append((row_index, order_placed_col, status))
            
            if status == "ORDER_PLACED":
                # Tradable = NO
                try:
                    tradable_col = self.get_column_index('Tradable')
                    updates.append((row_index, tradable_col, "NO"))
                except Exception:
                    logger.error("Tradable column not found")
                
                # Timestamp
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Order Date
                order_date_col = self.get_column_index('Order Date')
                updates.append((row_index, order_date_col, timestamp))
                
                # Purchase Price
                if purchase_price:
                    formatted_price = format_number_for_sheet(purchase_price)
                    purchase_price_col = self.get_column_index('Purchase Price')
                    updates.append((row_index, purchase_price_col, formatted_price))
                
                # Quantity
                if quantity:
                    formatted_quantity = format_number_for_sheet(quantity)
                    quantity_col = self.get_column_index('Quantity')
                    updates.append((row_index, quantity_col, formatted_quantity))
                
                # Take Profit
                if take_profit:
                    formatted_tp = format_number_for_sheet(take_profit)
                    tp_col = self.get_column_index('Take Profit')
                    updates.append((row_index, tp_col, formatted_tp))
                
                # Stop Loss
                if stop_loss:
                    formatted_sl = format_number_for_sheet(stop_loss)
                    sl_col = self.get_column_index('Stop-Loss')
                    updates.append((row_index, sl_col, formatted_sl))
                
                # Purchase Date
                purchase_date_col = self.get_column_index('Purchase Date')
                updates.append((row_index, purchase_date_col, timestamp))
                
                # Order ID
                if order_id:
                    # Notes
                    notes_col = self.get_column_index('Notes')
                    updates.append((row_index, notes_col, f"Order ID: {order_id}"))
                    
                    # order_id column
                    try:
                        order_id_col = self.get_column_index('order_id')
                        updates.append((row_index, order_id_col, order_id))
                    except ValueError:
                        logger.error("order_id column not found")
                    
            elif status == "SOLD":
                # Update Buy Signal to WAIT
                buy_signal_col = self.get_column_index('Buy Signal')
                updates.append((row_index, buy_signal_col, "WAIT"))
                
                # Update Sold? to YES
                sold_col = self.get_column_index('Sold?')
                updates.append((row_index, sold_col, "YES"))
                
                # Sell Price
                if sell_price:
                    formatted_sell_price = format_number_for_sheet(sell_price)
                    sell_price_col = self.get_column_index('Sell Price')
                    updates.append((row_index, sell_price_col, formatted_sell_price))
                
                # Sell Quantity
                if quantity:
                    formatted_sell_quantity = format_number_for_sheet(quantity)
                    sell_quantity_col = self.get_column_index('Sell Quantity')
                    updates.append((row_index, sell_quantity_col, formatted_sell_quantity))
                
                # Sold Date
                sold_date = sell_date or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                sold_date_col = self.get_column_index('Sold Date')
                updates.append((row_index, sold_date_col, sold_date))
                
                # Tradable = YES
                try:
                    tradable_col = self.get_column_index('Tradable')
                    updates.append((row_index, tradable_col, "YES"))
                except Exception:
                    logger.error("Tradable column not found")
                
                # Update Notes
                try:
                    current_notes = self.worksheet.cell(row_index, self.get_column_index('Notes')).value or ""
                    new_notes = f"{current_notes} | Position closed: {sold_date}"
                    notes_col = self.get_column_index('Notes')
                    updates.append((row_index, notes_col, new_notes))
                except Exception:
                    logger.error("Notes column not found")
                
                # Clear order_id
                try:
                    order_id_col = self.get_column_index('order_id')
                    updates.append((row_index, order_id_col, ""))
                except ValueError:
                    logger.error("order_id column not found")
            
            elif status == "UPDATE_TP_SL":
                # Update Take Profit and Stop Loss
                if take_profit:
                    formatted_tp = format_number_for_sheet(take_profit)
                    tp_col = self.get_column_index('Take Profit')
                    updates.append((row_index, tp_col, formatted_tp))
                
                if stop_loss:
                    formatted_sl = format_number_for_sheet(stop_loss)
                    sl_col = self.get_column_index('Stop-Loss')
                    updates.append((row_index, sl_col, formatted_sl))
            
            # Execute batch update
            return self.batch_update_cells(updates)
            
        except Exception as e:
            logger.error(f"Error updating trade status: {str(e)}")
            return False
            
    @retry(max_retries=2, retry_delay=1.0)
    def move_to_archive(self, row_index):
        """
        Move completed trade to archive worksheet but keep the coin in the main sheet
        
        Args:
            row_index (int): Row index to archive
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get the row data
            row_data = self.worksheet.row_values(row_index)
            
            # Handle potential missing data in the row
            while len(row_data) < 24:  # Ensure we have enough elements
                row_data.append("")
                
            # Calculate return percentage if possible
            return_percentage = ""
            try:
                buy_price = parse_number(row_data[9])  # Purchase Price
                sell_price = parse_number(row_data[13])  # Sell Price
                
                if buy_price > 0 and sell_price > 0:
                    return_pct = ((sell_price - buy_price) / buy_price) * 100
                    return_percentage = f"{return_pct:.2f}%"
                    
                    if return_pct > 0:
                        return_percentage = f"+{return_percentage}"  # Add plus sign for positive returns
            except Exception as e:
                logger.error(f"Error calculating return percentage: {str(e)}")
            
            # Map columns from trading sheet to archive sheet
            archive_data = [
                row_data[0],  # TRADE
                row_data[1],  # Coin
                row_data[2],  # Last Price
                row_data[3],  # Buy Target
                row_data[4],  # Buy Signal -> Buy Recommendation
                row_data[5],  # Take Profit -> Sell Target
                row_data[6],  # Stop-Loss
                row_data[7],  # Order Placed?
                row_data[8],  # Order Date -> Order Place Date
                row_data[9],  # Purchase Price -> Order PURCHASE Price
                row_data[10], # Quantity -> Order PURCHASE Quantity
                row_data[11], # Purchase Date -> Order PURCHASE Date
                row_data[12], # Sold? -> Order SOLD
                row_data[13], # Sell Price -> SOLD Price
                row_data[14], # Sell Quantity -> SOLD Quantity
                row_data[15], # Sold Date -> SOLD Date
                row_data[16], # Notes
                row_data[17] if len(row_data) > 17 else "", # RSI
                "Trading Bot", # Method (new column)
                row_data[19] if len(row_data) > 19 else "", # Resistance Up
                row_data[20] if len(row_data) > 20 else "", # Resistance Down
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), # Last Updated
                row_data[22] if len(row_data) > 22 else "", # RSI Sparkline
                row_data[23] if len(row_data) > 23 else "", # RSI DATA
                return_percentage  # Return %
            ]
            
            # Append to archive worksheet
            self.archive_worksheet.append_row(archive_data)
            
            # Prepare batch updates to clear the trade related fields in main sheet
            updates = []
            
            # Set Tradable=YES and Buy Signal=WAIT
            try:
                tradable_col = self.get_column_index('Tradable')
                updates.append((row_index, tradable_col, "YES"))
            except Exception:
                logger.error("Tradable column not found")
                
            try:
                buy_signal_col = self.get_column_index('Buy Signal')
                updates.append((row_index, buy_signal_col, "WAIT"))
            except Exception:
                logger.error("Buy Signal column not found")
            
            # Clear other fields
            columns_to_clear = [
                'Order Placed?', 'Sold?', 'Sell Price', 'Sell Quantity', 
                'Sold Date', 'Notes', 'order_id'
            ]
            
            for column in columns_to_clear:
                try:
                    col_index = self.get_column_index(column)
                    updates.append((row_index, col_index, ""))
                except Exception:
                    logger.error(f"{column} column not found")
            
            # Execute batch update
            if updates:
                self.batch_update_cells(updates)
            
            logger.info(f"Trade moved to archive: {row_data[1]}")
            return True
        except Exception as e:
            logger.error(f"Error moving trade to archive: {str(e)}")
            return False
    
    def refresh_headers(self):
        """
        Refresh the cached headers
        """
        self._cache_headers()
    
    def close(self):
        """
        Close any resources if needed
        """
        pass  # No resources to close for gspread at the moment 