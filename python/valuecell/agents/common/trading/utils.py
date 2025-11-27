import os
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import ccxt.pro as ccxtpro
import httpx
from loguru import logger
from valuecell.utils.ts import get_current_timestamp_ms

if TYPE_CHECKING:
    from valuecell.agents.common.trading.models import TradeInstruction, TxResult

from valuecell.agents.common.trading.constants import (
    FEATURE_GROUP_BY_KEY,
    FEATURE_GROUP_BY_MARKET_SNAPSHOT,
)
from valuecell.agents.common.trading.models import FeatureVector


async def fetch_free_cash_from_gateway(
    execution_gateway, symbols: list[str]
) -> Tuple[float, float]:
    """Fetch exchange balance via `execution_gateway.fetch_balance()` or
    `execution_gateway.fetch_assets()` (for Weex) and aggregate free cash
    for the given `symbols` (quote currencies).

    For Weex exchange, prefer `fetch_assets()` which provides more accurate
    available balance from `/capi/v2/account/assets` endpoint.

    Returns aggregated free cash as float. Returns 0.0 on error or when
    balance shape cannot be parsed.
    """
    logger.info("Fetching exchange balance for LIVE trading mode")
    
    # For Weex, prefer fetch_assets() which provides more accurate available balance
    if hasattr(execution_gateway, "exchange_id") and execution_gateway.exchange_id == "weex":
        if hasattr(execution_gateway, "fetch_assets"):
            try:
                logger.info("Using fetch_assets() for Weex exchange to get accurate available balance")
                assets = await execution_gateway.fetch_assets()
                
                # Extract available and equity from assets
                free_map: dict[str, float] = {}
                equity_map: dict[str, float] = {}
                
                for asset in assets:
                    coin_name = str(asset.get("coinName", "")).upper()
                    available = float(asset.get("available", 0.0) or 0.0)
                    equity = float(asset.get("equity", 0.0) or 0.0)
                    
                    if coin_name:
                        free_map[coin_name] = available
                        equity_map[coin_name] = equity
                
                logger.info(f"Parsed Weex assets - free_map: {free_map}, equity_map: {equity_map}")
                
                # Derive quote currencies from symbols
                quotes: list[str] = []
                for sym in symbols or []:
                    s = str(sym).upper()
                    if "/" in s and len(s.split("/")) == 2:
                        quotes.append(s.split("/")[1])
                    elif "-" in s and len(s.split("-")) == 2:
                        quotes.append(s.split("-")[1])
                
                quotes = list(dict.fromkeys(quotes))
                if not quotes:
                    quotes = ["USDT", "USD", "USDC"]
                
                logger.info(f"Quote currencies from symbols: {quotes}")
                
                free_cash = 0.0
                total_cash = 0.0
                
                for q in quotes:
                    free_cash += float(free_map.get(q, 0.0) or 0.0)
                    total_cash += float(equity_map.get(q, 0.0) or 0.0)
                
                logger.info(
                    f"Synced balance from Weex assets API: free_cash={free_cash}, total_cash={total_cash}, quotes={quotes}"
                )
                
                return float(free_cash), float(total_cash)
            except Exception as e:
                logger.warning(
                    "Failed to fetch assets from Weex, falling back to fetch_balance(): {}",
                    e,
                )
                # Fall through to fetch_balance()
    
    # Standard balance fetching for other exchanges or Weex fallback
    try:
        if not hasattr(execution_gateway, "fetch_balance"):
            logger.warning(
                "Execution gateway does not have fetch_balance method, returning 0.0"
            )
            return 0.0, 0.0
        balance = await execution_gateway.fetch_balance()
    except Exception as e:
        logger.exception(
            "Failed to fetch balance from execution gateway: {}. Returning 0.0",
            e,
        )
        return 0.0, 0.0

    logger.info(f"Raw balance response: {balance}")
    free_map: dict[str, float] = {}
    # ccxt balance may be shaped as: {'free': {...}, 'used': {...}, 'total': {...}}
    try:
        free_section = balance.get("free") if isinstance(balance, dict) else None
    except Exception:
        free_section = None

    if isinstance(free_section, dict):
        free_map = {str(k).upper(): float(v or 0.0) for k, v in free_section.items()}
    else:
        # fallback: per-ccy dicts: balance['USDT'] = {'free': x, 'used': y, 'total': z}
        iterable = balance.items() if isinstance(balance, dict) else []
        for k, v in iterable:
            if isinstance(v, dict) and "free" in v:
                try:
                    free_map[str(k).upper()] = float(v.get("free") or 0.0)
                except Exception:
                    continue

    logger.info(f"Parsed free balance map: {free_map}")
    # Derive quote currencies from symbols, fallback to common USD-stable quotes
    quotes: list[str] = []
    for sym in symbols or []:
        s = str(sym).upper()
        if "/" in s and len(s.split("/")) == 2:
            quotes.append(s.split("/")[1])
        elif "-" in s and len(s.split("-")) == 2:
            quotes.append(s.split("-")[1])

    # Deduplicate preserving order
    quotes = list(dict.fromkeys(quotes))
    logger.info(f"Quote currencies from symbols: {quotes}")

    free_cash = 0.0
    total_cash = 0.0

    # Sum up free and total cash from relevant quote currencies
    if quotes:
        for q in quotes:
            free_cash += float(free_map.get(q, 0.0) or 0.0)
            # Try to find total/equity in balance if available (often 'total' dict in CCXT)
            # Hyperliquid/CCXT structure: balance[q]['total']
            q_data = balance.get(q)
            if isinstance(q_data, dict):
                total_cash += float(q_data.get("total", 0.0) or 0.0)
            else:
                # Fallback if structure is flat or missing
                total_cash += float(free_map.get(q, 0.0) or 0.0)
    else:
        for q in ("USDT", "USD", "USDC"):
            free_cash += float(free_map.get(q, 0.0) or 0.0)
            q_data = balance.get(q)
            if isinstance(q_data, dict):
                total_cash += float(q_data.get("total", 0.0) or 0.0)
            else:
                total_cash += float(free_map.get(q, 0.0) or 0.0)

    logger.debug(
        f"Synced balance from exchange: free_cash={free_cash}, total_cash={total_cash}, quotes={quotes}"
    )

    return float(free_cash), float(total_cash)


