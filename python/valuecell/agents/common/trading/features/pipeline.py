"""Feature pipeline abstractions for the strategy agent.

This module encapsulates the data-fetch and feature-computation steps used by
strategy runtimes. Introducing a dedicated pipeline object means the decision
coordinator no longer needs direct access to the market data source or feature
computer—everything is orchestrated by the pipeline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from loguru import logger

from valuecell.agents.common.trading.models import (
    FeaturesPipelineResult,
    FeatureVector,
    UserRequest,
)

if TYPE_CHECKING:
    from valuecell.agents.common.trading.execution.interfaces import BaseExecutionGateway

from ..data.interfaces import BaseMarketDataSource
from ..data.market import SimpleMarketDataSource
from .candle import SimpleCandleFeatureComputer
from .interfaces import (
    BaseFeaturesPipeline,
    CandleBasedFeatureComputer,
)
from .market_snapshot import MarketSnapshotFeatureComputer


class DefaultFeaturesPipeline(BaseFeaturesPipeline):
    """Default pipeline using the simple data source and feature computer."""

    def __init__(
        self,
        *,
        request: UserRequest,
        market_data_source: BaseMarketDataSource,
        candle_feature_computer: CandleBasedFeatureComputer,
        market_snapshot_computer: MarketSnapshotFeatureComputer,
        micro_interval: str = "1s",
        micro_lookback: int = 60 * 3,
        medium_interval: str = "1m",
        medium_lookback: int = 60 * 4,
    ) -> None:
        self._request = request
        self._market_data_source = market_data_source
        self._candle_feature_computer = candle_feature_computer
        self._micro_interval = micro_interval
        self._micro_lookback = micro_lookback
        self._medium_interval = medium_interval
        self._medium_lookback = medium_lookback
        self._symbols = list(dict.fromkeys(request.trading_config.symbols))
        self._market_snapshot_computer = market_snapshot_computer

    async def build(self) -> FeaturesPipelineResult:
        """Fetch candles, compute feature vectors, and append market features."""
        # Determine symbols from the configured request so caller doesn't pass them
        logger.info(
            "Building features pipeline for symbols: {}, exchange: {}",
            self._symbols,
            self._request.exchange_config.exchange_id,
        )
        
        candles_micro = await self._market_data_source.get_recent_candles(
            self._symbols, self._micro_interval, self._micro_lookback
        )
        logger.info(
            "Fetched {} micro candles (interval: {}, lookback: {})",
            len(candles_micro),
            self._micro_interval,
            self._micro_lookback,
        )
        micro_features = self._candle_feature_computer.compute_features(
            candles=candles_micro
        )
        logger.info("Computed {} micro features", len(micro_features or []))

        candles_medium = await self._market_data_source.get_recent_candles(
            self._symbols, self._medium_interval, self._medium_lookback
        )
        logger.info(
            "Fetched {} medium candles (interval: {}, lookback: {})",
            len(candles_medium),
            self._medium_interval,
            self._medium_lookback,
        )
        medium_features = self._candle_feature_computer.compute_features(
            candles=candles_medium
        )
        logger.info("Computed {} medium features", len(medium_features or []))

        features: List[FeatureVector] = []
        features.extend(medium_features or [])
        features.extend(micro_features or [])

        market_snapshot = await self._market_data_source.get_market_snapshot(
            self._symbols
        )
        market_snapshot = market_snapshot or {}
        logger.info(
            "Fetched market snapshot for {} symbols: {}",
            len(market_snapshot),
            list(market_snapshot.keys()),
        )

        market_features = self._market_snapshot_computer.build(
            market_snapshot, self._request.exchange_config.exchange_id
        )
        logger.info("Computed {} market snapshot features", len(market_features))
        features.extend(market_features)

        logger.info(
            "Total features generated: {} (medium: {}, micro: {}, market: {})",
            len(features),
            len(medium_features or []),
            len(micro_features or []),
            len(market_features),
        )

        return FeaturesPipelineResult(features=features)

    @classmethod
    def from_request(
        cls,
        request: UserRequest,
        execution_gateway: Optional["BaseExecutionGateway"] = None,
    ) -> DefaultFeaturesPipeline:
        """Factory creating the default pipeline from a user request.
        
        Args:
            request: User request with strategy configuration
            execution_gateway: Optional execution gateway for custom exchanges
                (e.g., Weex) that need gateway-based market data fetching
        """
        market_data_source = SimpleMarketDataSource(
            exchange_id=request.exchange_config.exchange_id,
            execution_gateway=execution_gateway,
        )
        candle_feature_computer = SimpleCandleFeatureComputer()
        market_snapshot_computer = MarketSnapshotFeatureComputer()
        return cls(
            request=request,
            market_data_source=market_data_source,
            candle_feature_computer=candle_feature_computer,
            market_snapshot_computer=market_snapshot_computer,
        )
