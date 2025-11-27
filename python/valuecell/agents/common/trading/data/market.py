from collections import defaultdict
from typing import TYPE_CHECKING, List, Optional

from loguru import logger

from valuecell.agents.common.trading.models import (
    Candle,
    InstrumentRef,
    MarketSnapShotType,
)
from valuecell.agents.common.trading.utils import get_exchange_cls, normalize_symbol
from valuecell.utils.i18n_utils import detect_user_region

if TYPE_CHECKING:
    from valuecell.agents.common.trading.execution.interfaces import BaseExecutionGateway

from .interfaces import BaseMarketDataSource


class SimpleMarketDataSource(BaseMarketDataSource):
    """Generates synthetic candle data for each symbol or fetches via ccxt.pro.

    If `exchange_id` was provided at construction time and `ccxt.pro` is
    available, this class will attempt to fetch OHLCV data from the
    specified exchange. If any error occurs (missing library, unknown
    exchange, network error), it falls back to the built-in synthetic
    generator so the runtime remains functional in tests and offline.
    """

    def __init__(
        self,
        exchange_id: Optional[str] = None,
        execution_gateway: Optional["BaseExecutionGateway"] = None,
    ) -> None:
        if not exchange_id:
            # Auto-detect region and select appropriate exchange
            region = detect_user_region()
            if region == "us":
                # Use OKX for United States users (best support for USDT perpetuals)
                self._exchange_id = "okx"
                logger.info(
                    "Detected US region, using okx exchange (USDT perpetuals supported)"
                )
            else:
                # Use regular Binance for other regions
                self._exchange_id = "binance"
                logger.info("Detected non-US region, using binance exchange")
        else:
            self._exchange_id = exchange_id
        self._execution_gateway = execution_gateway

    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol format for specific exchanges.

        For Hyperliquid: converts BTC-USDC to BTC/USDC:USDC (swap format)
        For other exchanges: converts BTC-USDC to BTC/USDC:USDC

        Args:
            symbol: Symbol in format 'BTC-USDC', 'ETH-USDT', etc.

        Returns:
            Normalized CCXT symbol for the specific exchange
        """
        # Replace dash with slash
        base_symbol = symbol.replace("-", "/")

        # For most exchanges (especially those requiring settlement currency)
        if ":" not in base_symbol:
            parts = base_symbol.split("/")
            if len(parts) == 2:
                # Add settlement currency (e.g., BTC/USDC -> BTC/USDC:USDC)
                base_symbol = f"{parts[0]}/{parts[1]}:{parts[1]}"

        return base_symbol

    def _get_fallback_interval(self, interval: str) -> Optional[str]:
        """Get a fallback interval if the requested interval is not supported.
        
        Some exchanges (like Binance) don't support 1s intervals. This method
        provides a fallback to a supported interval.
        
        Args:
            interval: Requested interval (e.g., "1s", "1m")
            
        Returns:
            Fallback interval or None if no fallback is available
        """
        # Map unsupported intervals to fallback intervals
        fallback_map = {
            "1s": "1m",  # Fallback 1s to 1m for exchanges that don't support 1s
        }
        return fallback_map.get(interval)

    async def get_recent_candles(
        self, symbols: List[str], interval: str, lookback: int
    ) -> List[Candle]:
        async def _fetch(symbol: str, normalized_symbol: str) -> List[List]:
            # instantiate exchange class by name (e.g., ccxtpro.kraken)
            exchange_cls = get_exchange_cls(self._exchange_id)
            if exchange_cls is None:
                # Exchange not found in ccxt.pro (e.g., custom exchanges like Weex)
                # Try to fetch candles via execution gateway if available
                if self._execution_gateway:
                    logger.info(
                        "Exchange '{}' not found in ccxt.pro, trying execution gateway to fetch candles",
                        self._exchange_id,
                    )
                    try:
                        if hasattr(self._execution_gateway, "fetch_ohlcv"):
                            data = await self._execution_gateway.fetch_ohlcv(
                                symbol, timeframe=interval, since=None, limit=lookback
                            )
                            logger.info(
                                "Successfully fetched {} candles for {} (interval: {}) via execution gateway",
                                len(data),
                                symbol,
                                interval,
                            )
                            return data
                        else:
                            logger.warning(
                                "Execution gateway for '{}' does not support fetch_ohlcv method",
                                self._exchange_id,
                            )
                    except Exception as e:
                        logger.warning(
                            "Failed to fetch candles via execution gateway for {} ({}): {}",
                            symbol,
                            self._exchange_id,
                            e,
                        )
                else:
                    logger.warning(
                        "Exchange '{}' not found in ccxt.pro and no execution gateway available. "
                        "Cannot fetch candles. This may cause trading decisions to fail.",
                        self._exchange_id,
                    )
                return []
            
            exchange = exchange_cls({"newUpdates": False})
            try:
                # ccxt.pro uses async fetch_ohlcv with normalized symbol
                data = await exchange.fetch_ohlcv(
                    normalized_symbol, timeframe=interval, since=None, limit=lookback
                )
                return data
            except Exception as exc:
                # Check if this is an "Invalid interval" error and try fallback
                error_str = str(exc).lower()
                if "invalid interval" in error_str or "invalid timeframe" in error_str:
                    fallback_interval = self._get_fallback_interval(interval)
                    if fallback_interval:
                        logger.info(
                            "Exchange '{}' does not support interval '{}', "
                            "falling back to '{}' for symbol {}",
                            self._exchange_id,
                            interval,
                            fallback_interval,
                            symbol,
                        )
                        try:
                            data = await exchange.fetch_ohlcv(
                                normalized_symbol,
                                timeframe=fallback_interval,
                                since=None,
                                limit=lookback,
                            )
                            return data
                        except Exception as fallback_exc:
                            logger.warning(
                                "Fallback interval '{}' also failed for {}: {}",
                                fallback_interval,
                                symbol,
                                fallback_exc,
                            )
                            raise exc  # Raise original exception
                raise  # Re-raise if not an interval error or fallback failed
            finally:
                try:
                    await exchange.close()
                except Exception:
                    pass

        candles: List[Candle] = []
        # Run fetch for each symbol sequentially
        for symbol in symbols:
            try:
                # Normalize symbol format for the exchange (e.g., BTC-USDC -> BTC/USDC:USDC)
                normalized_symbol = self._normalize_symbol(symbol)
                raw = await _fetch(symbol, normalized_symbol)
                # raw is list of [ts, open, high, low, close, volume]
                for row in raw:
                    ts, open_v, high_v, low_v, close_v, vol = row
                    candles.append(
                        Candle(
                            ts=int(ts),
                            instrument=InstrumentRef(
                                symbol=symbol,
                                exchange_id=self._exchange_id,
                                # quote_ccy="USD",
                            ),
                            open=float(open_v),
                            high=float(high_v),
                            low=float(low_v),
                            close=float(close_v),
                            volume=float(vol),
                            interval=interval,
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to fetch candles for {} (normalized: {}) from {}, data interval is {}, return empty candles. Error: {}",
                    symbol,
                    normalized_symbol,
                    self._exchange_id,
                    interval,
                    exc,
                )
        logger.debug(
            f"Fetch {len(candles)} candles symbols: {symbols}, interval: {interval}, lookback: {lookback}"
        )
        return candles

    async def get_market_snapshot(self, symbols: List[str]) -> MarketSnapShotType:
        """Fetch latest prices for the given symbols using exchange endpoints.

        The method tries to use the exchange's `fetch_ticker` (and optionally
        `fetch_open_interest` / `fetch_funding_rate` when available) to build
        a mapping symbol -> last price. On any failure for a symbol, the
        symbol will be omitted from the snapshot.
        Example:
        ```
        "BTC/USDT": {
            "price": {
                "symbol": "BTC/USDT:USDT",
                "timestamp": 1762930517943,
                "datetime": "2025-11-12T06:55:17.943Z",
                "high": 105464.2,
                "low": 102400.0,
                "vwap": 103748.56,
                "open": 105107.1,
                "close": 103325.0,
                "last": 103325.0,
                "change": -1782.1,
                "percentage": -1.696,
                "average": 104216.0,
                "baseVolume": 105445.427,
                "quoteVolume": 10939811519.57,
                "info": {
                    "symbol": "BTCUSDT",
                    "priceChange": "-1782.10",
                    "priceChangePercent": "-1.696",
                    "weightedAvgPrice": "103748.56",
                    "lastPrice": "103325.00",
                    "lastQty": "0.002",
                    "openPrice": "105107.10",
                    "highPrice": "105464.20",
                    "lowPrice": "102400.00",
                    "volume": "105445.427",
                    "quoteVolume": "10939811519.57",
                    "openTime": 1762844100000,
                    "closeTime": 1762930517943,
                    "firstId": 6852533393,
                    "lastId": 6856484055,
                    "count": 3942419
                }
            },
            "open_interest": {
                "symbol": "BTC/USDT:USDT",
                "baseVolume": 85179.147,
                "openInterestAmount": 85179.147,
                "timestamp": 1762930517944,
                "datetime": "2025-11-12T06:55:17.944Z",
                "info": {
                    "symbol": "BTCUSDT",
                    "openInterest": "85179.147",
                    "time": 1762930517944
                }
            },
            "funding_rate": {
                "info": {
                    "symbol": "BTCUSDT",
                    "markPrice": "103325.10000000",
                    "indexPrice": "103382.54282609",
                    "estimatedSettlePrice": "103477.58650543",
                    "lastFundingRate": "0.00000967",
                    "interestRate": "0.00010000",
                    "nextFundingTime": 1762934400000,
                    "time": 1762930523000
                },
                "symbol": "BTC/USDT:USDT",
                "markPrice": 103325.1,
                "indexPrice": 103382.54282609,
                "interestRate": 0.0001,
                "estimatedSettlePrice": 103477.58650543,
                "timestamp": 1762930523000,
                "datetime": "2025-11-12T06:55:23.000Z",
                "fundingRate": 9.67e-06,
                "fundingTimestamp": 1762934400000,
                "fundingDatetime": "2025-11-12T08:00:00.000Z"
            }
        }
        ```
        """
        snapshot = defaultdict(dict)

        exchange_cls = get_exchange_cls(self._exchange_id)
        logger.debug(
            "get_market_snapshot: exchange_id={}, exchange_cls={}, execution_gateway={}, symbols={}",
            self._exchange_id,
            exchange_cls is not None,
            self._execution_gateway is not None,
            symbols,
        )
        
        if exchange_cls is None:
            # Exchange not found in ccxt.pro (e.g., custom exchanges like Weex)
            # Try to fetch market data via execution gateway if available
            if self._execution_gateway:
                logger.info(
                    "Exchange '{}' not found in ccxt.pro, trying execution gateway to fetch market data for {} symbols",
                    self._exchange_id,
                    len(symbols),
                )
                try:
                    if hasattr(self._execution_gateway, "fetch_ticker"):
                        logger.debug(
                            "Execution gateway has fetch_ticker method, fetching tickers for {} symbols",
                            len(symbols),
                        )
                        for symbol in symbols:
                            try:
                                logger.debug("Fetching ticker for {} via execution gateway", symbol)
                                ticker = await self._execution_gateway.fetch_ticker(symbol)
                                snapshot[symbol]["price"] = ticker
                                logger.info(
                                    "Successfully fetched ticker for {} ({}): last={}",
                                    symbol,
                                    self._exchange_id,
                                    ticker.get("last", "N/A"),
                                )
                            except Exception as e:
                                logger.warning(
                                    "Failed to fetch ticker for {} ({}): {}", symbol, self._exchange_id, e
                                )
                    else:
                        logger.error(
                            "Execution gateway for '{}' does not support fetch_ticker method. "
                            "Available methods: {}",
                            self._exchange_id,
                            [m for m in dir(self._execution_gateway) if not m.startswith("_")],
                        )
                except Exception as e:
                    logger.exception(
                        "Failed to fetch market data via execution gateway for '{}': {}", 
                        self._exchange_id, 
                        e
                    )
            else:
                logger.error(
                    "Exchange '{}' not found in ccxt.pro and no execution gateway available. "
                    "Market snapshot will be empty. This may cause trading decisions to fail. "
                    "Please ensure execution_gateway is passed to SimpleMarketDataSource.",
                    self._exchange_id,
                )
            result = dict(snapshot)
            logger.info(
                "get_market_snapshot returning {} symbols: {}",
                len(result),
                list(result.keys()),
            )
            return result

        exchange = exchange_cls({"newUpdates": False})
        try:
            for symbol in symbols:
                sym = normalize_symbol(symbol)
                try:
                    ticker = await exchange.fetch_ticker(sym)
                    snapshot[symbol]["price"] = ticker

                    # best-effort: warm other endpoints (open interest / funding)
                    try:
                        oi = await exchange.fetch_open_interest(sym)
                        snapshot[symbol]["open_interest"] = oi
                    except Exception:
                        logger.exception(
                            "Failed to fetch open interest for {} at {}",
                            symbol,
                            self._exchange_id,
                        )

                    try:
                        fr = await exchange.fetch_funding_rate(sym)
                        snapshot[symbol]["funding_rate"] = fr
                    except Exception:
                        logger.exception(
                            "Failed to fetch funding rate for {} at {}",
                            symbol,
                            self._exchange_id,
                        )
                    logger.debug(f"Fetch market snapshot for {sym} data: {snapshot}")
                except Exception:
                    logger.exception(
                        "Failed to fetch market snapshot for {} at {}",
                        symbol,
                        self._exchange_id,
                    )
        finally:
            try:
                await exchange.close()
            except Exception:
                logger.exception(
                    "Failed to close exchange connection for {}",
                    self._exchange_id,
                )

        return dict(snapshot)