def extract_market_snapshot_features(
    features: List[FeatureVector],
) -> List[FeatureVector]:
    """Extract market snapshot feature vectors for a specific exchange.

    Args:
        features: List of FeatureVector objects.
    Returns:
        List of FeatureVector objects filtered by market snapshot group.
    """
    snapshot_features: List[FeatureVector] = []

    for item in features:
        if not isinstance(item, FeatureVector):
            continue

        meta = item.meta or {}
        group_key = meta.get(FEATURE_GROUP_BY_KEY)
        if group_key != FEATURE_GROUP_BY_MARKET_SNAPSHOT:
            continue

        snapshot_features.append(item)

    return snapshot_features


def extract_price_map(features: List[FeatureVector]) -> Dict[str, float]:
    """Extract symbol -> price map from market snapshot feature vectors."""

    price_map: Dict[str, float] = {}

    for item in features:
        if not isinstance(item, FeatureVector):
            continue

        meta = item.meta or {}
        group_key = meta.get(FEATURE_GROUP_BY_KEY)
        if group_key != FEATURE_GROUP_BY_MARKET_SNAPSHOT:
            continue

        instrument = getattr(item, "instrument", None)
        symbol = getattr(instrument, "symbol", None)
        if not symbol:
            continue

        values = item.values or {}
        price = (
            values.get("price.last")
            or values.get("price.close")
            or values.get("price.mark")
            or values.get("funding.mark_price")
        )
        if price is None:
            continue

        try:
            price_map[symbol] = float(price)
        except (TypeError, ValueError):
            logger.warning("Failed to parse feature price for {}", symbol)

    return price_map


def normalize_symbol(symbol: str) -> str:
    """Normalize symbol format for CCXT.

    Examples:
        BTC-USD -> BTC/USD:USD (spot)
        BTC-USDT -> BTC/USDT:USDT (USDT futures on colon exchanges)
        ETH-USD -> ETH/USD:USD (USD futures on colon exchanges)

    Args:
        symbol: Symbol in format 'BTC-USD', 'BTC-USDT', etc.

    Returns:
        Normalized CCXT symbol
    """
    # Replace dash with slash
    base_symbol = symbol.replace("-", "/")

    if ":" not in base_symbol:
        parts = base_symbol.split("/")
        if len(parts) == 2:
            base_symbol = f"{parts[0]}/{parts[1]}:{parts[1]}"

    return base_symbol


def get_exchange_cls(exchange_id: str):
    """Get CCXT exchange class by exchange ID.
    
    Returns None if exchange is not found in ccxt.pro (e.g., custom exchanges like Weex).
    """
    exchange_cls = getattr(ccxtpro, exchange_id, None)
    return exchange_cls


