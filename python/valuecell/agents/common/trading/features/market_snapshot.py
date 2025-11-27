from __future__ import annotations

from typing import Dict, List

from loguru import logger

from valuecell.agents.common.trading.constants import (
    FEATURE_GROUP_BY_KEY,
    FEATURE_GROUP_BY_MARKET_SNAPSHOT,
)
from valuecell.agents.common.trading.models import (
    FeatureVector,
    InstrumentRef,
    MarketSnapShotType,
)
from valuecell.utils.ts import get_current_timestamp_ms


class MarketSnapshotFeatureComputer:
    """Convert exchange market_snapshot structures into FeatureVector items.

    This class encapsulates the logic previously embedded in
    `DefaultFeaturesPipeline._build_market_features`. Keeping it separate
    makes the pipeline easier to test and replace.
    """

    def build(
        self, market_snapshot: MarketSnapShotType, exchange_id: str
    ) -> List[FeatureVector]:
        features: List[FeatureVector] = []
        now_ts = get_current_timestamp_ms()

        for symbol, data in (market_snapshot or {}).items():
            if not isinstance(data, dict):
                continue

            price_obj = data.get("price") if isinstance(data, dict) else None
            timestamp = None
            values: Dict[str, float] = {}

            if isinstance(price_obj, dict):
                timestamp = price_obj.get("timestamp") or price_obj.get("ts")
                
                # Extract price fields (last, close, open, high, low, bid, ask)
                for key in ("last", "close", "open", "high", "low", "bid", "ask"):
                    val = price_obj.get(key)
                    if val is not None:
                        try:
                            val_float = float(val)
                            # Only add non-zero values (or allow zero for last/close which are valid)
                            if val_float != 0.0 or key in ("last", "close", "bid", "ask"):
                                values[f"price.{key}"] = val_float
                        except (TypeError, ValueError):
                            continue
                
                # Try to extract from info field if main fields are missing (for Weex)
                if not values.get("price.high") and isinstance(price_obj.get("info"), dict):
                    info = price_obj["info"]
                    for info_key, feature_key in [
                        ("high_24h", "price.high"),
                        ("low_24h", "price.low"),
                        ("best_bid", "price.bid"),
                        ("best_ask", "price.ask"),
                    ]:
                        if info_key in info and feature_key not in values:
                            try:
                                val_float = float(info[info_key])
                                if val_float != 0.0:
                                    values[feature_key] = val_float
                            except (TypeError, ValueError):
                                continue

                change = price_obj.get("percentage")
                if change is not None:
                    try:
                        values["price.change_pct"] = float(change)
                    except (TypeError, ValueError):
                        pass

                volume = price_obj.get("quoteVolume") or price_obj.get("baseVolume")
                if volume is not None:
                    try:
                        vol_float = float(volume)
                        if vol_float != 0.0:
                            values["price.volume"] = vol_float
                    except (TypeError, ValueError):
                        pass
                
                # Try to extract volume from info field if main volume is missing (for Weex)
                if not values.get("price.volume") and isinstance(price_obj.get("info"), dict):
                    info = price_obj["info"]
                    for info_key in ("volume_24h", "base_volume"):
                        if info_key in info:
                            try:
                                vol_float = float(info[info_key])
                                if vol_float != 0.0:
                                    values["price.volume"] = vol_float
                                    break
                            except (TypeError, ValueError):
                                continue

            if isinstance(data.get("open_interest"), dict):
                oi = data["open_interest"]
                for field in ("openInterest", "openInterestAmount", "baseVolume"):
                    val = oi.get(field)
                    if val is not None:
                        try:
                            values["open_interest"] = float(val)
                        except (TypeError, ValueError):
                            pass
                        break

            if isinstance(data.get("funding_rate"), dict):
                fr = data["funding_rate"]
                rate = fr.get("fundingRate") or fr.get("funding_rate")
                if rate is not None:
                    try:
                        values["funding.rate"] = float(rate)
                    except (TypeError, ValueError):
                        pass
                mark_price = fr.get("markPrice") or fr.get("mark_price")
                if mark_price is not None:
                    try:
                        values["funding.mark_price"] = float(mark_price)
                    except (TypeError, ValueError):
                        pass

            if not values:
                logger.warning(
                    "MarketSnapshotFeatureComputer: no values extracted for {}. "
                    "price_obj keys: {}",
                    symbol,
                    list(price_obj.keys()) if isinstance(price_obj, dict) else "N/A",
                )
                continue

            fv_ts = int(timestamp) if timestamp is not None else now_ts
            feature = FeatureVector(
                ts=int(fv_ts),
                instrument=InstrumentRef(symbol=symbol, exchange_id=exchange_id),
                values=values,
                meta={
                    FEATURE_GROUP_BY_KEY: FEATURE_GROUP_BY_MARKET_SNAPSHOT,
                },
            )
            features.append(feature)
            logger.debug(
                "MarketSnapshotFeatureComputer: created feature for {} with {} values: {}",
                symbol,
                len(values),
                list(values.keys()),
            )

        logger.info(
            "MarketSnapshotFeatureComputer: built {} market snapshot features from {} symbols",
            len(features),
            len(market_snapshot or {}),
        )
        return features
