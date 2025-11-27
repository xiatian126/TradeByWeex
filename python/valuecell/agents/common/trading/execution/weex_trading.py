"""WEEX exchange execution gateway.

This module implements a custom execution gateway for WEEX exchange since
CCXT does not support WEEX natively.

WEEX API Documentation: https://www.weex.com/api-doc/zh-CN/ai/intro

All operations use the WEEX Contract API endpoints:
- Base URL: https://api-contract.weex.com
- Account API: /capi/v2/account/accounts (获取账户信息、余额、持仓)
- Order API: /capi/v2/order/placeOrder (下单)
- Order API: /capi/v2/order/cancel_order (撤单)
- Order API: /capi/v2/order/detail (查询订单详情)
- Order API: /capi/v2/order/current (查询当前委托)
- Market API: /capi/v2/market/ticker (获取行情)
- Market API: /capi/v2/market/klines (获取K线数据)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from typing import Dict, List, Optional

import httpx
from loguru import logger

from valuecell.agents.common.trading.models import (
    FeatureVector,
    PriceMode,
    TradeInstruction,
    TradeSide,
    TxResult,
    TxStatus,
    derive_side_from_action,
)

from .interfaces import BaseExecutionGateway


class WeexExecutionGateway(BaseExecutionGateway):
    """Custom execution gateway for WEEX exchange.

    Features:
    - Direct REST API integration (CCXT doesn't support WEEX)
    - HMAC SHA256 + BASE64 signature
    - Contract trading support
    - Symbol format: cmt_btcusdt (lowercase with underscore prefix)
    """

    BASE_URL = "https://api-contract.weex.com"

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        passphrase: str,
        testnet: bool = False,
        default_type: str = "swap",
        margin_mode: str = "cross",
    ) -> None:
        """Initialize WEEX execution gateway.

        Args:
            api_key: WEEX API key
            secret_key: WEEX secret key
            passphrase: WEEX passphrase
            testnet: Whether to use testnet (not supported by WEEX currently)
            default_type: Market type ('swap' for perpetual contracts)
            margin_mode: Margin mode ('cross' or 'isolated')
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.testnet = testnet
        self.default_type = default_type
        self.margin_mode = margin_mode
        self._client: Optional[httpx.AsyncClient] = None

    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol to WEEX format.

        Converts BTC-USDT to cmt_btcusdt (lowercase with underscore prefix).

        Args:
            symbol: Symbol in format 'BTC-USDT', 'BTC/USDT', etc.

        Returns:
            Normalized WEEX symbol format
        """
        # Remove slashes and dashes, convert to lowercase
        base_symbol = symbol.replace("-", "").replace("/", "").lower()
        # Add cmt_ prefix if not present
        if not base_symbol.startswith("cmt_"):
            base_symbol = f"cmt_{base_symbol}"
        return base_symbol

    def _round_to_step_size(self, quantity: float, step_size: float) -> float:
        """Round quantity to match step size requirement.
        
        Args:
            quantity: Original quantity
            step_size: Step size requirement (e.g., 0.0001)
            
        Returns:
            Rounded quantity that matches step size (rounded down to nearest step)
        """
        if step_size <= 0:
            return quantity
        if quantity <= 0:
            return 0.0
        
        # Calculate number of steps (round down)
        steps = int(quantity / step_size)
        # Round down to nearest step size
        rounded = steps * step_size
        
        # Ensure we don't return 0 if original quantity was positive
        # But also ensure we don't exceed original quantity
        if rounded <= 0 and quantity > 0:
            rounded = step_size
        
        # Round to avoid floating point precision issues
        # Count decimal places in step_size
        step_str = f"{step_size:.10f}".rstrip('0').rstrip('.')
        if '.' in step_str:
            decimals = len(step_str.split('.')[1])
        else:
            decimals = 0
        
        # Round to match step_size precision
        rounded = round(rounded, decimals)
        
        return rounded

    def _extract_step_size_from_error(self, error_msg: str) -> Optional[float]:
        """Extract step size from error message.
        
        Example error: "The order size must be greater than 0 and matches the stepSize '0.0001' requirement."
        
        Args:
            error_msg: Error message from API
            
        Returns:
            Step size if found, None otherwise
        """
        import re
        # Try to extract stepSize from error message
        match = re.search(r"stepSize\s*['\"]?([0-9.]+)", error_msg, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except (ValueError, TypeError):
                pass
        return None

    def _generate_signature(
        self, timestamp: str, method: str, request_path: str, query_string: str = "", body: str = ""
    ) -> str:
        """Generate WEEX API signature.

        Signature format: timestamp + method.toUpperCase() + requestPath + "?" + queryString + body
        If query_string is empty, omit the "?" part.
        Then HMAC SHA256 + BASE64 encode.

        Args:
            timestamp: Timestamp string
            method: HTTP method (GET, POST, etc.)
            request_path: API endpoint path (without query string)
            query_string: Query string (e.g., "symbol=cmt_btcusdt&limit=100")
            body: Request body string (empty for GET requests)

        Returns:
            Base64 encoded signature
        """
        # Build message string
        if query_string:
            message = f"{timestamp}{method.upper()}{request_path}?{query_string}{body}"
        else:
            message = f"{timestamp}{method.upper()}{request_path}{body}"

        # HMAC SHA256
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        # BASE64 encode
        return base64.b64encode(signature).decode("utf-8")

    def _get_headers(
        self, method: str, request_path: str, body: str = "", query_string: str = ""
    ) -> Dict[str, str]:
        """Generate request headers with signature.

        Args:
            method: HTTP method
            request_path: API endpoint path (without query string)
            body: Request body string
            query_string: Query string for GET requests

        Returns:
            Dictionary of request headers
        """
        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature(timestamp, method, request_path, query_string, body)

        return {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-PASSPHRASE": self.passphrase,
            "ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
            "locale": "zh-CN",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=30.0,
            )
        return self._client

    def _map_action_to_weex_type(self, action: Optional[str], side: TradeSide) -> str:
        """Map TradeInstruction action to WEEX order type.

        WEEX order types:
        - 1: 开多 (open long)
        - 2: 开空 (open short)
        - 3: 平多 (close long)
        - 4: 平空 (close short)

        Args:
            action: Action from instruction (open_long, open_short, close_long, close_short)
            side: Trade side (BUY or SELL)

        Returns:
            WEEX order type string ("1", "2", "3", or "4")
        """
        if action:
            action_lower = action.lower()
            if action_lower == "open_long":
                return "1"
            elif action_lower == "open_short":
                return "2"
            elif action_lower == "close_long":
                return "3"
            elif action_lower == "close_short":
                return "4"

        # Fallback: infer from side
        # For BUY, assume open long; for SELL, assume open short
        # This is a best-effort guess and may need adjustment based on position
        if side == TradeSide.BUY:
            return "1"  # open long
        else:
            return "2"  # open short

    def _map_margin_mode(self, margin_mode: str) -> int:
        """Map margin mode to WEEX format.

        WEEX margin modes:
        - 1: 全仓模式 (cross margin)
        - 3: 逐仓模式 (isolated margin)

        Args:
            margin_mode: Margin mode string ('cross' or 'isolated')

        Returns:
            WEEX margin mode integer (1 or 3)
        """
        if margin_mode.lower() == "isolated":
            return 3
        return 1  # default to cross margin

    async def execute(
        self,
        instructions: List[TradeInstruction],
        market_features: Optional[List[FeatureVector]] = None,
    ) -> List[TxResult]:
        """Execute trade instructions on WEEX exchange.

        Args:
            instructions: List of trade instructions to execute
            market_features: Optional market features (not used for real execution)

        Returns:
            List of transaction results with fill details
        """
        if not instructions:
            logger.warning("⚠️ WeexExecutionGateway: No instructions to execute")
            return []

        logger.info(
            f"💰 WeexExecutionGateway: Executing {len(instructions)} instructions"
        )
        results: List[TxResult] = []

        for inst in instructions:
            try:
                result = await self._execute_single(inst)
                results.append(result)
            except Exception as e:
                side = (
                    getattr(inst, "side", None)
                    or derive_side_from_action(getattr(inst, "action", None))
                    or TradeSide.BUY
                )
                logger.error(f"❌ Error executing instruction {inst.instruction_id}: {e}")
                results.append(
                    TxResult(
                        instruction_id=inst.instruction_id,
                        instrument=inst.instrument,
                        side=side,
                        requested_qty=float(inst.quantity),
                        filled_qty=0.0,
                        status=TxStatus.ERROR,
                        reason=str(e),
                        meta=inst.meta,
                    )
                )

        return results

    async def _execute_single(self, inst: TradeInstruction) -> TxResult:
        """Execute a single trade instruction.

        Args:
            inst: Trade instruction to execute

        Returns:
            Transaction result with execution details
        """
        # Normalize symbol
        symbol = self._normalize_symbol(inst.instrument.symbol)

        # Determine side and action
        side = (
            getattr(inst, "side", None)
            or derive_side_from_action(getattr(inst, "action", None))
            or TradeSide.BUY
        )
        action = (inst.action.value if getattr(inst, "action", None) else None) or str(
            (inst.meta or {}).get("action") or ""
        )

        # Map to WEEX order type
        weex_type = self._map_action_to_weex_type(action, side)

        # Determine order type and match price
        order_type = "0"  # 0:普通
        match_price = "0"  # 0:限价, 1:市价
        price = str(inst.limit_price) if inst.limit_price else "0"

        if inst.price_mode == PriceMode.MARKET:
            match_price = "1"
            # For market orders, we need to fetch current price
            # For now, set price to 0 and let exchange handle it
            price = "0"

        # Round quantity to reasonable precision (default step size for most contracts is 0.0001)
        # We'll try with a default step size first, and if it fails, extract from error
        quantity = float(inst.quantity)
        default_step_size = 0.0001  # Common step size for BTC contracts
        quantity = self._round_to_step_size(quantity, default_step_size)
        
        # If quantity becomes 0 after rounding, reject the order
        if quantity <= 0:
            logger.warning(
                f"  ⚠️ Quantity {inst.quantity} rounded to 0 with step size {default_step_size}, rejecting order"
            )
            return TxResult(
                instruction_id=inst.instruction_id,
                instrument=inst.instrument,
                side=side,
                requested_qty=float(inst.quantity),
                filled_qty=0.0,
                status=TxStatus.REJECTED,
                reason=f"quantity_too_small_for_step_size_{default_step_size}",
                meta=inst.meta,
            )

        # Build request body
        request_body = {
            "symbol": symbol,
            "client_oid": inst.instruction_id[:40],  # WEEX limit: max 40 chars
            "size": str(quantity),
            "type": weex_type,
            "order_type": order_type,
            "match_price": match_price,
            "price": price,
            "marginMode": self._map_margin_mode(self.margin_mode),
        }

        # Add optional parameters
        if inst.meta:
            if "presetTakeProfitPrice" in inst.meta:
                request_body["presetTakeProfitPrice"] = str(inst.meta["presetTakeProfitPrice"])
            if "presetStopLossPrice" in inst.meta:
                request_body["presetStopLossPrice"] = str(inst.meta["presetStopLossPrice"])

        body_str = json.dumps(request_body, separators=(",", ":"))
        request_path = "/capi/v2/order/placeOrder"

        # Get headers with signature (POST requests don't have query string)
        headers = self._get_headers("POST", request_path, body_str, "")

        # Make request
        client = await self._get_client()
        logger.info(
            f"  📤 Placing order: {symbol} type={weex_type} size={inst.quantity} price={price}"
        )

        try:
            response = await client.post(
                request_path,
                headers=headers,
                content=body_str,
            )
            response.raise_for_status()
            result_data = response.json()

            # WEEX API may return data wrapped in a response structure
            # Handle both direct response and wrapped response
            if isinstance(result_data, dict):
                if "code" in result_data and result_data.get("code") != 0:
                    error_msg = result_data.get("msg", "Unknown error")
                    logger.error(f"  ❌ WEEX API error: {error_msg}")
                    raise Exception(f"WEEX API error: {error_msg}")
                # Extract data if wrapped
                if "data" in result_data:
                    result_data = result_data["data"]

            # Parse response - handle both snake_case and camelCase
            order_id = result_data.get("order_id") or result_data.get("orderId")
            client_oid = result_data.get("client_oid") or result_data.get("clientOid")

            logger.info(f"  ✓ Order placed: order_id={order_id}, client_oid={client_oid}")

            # Try to fetch order status to get accurate fill information
            filled_qty = 0.0
            avg_price = None
            status = TxStatus.PARTIAL  # Default to PARTIAL, will be updated based on order status

            if order_id:
                try:
                    # Fetch order status to get accurate fill information
                    order_info = await self.fetch_order(order_id, symbol)
                    if order_info:
                        filled_qty = float(order_info.get("filled_qty", "0") or "0")
                        price_avg = order_info.get("price_avg")
                        if price_avg:
                            avg_price = float(price_avg)
                        order_status = order_info.get("status", "").lower()
                        if order_status == "filled":
                            status = TxStatus.FILLED
                        elif order_status in ("canceled", "canceling"):
                            status = TxStatus.REJECTED
                        elif filled_qty > 0:
                            status = TxStatus.PARTIAL
                except Exception as e:
                    logger.warning(f"  ⚠️ Could not fetch order status: {e}, using defaults")

            # Fallback for market orders
            if match_price == "1" and filled_qty == 0.0:
                filled_qty = float(inst.quantity)
                status = TxStatus.FILLED

            return TxResult(
                instruction_id=inst.instruction_id,
                instrument=inst.instrument,
                side=side,
                requested_qty=float(inst.quantity),
                filled_qty=filled_qty,
                avg_exec_price=avg_price or (float(price) if price != "0" and match_price == "0" else None),
                status=status,
                reason=order_id if order_id else None,
                meta=inst.meta,
            )

        except httpx.HTTPStatusError as e:
            # Try to parse error message from response
            try:
                error_data = e.response.json()
                error_msg = error_data.get("msg", error_data.get("message", e.response.text))
                
                # Check if this is a step size error and retry with correct step size
                if e.response.status_code == 400 and "stepSize" in error_msg:
                    step_size = self._extract_step_size_from_error(error_msg)
                    if step_size and step_size > 0:
                        logger.info(
                            f"  🔄 Retrying order with step size {step_size} (original quantity: {inst.quantity})"
                        )
                        # Round quantity to the correct step size
                        corrected_quantity = self._round_to_step_size(float(inst.quantity), step_size)
                        
                        if corrected_quantity > 0:
                            # Update request body with corrected quantity
                            request_body["size"] = str(corrected_quantity)
                            body_str = json.dumps(request_body, separators=(",", ":"))
                            headers = self._get_headers("POST", request_path, body_str, "")
                            
                            # Retry the request
                            try:
                                response = await client.post(
                                    request_path,
                                    headers=headers,
                                    content=body_str,
                                )
                                response.raise_for_status()
                                result_data = response.json()
                                
                                # Process successful response (same as above)
                                if isinstance(result_data, dict):
                                    if "code" in result_data and result_data.get("code") != 0:
                                        error_msg_retry = result_data.get("msg", "Unknown error")
                                        logger.error(f"  ❌ WEEX API error on retry: {error_msg_retry}")
                                        raise Exception(f"WEEX API error: {error_msg_retry}")
                                    if "data" in result_data:
                                        result_data = result_data["data"]
                                
                                order_id = result_data.get("order_id") or result_data.get("orderId")
                                client_oid = result_data.get("client_oid") or result_data.get("clientOid")
                                
                                logger.info(f"  ✓ Order placed (retry): order_id={order_id}, client_oid={client_oid}, corrected_qty={corrected_quantity}")
                                
                                # Fetch order status
                                filled_qty = 0.0
                                avg_price = None
                                status = TxStatus.PARTIAL  # Default to PARTIAL, will be updated based on order status
                                
                                if order_id:
                                    try:
                                        order_info = await self.fetch_order(order_id, symbol)
                                        if order_info:
                                            filled_qty = float(order_info.get("filled_qty", "0") or "0")
                                            price_avg = order_info.get("price_avg")
                                            if price_avg:
                                                avg_price = float(price_avg)
                                            order_status = order_info.get("status", "").lower()
                                            if order_status == "filled":
                                                status = TxStatus.FILLED
                                            elif order_status in ("canceled", "canceling"):
                                                status = TxStatus.REJECTED
                                            elif filled_qty > 0:
                                                status = TxStatus.PARTIAL
                                    except Exception as e:
                                        logger.warning(f"  ⚠️ Could not fetch order status: {e}, using defaults")
                                
                                if match_price == "1" and filled_qty == 0.0:
                                    filled_qty = corrected_quantity
                                    status = TxStatus.FILLED
                                
                                return TxResult(
                                    instruction_id=inst.instruction_id,
                                    instrument=inst.instrument,
                                    side=side,
                                    requested_qty=float(inst.quantity),
                                    filled_qty=filled_qty,
                                    avg_exec_price=avg_price or (float(price) if price != "0" and match_price == "0" else None),
                                    status=status,
                                    reason=order_id if order_id else None,
                                    meta=inst.meta,
                                )
                            except Exception as retry_error:
                                logger.error(f"  ❌ Retry failed: {retry_error}")
                                # Fall through to original error handling
                
                logger.error(f"  ❌ WEEX API error (HTTP {e.response.status_code}): {error_msg}")
                raise Exception(f"WEEX API error: {error_msg}") from e
            except Exception:
                error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
                logger.error(f"  ❌ HTTP error: {error_msg}")
                raise Exception(error_msg) from e
        except Exception as e:
            logger.error(f"  ❌ Request error: {e}")
            raise

    async def close(self) -> None:
        """Close the HTTP client and cleanup resources."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_balance(self) -> Dict:
        """Fetch account balance from WEEX using /capi/v2/account/accounts endpoint.

        This endpoint returns comprehensive account information including:
        - account: Account configuration and settings
        - collateral: Collateral balances (this is where the actual balance is)
        - position: Current positions

        Returns:
            Balance dictionary in CCXT-compatible format:
            {
                'free': {'USDT': 1000.0, ...},
                'used': {'USDT': 0.0, ...},
                'total': {'USDT': 1000.0, ...},
                'USDT': {'free': 1000.0, 'used': 0.0, 'total': 1000.0},
                ...
            }
        """
        # Use /capi/v2/account/accounts which returns comprehensive account info
        # including collateral (balance) information
        request_path = "/capi/v2/account/accounts"
        headers = self._get_headers("GET", request_path, "", "")

        client = await self._get_client()
        try:
            response = await client.get(request_path, headers=headers)
            response.raise_for_status()
            result = response.json()
            
            logger.debug(f"WEEX accounts API response: {result}")
            
            # WEEX API returns the data directly (no code/data wrapper for this endpoint)
            # Extract collateral information which contains the balance
            collateral_list = result.get("collateral", [])
            
            # Convert to CCXT-compatible format
            balance = {"free": {}, "used": {}, "total": {}}
            
            # Map coin_id to currency symbol (common mappings)
            # Note: Weex uses coin_id, we need to map it to currency symbols
            # Common coin_id mappings: 1=BTC, 2=USDT, etc.
            coin_id_to_currency = {
                1: "BTC",
                2: "USDT",
                3: "ETH",
                # Add more mappings as needed
            }
            
            # Process collateral data
            for collateral in collateral_list:
                if not isinstance(collateral, dict):
                    continue
                
                coin_id = collateral.get("coin_id")
                currency = coin_id_to_currency.get(coin_id, f"COIN_{coin_id}")
                
                # amount is the available balance (free)
                amount = float(collateral.get("amount", 0.0) or 0.0)
                # pending amounts are considered "used" (locked)
                pending_deposit = float(collateral.get("pending_deposit_amount", 0.0) or 0.0)
                pending_withdraw = float(collateral.get("pending_withdraw_amount", 0.0) or 0.0)
                pending_transfer_in = float(collateral.get("pending_transfer_in_amount", 0.0) or 0.0)
                pending_transfer_out = float(collateral.get("pending_transfer_out_amount", 0.0) or 0.0)
                
                # Free balance is the available amount
                free = amount
                # Used balance is pending operations (though these don't actually lock the balance)
                # For Weex, we'll consider the amount as free, and used as 0 unless there's actual margin used
                used = 0.0
                total = free + used
                
                # Accumulate balances (in case there are multiple entries for same currency)
                if currency in balance["free"]:
                    balance["free"][currency] += free
                    balance["used"][currency] += used
                    balance["total"][currency] += total
                else:
                    balance["free"][currency] = free
                    balance["used"][currency] = used
                    balance["total"][currency] = total
                
                # Also store in per-currency format
                balance[currency] = {
                    "free": balance["free"][currency],
                    "used": balance["used"][currency],
                    "total": balance["total"][currency],
                }
            
            logger.info(f"Parsed WEEX balance from accounts API: {balance}")
            return balance
        except httpx.HTTPStatusError as e:
            logger.error(
                "WEEX accounts API returned error: status={}, response={}",
                e.response.status_code,
                e.response.text,
            )
            raise
        except Exception as e:
            logger.exception("Failed to fetch WEEX balance: {}", e)
            raise

    async def fetch_account_info(self) -> Dict:
        """Fetch comprehensive account information from WEEX using /capi/v2/account/accounts endpoint.

        This endpoint returns:
        - account: Account configuration and settings
        - collateral: Collateral balances (available balance)
        - position: Current positions

        Returns:
            Account information dictionary with balance details:
            {
                "account": {...},
                "collateral": [...],
                "position": [...],
                "total_equity": 1000.0,  # Sum of all collateral equity
                "total_available": 950.0,  # Sum of all collateral available
                "total_frozen": 50.0,  # Sum of all collateral frozen
            }
        """
        request_path = "/capi/v2/account/accounts"
        headers = self._get_headers("GET", request_path, "", "")

        client = await self._get_client()
        try:
            response = await client.get(request_path, headers=headers)
            response.raise_for_status()
            result = response.json()
            
            logger.debug(f"WEEX accounts API response: {result}")
            
            # Extract account information
            account_info = result.get("account", {})
            collateral_list = result.get("collateral", [])
            position_list = result.get("position", [])
            
            # Calculate totals from collateral
            total_equity = 0.0
            total_available = 0.0
            total_frozen = 0.0
            
            # Map coin_id to currency symbol
            coin_id_to_currency = {
                1: "BTC",
                2: "USDT",
                3: "ETH",
            }
            
            # Process collateral to calculate totals
            # Collateral structure from /capi/v2/account/accounts:
            # {
            #   "coin_id": 2,
            #   "amount": "949.33464697",  # Available balance
            #   "pending_deposit_amount": "0.0",
            #   "pending_withdraw_amount": "0.0",
            #   "pending_transfer_in_amount": "0.0",
            #   "pending_transfer_out_amount": "0.0",
            #   ...
            # }
            for collateral in collateral_list:
                if not isinstance(collateral, dict):
                    continue
                
                coin_id = collateral.get("coin_id")
                currency = coin_id_to_currency.get(coin_id, f"COIN_{coin_id}")
                
                # For USDT/USD/USDC, sum up the values
                if currency in ("USDT", "USD", "USDC"):
                    # amount is the available balance
                    amount = float(collateral.get("amount", 0.0) or 0.0)
                    # Calculate frozen from pending operations
                    pending_deposit = float(collateral.get("pending_deposit_amount", 0.0) or 0.0)
                    pending_withdraw = float(collateral.get("pending_withdraw_amount", 0.0) or 0.0)
                    pending_transfer_in = float(collateral.get("pending_transfer_in_amount", 0.0) or 0.0)
                    pending_transfer_out = float(collateral.get("pending_transfer_out_amount", 0.0) or 0.0)
                    frozen = pending_deposit + pending_withdraw + pending_transfer_in + pending_transfer_out
                    
                    # Equity is typically amount + frozen (total balance)
                    # But for Weex, amount is already the available balance
                    equity = amount + frozen
                    
                    total_equity += equity
                    total_available += amount
                    total_frozen += frozen
            
            account_data = {
                "account": account_info,
                "collateral": collateral_list,
                "position": position_list,
                "total_equity": total_equity,
                "total_available": total_available,
                "total_frozen": total_frozen,
            }
            
            logger.info(
                f"Fetched WEEX account info: equity={total_equity}, available={total_available}, frozen={total_frozen}"
            )
            return account_data

        except httpx.HTTPStatusError as e:
            logger.error(
                "WEEX accounts API returned error: status={}, response={}",
                e.response.status_code,
                e.response.text,
            )
            raise
        except Exception as e:
            logger.exception("Failed to fetch WEEX account info: {}", e)
            raise

    async def fetch_assets(self) -> List[Dict]:
        """Fetch account assets from WEEX using /capi/v2/account/assets endpoint.

        Returns:
            List of asset dictionaries with the following structure:
            [
                {
                    "coinId": 2,
                    "coinName": "USDT",
                    "available": "949.33464697",
                    "frozen": "0.0",
                    "equity": "999.61936697",
                    "unrealizePnl": "0.22265"
                },
                ...
            ]
        """
        request_path = "/capi/v2/account/assets"
        headers = self._get_headers("GET", request_path, "", "")

        client = await self._get_client()
        try:
            response = await client.get(request_path, headers=headers)
            response.raise_for_status()
            result = response.json()

            # WEEX API returns an array of assets directly
            assets = result if isinstance(result, list) else result.get("data", [])

            logger.info(f"Fetched {len(assets)} assets from WEEX")
            return assets

        except httpx.HTTPStatusError as e:
            logger.error(
                "WEEX assets API returned error: status={}, response={}",
                e.response.status_code,
                e.response.text,
            )
            raise
        except Exception as e:
            logger.exception("Failed to fetch WEEX assets: {}", e)
            raise

    async def fetch_positions(self, symbols: Optional[List[str]] = None) -> List[Dict]:
        """Fetch current positions from WEEX using /capi/v2/account/accounts endpoint.

        This endpoint returns comprehensive account information including positions.

        Args:
            symbols: Optional list of symbols to fetch positions for

        Returns:
            List of position dictionaries in CCXT-compatible format
        """
        # Use /capi/v2/account/accounts which includes position information
        request_path = "/capi/v2/account/accounts"
        headers = self._get_headers("GET", request_path, "", "")

        client = await self._get_client()
        try:
            response = await client.get(request_path, headers=headers)
            response.raise_for_status()
            result = response.json()

            logger.debug(f"WEEX accounts API response for positions: {result}")

            # Extract position information from the response
            positions_raw = result.get("position", [])

            # Convert to CCXT-compatible format
            positions = []
            for pos in positions_raw:
                if not isinstance(pos, dict):
                    continue

                # Map Weex position fields to CCXT-compatible format
                # Weex uses contract_id, we need to map it to symbol
                contract_id = pos.get("contract_id")
                side = pos.get("side", "").upper()  # LONG or SHORT
                size = float(pos.get("size", 0.0) or 0.0)

                # Only include non-zero positions
                if size == 0:
                    continue

                # Try to extract symbol from contract_id or other fields
                # Weex may return symbol in different formats
                symbol = pos.get("symbol") or pos.get("contract_symbol")
                if not symbol and contract_id:
                    # Try to reverse-normalize: if contract_id is like "cmt_btcusdt", extract "BTC-USDT"
                    # For now, use contract_id as fallback
                    symbol = f"CONTRACT_{contract_id}"

                # Extract additional position fields from Weex API response
                entry_price = pos.get("open_price") or pos.get("entry_price") or pos.get("avg_price")
                mark_price = pos.get("mark_price") or pos.get("current_price")
                unrealized_pnl = pos.get("unrealized_pnl") or pos.get("unrealizedPnl") or pos.get("pnl")
                leverage = pos.get("leverage") or pos.get("leverage_ratio") or "1"
                margin_mode = pos.get("margin_mode") or pos.get("marginMode") or ""
                open_value = pos.get("open_value") or pos.get("position_value") or pos.get("notional")
                isolated_margin = pos.get("isolated_margin") or pos.get("isolatedMargin") or pos.get("margin")
                liquidation_price = pos.get("liquidation_price") or pos.get("liquidationPrice")

                # Convert to CCXT format
                position = {
                    "symbol": symbol,
                    "contract_id": contract_id,
                    "side": side,
                    "quantity": size if side == "LONG" else -size,  # Negative for short
                    "size": size,
                    "leverage": leverage,
                    "margin_mode": margin_mode,
                    "open_value": float(open_value or 0.0),
                    "isolated_margin": float(isolated_margin or 0.0),
                    "unrealized_pnl": float(unrealized_pnl or 0.0),
                    "entry_price": float(entry_price or 0.0),
                    "mark_price": float(mark_price or 0.0),
                    "liquidation_price": float(liquidation_price or 0.0) if liquidation_price else None,
                    "info": pos,  # Keep raw data for reference
                }

                positions.append(position)
                
                # Log position details for debugging
                logger.debug(
                    "Position: symbol={}, side={}, size={}, entry_price={}, mark_price={}, pnl={}",
                    symbol,
                    side,
                    size,
                    entry_price,
                    mark_price,
                    unrealized_pnl,
                )

            # Filter by symbols if provided
            if symbols:
                normalized_symbols = [self._normalize_symbol(s) for s in symbols]
                # Note: We may need to map contract_id to symbol for filtering
                # For now, return all positions if symbols are provided
                pass

            logger.info(f"Fetched {len(positions)} positions from WEEX")
            return positions

        except httpx.HTTPStatusError as e:
            logger.error(
                "WEEX accounts API returned error when fetching positions: status={}, response={}",
                e.response.status_code,
                e.response.text,
            )
            raise
        except Exception as e:
            logger.exception("Failed to fetch WEEX positions: {}", e)
            raise

    async def cancel_order(
        self, order_id: str, symbol: str, client_oid: Optional[str] = None
    ) -> Dict:
        """Cancel an open order.

        Args:
            order_id: Order ID to cancel (optional if client_oid is provided)
            symbol: Symbol of the order
            client_oid: Client order ID (optional if order_id is provided)

        Returns:
            Cancellation result dictionary

        Raises:
            ValueError: If neither order_id nor client_oid is provided
        """
        if not order_id and not client_oid:
            raise ValueError("Either order_id or client_oid must be provided")

        symbol = self._normalize_symbol(symbol)

        request_body = {"symbol": symbol}
        if order_id:
            request_body["orderId"] = order_id
        if client_oid:
            request_body["clientOid"] = client_oid

        body_str = json.dumps(request_body, separators=(",", ":"))
        request_path = "/capi/v2/order/cancel_order"

        headers = self._get_headers("POST", request_path, body_str, "")

        client = await self._get_client()
        logger.info(f"  🚫 Canceling order: symbol={symbol}, order_id={order_id}, client_oid={client_oid}")

        try:
            response = await client.post(
                request_path,
                headers=headers,
                content=body_str,
            )
            response.raise_for_status()
            result = response.json()

            # Handle wrapped response
            if isinstance(result, dict) and "data" in result:
                result = result["data"]

            # Check for error code
            if isinstance(result, dict) and "code" in result and result.get("code") != 0:
                error_msg = result.get("msg", "Unknown error")
                logger.error(f"  ❌ WEEX API error: {error_msg}")
                raise Exception(f"WEEX API error: {error_msg}")

            logger.info(f"  ✓ Cancel result: {result.get('result')}, order_id={result.get('order_id') or result.get('orderId')}")
            return result

        except httpx.HTTPStatusError as e:
            # Try to parse error message from response
            try:
                error_data = e.response.json()
                error_msg = error_data.get("msg", error_data.get("message", e.response.text))
                logger.error(f"  ❌ WEEX API error (HTTP {e.response.status_code}): {error_msg}")
                raise Exception(f"WEEX API error: {error_msg}") from e
            except Exception:
                error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
                logger.error(f"  ❌ HTTP error canceling order: {error_msg}")
                raise Exception(error_msg) from e
        except Exception as e:
            logger.error(f"  ❌ Error canceling order: {e}")
            raise

    async def fetch_order(self, order_id: str, symbol: Optional[str] = None) -> Optional[Dict]:
        """Fetch order information by order ID.

        Args:
            order_id: Order ID to fetch
            symbol: Optional symbol (not required by WEEX API but kept for compatibility)

        Returns:
            Order information dictionary, or None if not found
        """
        request_path = "/capi/v2/order/detail"
        query_string = f"orderId={order_id}"
        headers = self._get_headers("GET", request_path, "", query_string)

        client = await self._get_client()
        logger.debug(f"  📋 Fetching order info: order_id={order_id}")

        try:
            full_path = f"{request_path}?{query_string}"
            response = await client.get(full_path, headers=headers)
            response.raise_for_status()
            result = response.json()

            # WEEX API may return data wrapped in a response structure
            # Handle both direct response and wrapped response: {"code": 0, "data": {...}}
            if isinstance(result, dict):
                code = result.get("code")
                is_success = (
                    code == 0
                    or code == "0"
                    or code == "00000"
                    or (isinstance(code, str) and code.startswith("00000"))
                )
                if is_success and "data" in result:
                    # Extract data from wrapped response
                    order_data = result.get("data")
                    return order_data if order_data else None
                elif is_success or "order_id" in result or "orderId" in result:
                    # Direct order data
                    return result
                else:
                    # Error response
                    error_msg = result.get("msg", "Unknown error")
                    logger.error(f"  ❌ WEEX API error: {error_msg}")
                    return None
            else:
                return result if result else None

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"  ⚠️ Order not found: {order_id}")
                return None
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            logger.error(f"  ❌ HTTP error fetching order: {error_msg}")
            raise Exception(error_msg) from e
        except Exception as e:
            logger.error(f"  ❌ Error fetching order: {e}")
            raise

    async def fetch_ticker(self, symbol: str) -> Dict:
        """Fetch ticker (24h ticker) for a symbol from WEEX.

        Args:
            symbol: Symbol in format 'BTC-USDT' or 'BTC/USDT'

        Returns:
            Ticker dictionary in CCXT-compatible format
        """
        normalized_symbol = self._normalize_symbol(symbol)
        # WEEX public API endpoint for ticker (no authentication required)
        # Using public API endpoint: /capi/v2/market/ticker
        request_path = "/capi/v2/market/ticker"
        query_string = f"symbol={normalized_symbol}"
        
        # For public endpoints, create a new client without authentication
        # or use the existing client but don't add auth headers
        try:
            # Create a temporary client for public API calls
            async with httpx.AsyncClient(base_url=self.BASE_URL, timeout=10.0) as public_client:
                response = await public_client.get(f"{request_path}?{query_string}")
                response.raise_for_status()
                result = response.json()
        except Exception as e:
            logger.error("Failed to fetch WEEX ticker (public API): {}", e)
            raise
        
        # WEEX returns: {"code": 0, "data": {...}} or {"code": "00000", "data": {...}}
        # Handle both numeric and string code values
        code = result.get("code") if isinstance(result, dict) else None
        is_success = (
            code == 0
            or code == "0"
            or code == "00000"
            or (isinstance(code, str) and code.startswith("00000"))
        )
        
        if isinstance(result, dict) and is_success:
            data = result.get("data", {})
        elif isinstance(result, dict) and "data" in result:
            # Try to extract data even if code is not 0
            data = result.get("data", {})
        else:
            data = result if isinstance(result, dict) else {}
        
        # Check if we have valid data
        if not data or (isinstance(data, dict) and not any(data.values())):
            logger.warning(
                "WEEX ticker API returned empty or invalid data for {}: {}",
                symbol,
                result,
            )
            # Return a minimal ticker with current timestamp
            return {
                "symbol": symbol.replace("-", "/"),
                "timestamp": int(time.time() * 1000),
                "last": 0.0,
                "info": data or {},
            }
        
        # Convert to CCXT-compatible ticker format
        # WEEX ticker format: data contains last, best_ask, best_bid, high_24h, low_24h, volume_24h, etc.
        last_price = float(data.get("lastPrice", data.get("last", data.get("price", 0.0))) or 0.0)
        ticker = {
            "symbol": symbol.replace("-", "/"),
            "timestamp": int(data.get("timestamp", time.time() * 1000)),
            "datetime": None,
            "last": last_price,
            "open": float(data.get("openPrice", data.get("open", 0.0)) or 0.0),  # May be 0 if not available
            "high": float(data.get("highPrice", data.get("high_24h", data.get("high", 0.0))) or 0.0),
            "low": float(data.get("lowPrice", data.get("low_24h", data.get("low", 0.0))) or 0.0),
            "close": last_price,  # Use last price as close
            "bid": float(data.get("best_bid", data.get("bid", 0.0)) or 0.0),
            "ask": float(data.get("best_ask", data.get("ask", 0.0)) or 0.0),
            "change": float(data.get("priceChange", data.get("change", 0.0)) or 0.0),
            "percentage": float(data.get("priceChangePercent", data.get("changePercent", data.get("priceChangePercent", 0.0))) or 0.0),
            "baseVolume": float(data.get("base_volume", data.get("volume", data.get("baseVolume", 0.0))) or 0.0),
            "quoteVolume": float(data.get("volume_24h", data.get("quoteVolume", data.get("turnover", 0.0))) or 0.0),
            "info": data,
        }
        
        logger.info(
            "Fetched WEEX ticker for {}: last={}, volume={}",
            symbol,
            ticker["last"],
            ticker["baseVolume"],
        )
        return ticker

    def _normalize_timeframe(self, timeframe: str) -> str:
        """Convert CCXT timeframe to WEEX kline interval format.
        
        WEEX supports: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1M
        CCXT timeframes: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1M
        
        Args:
            timeframe: CCXT timeframe string (e.g., "1m", "5m", "1h")
            
        Returns:
            WEEX interval string
        """
        # Map common timeframes
        timeframe_map = {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
            "4h": "4h",
            "1d": "1d",
            "1w": "1w",
            "1M": "1M",
        }
        return timeframe_map.get(timeframe, "1m")

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str = "1m", since: Optional[int] = None, limit: int = 100
    ) -> List[List]:
        """Fetch OHLCV (candles) data from WEEX.

        Args:
            symbol: Symbol in format 'BTC-USDT' or 'BTC/USDT'
            timeframe: Candle interval (e.g., "1m", "5m", "1h", "1d")
            since: Timestamp in milliseconds (optional, for pagination)
            limit: Number of candles to fetch (default 100, max 1000)

        Returns:
            List of OHLCV candles in CCXT format: [[timestamp, open, high, low, close, volume], ...]
        """
        normalized_symbol = self._normalize_symbol(symbol)
        weex_interval = self._normalize_timeframe(timeframe)
        
        # WEEX public API endpoint for candles: /capi/v2/market/candles
        # Parameters: symbol, granularity (not interval), limit, startTime, endTime
        request_path = "/capi/v2/market/candles"
        params = {
            "symbol": normalized_symbol,
            "granularity": weex_interval,  # WEEX uses "granularity" not "interval"
            "limit": min(limit, 1000),
        }
        if since:
            params["startTime"] = since
            # Optionally add endTime if needed (defaults to current time)
        
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        
        try:
            # Create a temporary client for public API calls
            async with httpx.AsyncClient(base_url=self.BASE_URL, timeout=10.0) as public_client:
                response = await public_client.get(f"{request_path}?{query_string}")
                response.raise_for_status()
                result = response.json()
        except Exception as e:
            logger.error(
                "Failed to fetch WEEX OHLCV (public API) for {}: {}", symbol, e
            )
            raise
        
        # WEEX candles API returns: [[timestamp, open, high, low, close, volume, amount], ...]
        # Direct array format, not wrapped in an object
        if isinstance(result, list):
            klines = result
        elif isinstance(result, dict):
            # Handle wrapped response format if present
            code = result.get("code")
            is_success = (
                code == 0
                or code == "0"
                or code == "00000"
                or (isinstance(code, str) and code.startswith("00000"))
            )
            if is_success and "data" in result:
                klines = result["data"] if isinstance(result["data"], list) else []
            elif "data" in result:
                klines = result["data"] if isinstance(result["data"], list) else []
            else:
                klines = []
        else:
            klines = []
        
        if not klines:
            logger.warning(
                "WEEX candles API returned empty data for {} (granularity: {}): {}",
                symbol,
                timeframe,
                result,
            )
        
        # Convert WEEX kline format to CCXT format
        # WEEX format: [timestamp, open, high, low, close, volume, ...]
        # CCXT format: [timestamp, open, high, low, close, volume]
        candles = []
        for kline in klines:
            if isinstance(kline, list) and len(kline) >= 6:
                candles.append([
                    int(kline[0]),  # timestamp
                    float(kline[1]),  # open
                    float(kline[2]),  # high
                    float(kline[3]),  # low
                    float(kline[4]),  # close
                    float(kline[5]),  # volume
                ])
        
        logger.debug(
            "Fetched {} WEEX candles for {} (interval: {}, limit: {})",
            len(candles),
            symbol,
            timeframe,
            limit,
        )
        return candles

    async def fetch_open_orders(
        self, symbol: Optional[str] = None, limit: int = 100, page: int = 0
    ) -> List[Dict]:
        """Fetch current open orders.

        Args:
            symbol: Optional symbol to filter orders
            limit: Number of orders to fetch (default 100, max 100)
            page: Page number (default 0)

        Returns:
            List of open order dictionaries
        """
        params = {"limit": min(limit, 100), "page": page}
        if symbol:
            params["symbol"] = self._normalize_symbol(symbol)

        # Build query string
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        request_path = "/capi/v2/order/current"

        headers = self._get_headers("GET", request_path, "", query_string)

        client = await self._get_client()
        logger.debug(f"  📋 Fetching open orders: symbol={symbol}, limit={limit}, page={page}")

        try:
            full_path = f"{request_path}?{query_string}"
            response = await client.get(full_path, headers=headers)
            response.raise_for_status()
            result = response.json()

            # WEEX API may return data wrapped in a response structure
            # Handle both direct list and wrapped response: {"code": 0, "data": [...]}
            if isinstance(result, dict):
                code = result.get("code")
                is_success = (
                    code == 0
                    or code == "0"
                    or code == "00000"
                    or (isinstance(code, str) and code.startswith("00000"))
                )
                if is_success and "data" in result:
                    orders = result.get("data", [])
                elif isinstance(result.get("data"), list):
                    orders = result.get("data", [])
                else:
                    orders = []
            elif isinstance(result, list):
                orders = result
            else:
                orders = []

            logger.info(f"Fetched {len(orders)} open orders from WEEX")
            return orders

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            logger.error(f"  ❌ HTTP error fetching open orders: {error_msg}")
            raise Exception(error_msg) from e
        except Exception as e:
            logger.error(f"  ❌ Error fetching open orders: {e}")
            raise

    def _map_weex_status_to_tx_status(self, weex_status: str) -> TxStatus:
        """Map WEEX order status to TxStatus.

        Args:
            weex_status: WEEX order status string

        Returns:
            Corresponding TxStatus
        """
        status_lower = weex_status.lower()
        if status_lower == "filled":
            return TxStatus.FILLED
        elif status_lower in ("canceled", "canceling"):
            return TxStatus.REJECTED
        elif status_lower in ("pending", "open"):
            return TxStatus.PARTIAL  # Pending orders are treated as PARTIAL
        else:
            return TxStatus.PARTIAL  # Unknown status treated as PARTIAL

    def __repr__(self) -> str:
        mode = "testnet" if self.testnet else "live"
        return (
            f"WeexExecutionGateway(type={self.default_type}, "
            f"margin={self.margin_mode}, mode={mode})"
        )