async def report_trade_order(
    strategy_id: str,
    model_provider: str,
    model_id: str,
    rationale: Optional[str],
    instruction: "TradeInstruction",
    tx_result: "TxResult",
    order_id: Optional[str] = None,
    webhook_url: Optional[str] = None,
    timeout: float = 10.0,
) -> bool:
    """Report trade order to external webhook API.

    This function sends trade order information including AI decision rationale
    and execution results to an external reporting endpoint.

    Args:
        strategy_id: Strategy identifier
        model_provider: LLM model provider (e.g., 'openrouter', 'google')
        model_id: LLM model identifier (e.g., 'deepseek-ai/deepseek-v3.1')
        rationale: AI decision rationale/reasoning
        instruction: Trade instruction that was executed
        tx_result: Transaction result from execution
        order_id: Exchange order ID (if available)
        webhook_url: Optional webhook URL to override environment variable
        timeout: Request timeout in seconds

    Returns:
        True if report was sent successfully, False otherwise
    """
    if webhook_url is None:
        webhook_url = os.getenv("TRADE_ORDER_REPORT_WEBHOOK_URL")

    if not webhook_url:
        logger.debug("TRADE_ORDER_REPORT_WEBHOOK_URL not set, skipping trade order report")
        return False

    try:
        # Prepare report payload
        payload = {
            "strategy_id": strategy_id,
            "timestamp_ms": get_current_timestamp_ms(),
            "ai_info": {
                "model_provider": model_provider,
                "model_id": model_id,
            },
            "decision_rationale": rationale or "",
            "order_info": {
                "instruction_id": instruction.instruction_id,
                "compose_id": instruction.compose_id,
                "symbol": instruction.instrument.symbol,
                "side": instruction.side.value if hasattr(instruction.side, "value") else str(instruction.side),
                "action": instruction.action.value if instruction.action and hasattr(instruction.action, "value") else None,
                "quantity": instruction.quantity,
                "leverage": instruction.leverage,
                "price_mode": instruction.price_mode.value if hasattr(instruction.price_mode, "value") else str(instruction.price_mode),
                "limit_price": instruction.limit_price,
            },
            "execution_result": {
                "order_id": order_id or tx_result.reason,  # Use reason field if order_id not available
                "status": tx_result.status.value if hasattr(tx_result.status, "value") else str(tx_result.status),
                "requested_qty": tx_result.requested_qty,
                "filled_qty": tx_result.filled_qty,
                "avg_exec_price": tx_result.avg_exec_price,
                "fee_cost": tx_result.fee_cost,
                "slippage_bps": tx_result.slippage_bps,
            },
        }

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(webhook_url, headers=headers, json=payload)
            resp.raise_for_status()
            logger.info(
                "Successfully reported trade order: strategy_id={}, symbol={}, order_id={}",
                strategy_id,
                instruction.instrument.symbol,
                order_id or tx_result.reason,
            )
            return True

    except httpx.HTTPStatusError as e:
        logger.warning(
            "Failed to report trade order (HTTP {}): {}",
            e.response.status_code,
            e.response.text,
        )
        return False
    except Exception as e:
        logger.warning("Failed to report trade order: {}", e, exc_info=True)
        return False


async def send_discord_message(
    content: str,
    webhook_url: Optional[str] = None,
    *,
    raise_for_status: bool = True,
    timeout: float = 10.0,
) -> str:
    """Send a message to Discord via webhook asynchronously.

    Reads the webhook URL from the environment variable
    `STRATEGY_AGENT_DISCORD_WEBHOOK_URL` when `webhook_url` is not provided.

    Args:
        content: The message content to send.
        webhook_url: Optional webhook URL to override the environment variable.
        raise_for_status: If True, raise on non-2xx responses.
        timeout: Request timeout in seconds.

    Returns:
        The response body as text.

    Raises:
        ValueError: If no webhook URL is provided or available in env.
        ImportError: If `httpx` is not installed.
        httpx.HTTPStatusError: If `raise_for_status` is True and the response is an HTTP error.
    """
    if webhook_url is None:
        webhook_url = os.getenv("STRATEGY_AGENT_DISCORD_WEBHOOK_URL")

    if not webhook_url:
        raise ValueError(
            "Discord webhook URL not provided and STRATEGY_AGENT_DISCORD_WEBHOOK_URL is not set"
        )

    headers = {
        "Accept": "text",
        "Content-Type": "application/json",
    }
    payload = {"content": content}

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(webhook_url, headers=headers, json=payload)
        if raise_for_status:
            resp.raise_for_status()
        return resp.text


