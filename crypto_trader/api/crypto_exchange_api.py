#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import hmac
import hashlib
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from threading import Lock

from crypto_trader.config import config
from crypto_trader.utils import setup_logger, retry, normalize_price, format_quantity

logger = setup_logger("crypto_exchange_api")

class CryptoExchangeAPI:
    """
    Handles interactions with Crypto.com Exchange API with proper error handling and retry mechanisms
    """
    
    def __init__(self, api_key=None, api_secret=None):
        self.api_key = api_key or config.CRYPTO_API_KEY
        self.api_secret = api_secret or config.CRYPTO_API_SECRET
        self.trading_base_url = config.TRADING_BASE_URL
        self.account_base_url = config.ACCOUNT_BASE_URL
        self.trade_amount = config.TRADE_AMOUNT
        self.min_balance_required = self.trade_amount * 1.05  # 5% buffer for fees
        self._session = None
        self._price_cache = {}  # Cache for price data
        self._price_cache_lock = Lock()  # Thread-safe cache access
        self._balance_cache = {}  # Cache for balance data
        self._balance_cache_lock = Lock()  # Thread-safe cache access
        
        # Validate API credentials
        if not self.api_key or not self.api_secret:
            logger.error("API key or secret not found in environment variables")
            raise ValueError("CRYPTO_API_KEY and CRYPTO_API_SECRET environment variables are required")
        
        # Initialize session with retry mechanism
        self._init_session()
        
        # Test authentication
        if self.test_auth():
            logger.info("Authentication successful")
        else:
            logger.error("Authentication failed")
            raise ValueError("Could not authenticate with Crypto.com Exchange API")
    
    def _init_session(self):
        """Initialize a requests session with retry capabilities"""
        self._session = requests.Session()
        
        # Configure automatic retries for common HTTP errors
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
    
    def _params_to_str(self, obj, level=0):
        """
        Convert params object to string according to Crypto.com's official algorithm
        
        Args:
            obj: The object to convert
            level: Current recursion level
            
        Returns:
            str: String representation for signature
        """
        MAX_LEVEL = 3  # Maximum recursion level for nested params
        
        if level >= MAX_LEVEL:
            return str(obj)

        if isinstance(obj, dict):
            # Sort dictionary keys
            return_str = ""
            for key in sorted(obj.keys()):
                return_str += key
                if obj[key] is None:
                    return_str += 'null'
                elif isinstance(obj[key], bool):
                    return_str += str(obj[key]).lower()  # 'true' or 'false'
                elif isinstance(obj[key], list):
                    # Special handling for lists
                    for sub_obj in obj[key]:
                        return_str += self._params_to_str(sub_obj, level + 1)
                else:
                    return_str += str(obj[key])
            return return_str
        else:
            return str(obj)
    
    @retry(max_retries=3, retry_delay=1.0)
    def send_request(self, method, params=None):
        """
        Send API request to Crypto.com using official documented signing method
        
        Args:
            method (str): API method to call
            params (dict, optional): Parameters for the request
            
        Returns:
            dict: API response
            
        Raises:
            Exception: On request failure after retries
        """
        if params is None:
            params = {}
        
        # Convert all numeric values to strings as required by API
        def convert_numbers_to_strings(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if isinstance(value, (int, float)):
                        obj[key] = str(value)
                    elif isinstance(value, (dict, list)):
                        convert_numbers_to_strings(value)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    if isinstance(item, (int, float)):
                        obj[i] = str(item)
                    elif isinstance(item, (dict, list)):
                        convert_numbers_to_strings(item)
            return obj
        
        # Convert all numbers to strings as required
        params = convert_numbers_to_strings(params)
            
        # Generate request ID and nonce
        request_id = int(time.time() * 1000)
        nonce = request_id
        
        # Convert params to string using OFFICIAL algorithm
        param_str = self._params_to_str(params)
        
        # Choose base URL based on method
        # Account methods use v2 API, trading methods use v1 API
        account_methods = [
            "private/get-account-summary", 
            "private/margin/get-account-summary",
            "private/get-subaccount-balances",
            "private/get-accounts"
        ]
        is_account_method = any(method.startswith(acc_method) for acc_method in account_methods)
        base_url = self.account_base_url if is_account_method else self.trading_base_url
        
        # Build signature payload EXACTLY as in documentation
        # Format: method + id + api_key + params_string + nonce
        sig_payload = method + str(request_id) + self.api_key + param_str + str(nonce)
        
        # Generate signature
        signature = hmac.new(
            bytes(self.api_secret, 'utf-8'),
            msg=bytes(sig_payload, 'utf-8'),
            digestmod=hashlib.sha256
        ).hexdigest()
        
        # Create request body
        request_body = {
            "id": request_id,
            "method": method,
            "api_key": self.api_key,
            "params": params,
            "nonce": nonce,
            "sig": signature
        }
        
        # API endpoint
        endpoint = f"{base_url}{method}"
        
        # Log detailed request information (with sensitive data masked)
        logger.debug(
            f"Sending request to {endpoint} "
            f"with method: {method}, params: {json.dumps({k: '***' if k in ['api_key', 'sig'] else v for k, v in params.items()})}"
        )
        
        # Send request
        headers = {'Content-Type': 'application/json'}
        try:
            response = self._session.post(
                endpoint,
                headers=headers,
                json=request_body,
                timeout=30
            )
            
            # Parse response
            response_data = {}
            try:
                response_data = response.json()
            except Exception as e:
                logger.error(f"Failed to parse response as JSON: {str(e)}")
                logger.error(f"Raw response: {response.text[:500]}")
                response_data = {"error": "Failed to parse JSON", "raw": response.text[:500]}
            
            # Log response code
            logger.debug(f"Response from {method}: code={response_data.get('code')}")
            
            return response_data
            
        except requests.RequestException as e:
            logger.error(f"Request failed: {str(e)}")
            raise
    
    def test_auth(self):
        """
        Test authentication with the exchange API
        
        Returns:
            bool: True if authentication successful, False otherwise
        """
        try:
            account_summary = self.get_account_summary()
            return account_summary is not None
        except Exception as e:
            logger.error(f"Authentication test failed: {str(e)}")
            return False
    
    def get_account_summary(self):
        """
        Get account summary from the exchange
        
        Returns:
            dict: Account summary data or None on failure
        """
        try:
            method = "private/get-account-summary"
            params = {}
            
            # Send request
            response = self.send_request(method, params)
            
            if response.get("code") == 0:
                logger.debug("Successfully fetched account summary")
                return response.get("result")
            else:
                error_code = response.get("code")
                error_msg = response.get("message", response.get("msg", "Unknown error"))
                logger.error(f"API error: {error_code} - {error_msg}")
            
            return None
        except Exception as e:
            logger.error(f"Error in get_account_summary: {str(e)}")
            return None
    
    def get_balance(self, currency="USDT"):
        """
        Get balance for a specific currency with caching
        
        Args:
            currency (str): Currency symbol
            
        Returns:
            float: Available balance
        """
        try:
            # Check cache first (5 second validity)
            with self._balance_cache_lock:
                cache_key = currency
                if cache_key in self._balance_cache:
                    cache_time, cached_value = self._balance_cache[cache_key]
                    if time.time() - cache_time < 5:  # 5 seconds cache validity
                        logger.debug(f"Using cached balance for {currency}: {cached_value}")
                        return cached_value
            
            account_summary = self.get_account_summary()
            if not account_summary or "accounts" not in account_summary:
                logger.error("Failed to get account summary")
                return 0
                
            # Find the currency in accounts
            for account in account_summary["accounts"]:
                if account.get("currency") == currency:
                    available = float(account.get("available", 0))
                    logger.info(f"Available {currency} balance: {available}")
                    
                    # Update cache
                    with self._balance_cache_lock:
                        self._balance_cache[cache_key] = (time.time(), available)
                    
                    return available
                    
            logger.warning(f"Currency {currency} not found in account")
            return 0
        except Exception as e:
            logger.error(f"Error in get_balance: {str(e)}")
            return 0
    
    def has_sufficient_balance(self, currency="USDT"):
        """
        Check if there is sufficient balance for trading
        
        Args:
            currency (str): Currency to check
            
        Returns:
            bool: True if sufficient balance exists, False otherwise
        """
        balance = self.get_balance(currency)
        sufficient = balance >= self.min_balance_required
        
        if sufficient:
            logger.info(f"Sufficient balance: {balance} {currency}")
        else:
            logger.warning(f"Insufficient balance: {balance} {currency}, minimum required: {self.min_balance_required}")
            
        return sufficient
    
    def buy_coin(self, instrument_name, amount_usd=None):
        """
        Buy coin with specified USD amount using market order
        
        Args:
            instrument_name (str): Instrument name (e.g. BTC_USDT)
            amount_usd (float, optional): Amount in USD to buy
            
        Returns:
            str: Order ID or None on failure
        """
        if amount_usd is None:
            amount_usd = self.trade_amount
            
        logger.info(f"Creating market buy order for {instrument_name} with ${amount_usd}")
        
        # IMPORTANT: Use the exact method format from documentation
        method = "private/create-order"
        
        # Create order params - ensure all numbers are strings
        params = {
            "instrument_name": instrument_name,
            "side": "BUY",
            "type": "MARKET",
            "notional": str(float(amount_usd))  # Convert to string as required
        }
        
        # Send order request
        response = self.send_request(method, params)
        
        # Check response
        if response.get("code") == 0:
            order_id = None
            
            # Try to extract order ID
            if "result" in response and "order_id" in response.get("result", {}):
                order_id = response.get("result", {}).get("order_id")
            
            if order_id:
                logger.info(f"Order successfully created! Order ID: {order_id}")
                return order_id
            else:
                logger.info(f"Order successful, but couldn't find order ID in response")
                return "success_no_id"
        else:
            error_code = response.get("code")
            error_msg = response.get("message", response.get("msg", "Unknown error"))
            logger.error(f"Failed to create order. Error {error_code}: {error_msg}")
            return None
    
    def get_coin_balance(self, currency):
        """
        Get coin balance (alias for get_balance for clarity)
        
        Args:
            currency (str): Currency symbol
            
        Returns:
            str: Available balance as string
        """
        balance = self.get_balance(currency)
        return str(balance)
    
    def get_order_status(self, order_id):
        """
        Get the status of an order
        
        Args:
            order_id (str): Order ID
            
        Returns:
            str: Order status or None on failure
        """
        try:
            method = "private/get-order-detail"
            params = {
                "order_id": order_id
            }
            
            # Send request
            response = self.send_request(method, params)
            
            if response.get("code") == 0:
                order_detail = response.get("result", {})
                status = order_detail.get("status")
                logger.debug(f"Order {order_id} status: {status}")
                return status
            else:
                error_code = response.get("code")
                error_msg = response.get("message", response.get("msg", "Unknown error"))
                logger.error(f"API error: {error_code} - {error_msg}")
            
            return None
        except Exception as e:
            logger.error(f"Error in get_order_status: {str(e)}")
            return None
    
    def sell_coin(self, instrument_name, quantity=None, notional=None):
        """
        Sell a specified quantity of a coin using MARKET order
        
        Args:
            instrument_name (str): Instrument name (e.g. BTC_USDT)
            quantity (float, optional): Quantity to sell
            notional (float, optional): Value in USD to sell (not recommended)
            
        Returns:
            str: Order ID or None on failure
        """
        try:
            # Extract base currency from instrument_name
            base_currency = instrument_name.split('_')[0]
            
            # Generate unique client order ID
            client_order_id = f"SELL_{instrument_name}_{int(time.time() * 1000)}"
            
            # SAFETY CHECK: Prevent usage of notional parameter for SELL orders
            if notional is not None:
                logger.critical("CRITICAL ERROR: 'notional' parameter was passed to sell_coin, but this is not allowed!")
                logger.critical("For SELL orders, you MUST use quantity parameter, not notional")
                logger.critical("Converting notional to quantity using current price")
                
                # Try to convert notional to quantity using current price
                current_price = self.get_current_price(instrument_name)
                if current_price:
                    quantity = float(notional) / float(current_price)
                    logger.warning(f"Converted notional {notional} to quantity {quantity} using price {current_price}")
                else:
                    logger.error("Cannot convert notional to quantity - cannot get current price")
                    return None
            
            # If quantity is not provided, determine it from available balance
            if quantity is None:
                logger.info(f"No quantity provided, getting available balance for {base_currency}")
                available_balance = self.get_coin_balance(base_currency)
                
                if not available_balance or available_balance == "0":
                    logger.error(f"No available balance found for {base_currency}")
                    return None
                
                # Convert to float and use 95% of available balance (to avoid precision issues)
                available_balance = float(available_balance)
                quantity = available_balance * 0.95
                logger.info(f"Using 95% of available balance: {quantity} {base_currency}")
            else:
                # If quantity is provided, convert to float
                quantity = float(quantity)
            
            # Format quantity based on coin requirements
            formatted_quantity = format_quantity(quantity, instrument_name)
            
            # Get current price for logging purposes
            current_price = self.get_current_price(instrument_name)
            if current_price:
                usd_value = float(formatted_quantity) * float(current_price)
                logger.info(f"Attempting to sell {formatted_quantity} {base_currency} (approx. ${usd_value:.2f})")
            
            # Create the order request with client_order_id
            response = self.send_request(
                "private/create-order", 
                {
                    "instrument_name": instrument_name,
                    "side": "SELL",
                    "type": "MARKET",
                    "quantity": formatted_quantity,
                    "client_oid": client_order_id
                }
            )
            
            # Check response
            if not response:
                logger.error("No response received from API")
                return None
                
            if response.get("code") != 0:
                error_code = response.get("code")
                error_msg = response.get("message", response.get("msg", "Unknown error"))
                logger.error(f"API error creating sell order: {error_code} - {error_msg}")
                
                # Handle specific error cases
                if error_code == 213 or "Invalid quantity format" in error_msg:
                    logger.warning(f"Invalid quantity format (error {error_code}). Attempting alternative approach.")
                    
                    # Try different formats based on coin type
                    retry_formats = []
                    
                    if base_currency in config.INTEGER_COINS:
                        # For meme coins, try without decimal and with rounding
                        retry_formats = [
                            str(int(quantity)),  # Integer
                            str(int(quantity * 0.99)),  # 99% as integer
                            str(int(quantity * 0.95))  # 95% as integer
                        ]
                    else:
                        # For other coins try various precision levels
                        retry_formats = [
                            f"{quantity:.1f}",  # 1 decimal
                            f"{quantity:.0f}",  # 0 decimals
                            f"{quantity * 0.99:.8f}"  # 8 decimals with 99%
                        ]
                    
                    # Try each format
                    for retry_format in retry_formats:
                        logger.info(f"Retry with format: {retry_format}")
                        
                        retry_response = self.send_request(
                            "private/create-order", 
                            {
                                "instrument_name": instrument_name,
                                "side": "SELL",
                                "type": "MARKET",
                                "quantity": retry_format
                            }
                        )
                        
                        if retry_response and retry_response.get("code") == 0:
                            order_id = retry_response["result"]["order_id"]
                            logger.info(f"Retry successful with format {retry_format}! Order ID: {order_id}")
                            return order_id
                    
                    # Try batch selling approach
                    return self._batch_sell_coin(instrument_name, quantity, base_currency)
                
                return None
            
            # Extract order ID from successful response
            if "result" in response and "order_id" in response["result"]:
                order_id = response["result"]["order_id"]
                logger.info(f"Successfully created SELL order with ID: {order_id}")
                return order_id
            else:
                logger.error(f"Unexpected response format: {response}")
                return None
                
        except Exception as e:
            logger.exception(f"Error in sell_coin for {instrument_name}: {str(e)}")
            return None
    
    def _batch_sell_coin(self, instrument_name, total_quantity, base_currency):
        """
        Sell coin in smaller batches when a large order fails
        
        Args:
            instrument_name (str): Instrument name
            total_quantity (float): Total quantity to sell
            base_currency (str): Base currency
            
        Returns:
            str: First successful order ID or None
        """
        try:
            logger.info(f"Using batch sell approach for {instrument_name}")
            
            # Maximum batch size
            max_batch_size = 100000 if base_currency in config.INTEGER_COINS else 100
            
            # Calculate number of batches
            if total_quantity > max_batch_size:
                num_batches = int(total_quantity / max_batch_size) + (1 if total_quantity % max_batch_size > 0 else 0)
                logger.info(f"Selling {total_quantity} {base_currency} in {num_batches} batches")
                
                successful_orders = []
                remaining_quantity = total_quantity
                
                for i in range(num_batches):
                    # For the last batch, get current balance to avoid errors
                    if i == num_batches - 1:
                        current_balance = float(self.get_coin_balance(base_currency))
                        if current_balance <= 0:
                            logger.info(f"No balance left, selling completed")
                            break
                        
                        # Use 98% of remaining balance
                        batch_quantity = current_balance * 0.98
                    else:
                        # Use maximum batch size for each batch
                        batch_quantity = min(max_batch_size, remaining_quantity)
                    
                    # Format the quantity
                    formatted_batch = format_quantity(batch_quantity, instrument_name)
                    
                    if float(formatted_batch) <= 0:
                        logger.warning(f"Batch {i+1} quantity is zero or negative, skipping")
                        continue
                    
                    logger.info(f"Batch {i+1}/{num_batches}: Selling {formatted_batch} {base_currency}")
                    
                    # Generate unique client order ID for this batch
                    batch_client_order_id = f"SELL_{instrument_name}_BATCH_{i+1}_{int(time.time() * 1000)}"
                    
                    # Create sell order for this batch
                    batch_response = self.send_request(
                        "private/create-order", 
                        {
                            "instrument_name": instrument_name,
                            "side": "SELL",
                            "type": "MARKET",
                            "quantity": formatted_batch,
                            "client_oid": batch_client_order_id
                        }
                    )
                    
                    if batch_response and batch_response.get("code") == 0:
                        batch_order_id = batch_response["result"]["order_id"]
                        successful_orders.append(batch_order_id)
                        logger.info(f"Batch {i+1} successfully sold! Order ID: {batch_order_id}")
                        
                        # Update remaining quantity
                        remaining_quantity -= batch_quantity
                        
                        # Small delay between batches
                        time.sleep(2)
                    else:
                        error_msg = batch_response.get("message", "Unknown error") if batch_response else "No response"
                        logger.error(f"Batch {i+1} failed: {error_msg}")
                        
                        # Try with a different format
                        if "Invalid quantity format" in error_msg:
                            # Try with 99% of the batch
                            modified_batch = format_quantity(batch_quantity * 0.99, instrument_name)
                            
                            logger.info(f"Retrying batch {i+1} with quantity: {modified_batch}")
                            
                            retry_response = self.send_request(
                                "private/create-order", 
                                {
                                    "instrument_name": instrument_name,
                                    "side": "SELL",
                                    "type": "MARKET",
                                    "quantity": modified_batch
                                }
                            )
                            
                            if retry_response and retry_response.get("code") == 0:
                                retry_order_id = retry_response["result"]["order_id"]
                                successful_orders.append(retry_order_id)
                                logger.info(f"Batch {i+1} retry succeeded! Order ID: {retry_order_id}")
                
                # Return the first successful order ID if any
                if successful_orders:
                    logger.info(f"Successfully sold {len(successful_orders)}/{num_batches} batches")
                    return successful_orders[0]
            
            # If we get here, try selling 50% as a last resort
            logger.info(f"Trying to sell 50% of the total quantity")
            half_quantity = total_quantity * 0.5
            formatted_half = format_quantity(half_quantity, instrument_name)
            
            final_response = self.send_request(
                "private/create-order", 
                {
                    "instrument_name": instrument_name,
                    "side": "SELL",
                    "type": "MARKET",
                    "quantity": formatted_half
                }
            )
            
            if final_response and final_response.get("code") == 0:
                final_order_id = final_response["result"]["order_id"]
                logger.info(f"Successfully sold 50% of quantity! Order ID: {final_order_id}")
                return final_order_id
            
            return None
            
        except Exception as e:
            logger.error(f"Error in batch sell method: {str(e)}")
            return None
    
    @retry(max_retries=3, retry_delay=1.0)
    def get_current_price(self, instrument_name):
        """
        Get current price for a symbol from the API
        
        Args:
            instrument_name (str): Instrument name
            
        Returns:
            float: Current price or None on failure
        """
        try:
            # Check cache first (1 second validity)
            with self._price_cache_lock:
                cache_key = instrument_name
                if cache_key in self._price_cache:
                    cache_time, cached_price = self._price_cache[cache_key]
                    if time.time() - cache_time < 1:  # 1 second cache validity
                        logger.debug(f"Using cached price for {instrument_name}: {cached_price}")
                        return cached_price
            
            # Simple public API call - no signature needed
            url = f"{self.account_base_url}public/get-ticker"
            
            # Simple parameter format
            params = {
                "instrument_name": instrument_name
            }
            
            logger.debug(f"Getting price for {instrument_name}")
            
            # Direct HTTP GET request - no signature needed for public endpoint
            response = self._session.get(url, params=params, timeout=30)
            
            # Process response
            if response.status_code == 200:
                response_data = response.json()
                
                if response_data.get("code") == 0:
                    result = response_data.get("result", {})
                    data = result.get("data", [])
                    
                    if data:
                        # Get the latest price
                        latest_price = float(data[0].get("a", 0))  # 'a' is the ask price
                        
                        # Normalize price if needed
                        latest_price = normalize_price(latest_price, instrument_name)
                        
                        logger.debug(f"Current price for {instrument_name}: {latest_price}")
                        
                        # Update cache
                        with self._price_cache_lock:
                            self._price_cache[cache_key] = (time.time(), latest_price)
                        
                        return latest_price
                    else:
                        logger.warning(f"No ticker data found for {instrument_name}")
                else:
                    error_code = response_data.get("code")
                    error_msg = response_data.get("message", response_data.get("msg", "Unknown error"))
                    logger.error(f"API error: {error_code} - {error_msg}")
            else:
                logger.error(f"HTTP error: {response.status_code} - {response.text[:200]}")
            
            return None
        except Exception as e:
            logger.error(f"Error getting current price for {instrument_name}: {str(e)}")
            raise  # Let the retry decorator handle this
    
    def cancel_order(self, order_id):
        """
        Cancel an existing order
        
        Args:
            order_id (str): The order ID to cancel
            
        Returns:
            bool: True if cancelled successfully, False otherwise
        """
        try:
            method = "private/cancel-order"
            params = {"order_id": order_id}
            
            response = self.send_request(method, params)
            
            if response and response.get("code") == 0:
                logger.info(f"Successfully cancelled order {order_id}")
                return True
            else:
                error_code = response.get("code") if response else None
                error_msg = response.get("message", "Unknown error") if response else "No response"
                logger.error(f"Failed to cancel order {order_id}: {error_code} - {error_msg}")
                return False
        
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {str(e)}")
            return False
            
    def close(self):
        """Close resources properly"""
        if self._session:
            try:
                self._session.close()
                logger.debug("API session closed")
            except Exception as e:
                logger.error(f"Error closing API session: {str(e)}")
            finally:
                self._session = None

    @retry(max_retries=3, retry_delay=1.0)
    def get_order_details(self, order_id):
        """
        Get detailed information about a specific order
        
        Args:
            order_id (str): The order ID to query
            
        Returns:
            dict: Order details or None on failure
        """
        try:
            method = "private/get-order-detail"
            params = {
                "order_id": str(order_id)
            }
            
            response = self.send_request(method, params)
            
            if response.get("code") == 0:
                result = response.get("result", {})
                if result and isinstance(result, list) and len(result) > 0:
                    logger.debug(f"Successfully fetched order details for {order_id}")
                    return result[0]  # Return first order detail
                else:
                    logger.warning(f"No order details found for order ID {order_id}")
                    return None
            else:
                error_code = response.get("code")
                error_msg = response.get("message", response.get("msg", "Unknown error"))
                logger.error(f"API error getting order details: {error_code} - {error_msg}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting order details: {str(e)}")
            return None 