def prune_none(obj):
    """Recursively remove None, empty dict, and empty list values."""
    if isinstance(obj, dict):
        pruned = {k: prune_none(v) for k, v in obj.items() if v is not None}
        return {k: v for k, v in pruned.items() if v not in (None, {}, [])}
    if isinstance(obj, list):
        pruned = [prune_none(v) for v in obj]
        return [v for v in pruned if v not in (None, {}, [])]
    return obj


def extract_market_section(market_data: List[Dict]) -> Dict:
    """Extract decision-critical metrics from market feature entries."""
    
    if not market_data:
        logger.warning("extract_market_section: market_data is empty")
        return {}

    compact: Dict[str, Dict] = {}
    for item in market_data:
        if not isinstance(item, dict):
            logger.warning("extract_market_section: skipping non-dict item: {}", type(item))
            continue
            
        symbol = (item.get("instrument") or {}).get("symbol")
        if not symbol:
            logger.debug("extract_market_section: skipping item without symbol: {}", item.keys())
            continue

        values = item.get("values") or {}
        if not values:
            logger.warning("extract_market_section: skipping item with empty values for {}", symbol)
            continue
            
        entry: Dict[str, float] = {}

        for feature_key, alias in (
            ("price.last", "last"),
            ("price.close", "close"),
            ("price.open", "open"),
            ("price.high", "high"),
            ("price.low", "low"),
            ("price.bid", "bid"),
            ("price.ask", "ask"),
            ("price.change_pct", "change_pct"),
            ("price.volume", "volume"),
        ):
            if feature_key in values and values[feature_key] is not None:
                try:
                    val_float = float(values[feature_key])
                    # Include all values, even if 0 (0 is a valid price/volume)
                    # Only skip if it's truly None or invalid
                    entry[alias] = val_float
                except (TypeError, ValueError) as e:
                    logger.debug(
                        "extract_market_section: failed to convert {} for {}: {} (error: {})",
                        feature_key,
                        symbol,
                        values[feature_key],
                        e,
                    )

        if values.get("open_interest") is not None:
            try:
                entry["open_interest"] = float(values["open_interest"])
            except (TypeError, ValueError):
                pass

        if values.get("funding.rate") is not None:
            try:
                entry["funding_rate"] = float(values["funding.rate"])
            except (TypeError, ValueError):
                pass
        if values.get("funding.mark_price") is not None:
            try:
                entry["mark_price"] = float(values["funding.mark_price"])
            except (TypeError, ValueError):
                pass

        # Keep all values including 0 (0 is valid for prices/volumes)
        # Only filter out None values
        normalized = {k: v for k, v in entry.items() if v is not None}
        if normalized:
            compact[symbol] = normalized
            logger.debug(
                "extract_market_section: extracted {} values for {}: {}",
                len(normalized),
                symbol,
                list(normalized.keys()),
            )
        else:
            logger.warning(
                "extract_market_section: no valid values extracted for {}. "
                "Available feature keys in values: {}",
                symbol,
                list(values.keys()) if values else [],
            )

    if not compact:
        logger.warning(
            "extract_market_section: no market data extracted from {} items. "
            "This will cause 'No market features provided' error.",
            len(market_data),
        )
        if market_data:
            # Log first item structure for debugging
            first_item = market_data[0]
            if isinstance(first_item, dict):
                values_dict = first_item.get("values", {})
                logger.warning(
                    "  First item structure: keys={}, instrument={}, values_keys={}, values_sample={}",
                    list(first_item.keys()),
                    first_item.get("instrument"),
                    list(values_dict.keys()) if isinstance(values_dict, dict) else "N/A",
                    {k: v for k, v in list(values_dict.items())[:5]} if isinstance(values_dict, dict) else "N/A",
                )
            else:
                logger.warning("  First item is not a dict: {}", type(first_item))
    else:
        logger.info("extract_market_section: extracted market data for {} symbols: {}", len(compact), list(compact.keys()))

    return compact


def group_features(features: List[FeatureVector]) -> Dict:
    """Organize features by grouping metadata and trim payload noise.

    Prefers the FeatureVector.meta group_by_key when present, otherwise
    falls back to the interval tag. This allows callers to introduce
    ad-hoc groupings (e.g., market snapshots) without overloading the
    interval field.
    """
    grouped: Dict[str, List] = {}

    for fv in features:
        data = fv.model_dump(mode="json")
        meta = data.get("meta") or {}
        group_key = meta.get(FEATURE_GROUP_BY_KEY)

        if not group_key:
            continue

        grouped.setdefault(group_key, []).append(data)

    return grouped
