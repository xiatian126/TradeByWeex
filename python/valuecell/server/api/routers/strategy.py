"""
Strategy API router for handling strategy-related endpoints.
"""

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from valuecell.core.coordinate.orchestrator import AgentOrchestrator

from valuecell.server.api.schemas.base import SuccessResponse
from valuecell.server.api.schemas.strategy import (
    AccountInfoData,
    ExchangeAssetItem,
    StrategyAccountInfoResponse,
    StrategyAssetsData,
    StrategyAssetsResponse,
    StrategyCurveResponse,
    StrategyDetailResponse,
    StrategyHoldingFlatItem,
    StrategyHoldingFlatResponse,
    StrategyListData,
    StrategyListResponse,
    StrategyPortfolioSummaryResponse,
    StrategyStatusSuccessResponse,
    StrategyStatusUpdateResponse,
    StrategySummaryData,
    StrategyType,
)
from valuecell.agents.common.trading.execution.factory import create_execution_gateway
from valuecell.agents.common.trading.models import ExchangeConfig, MarginMode, MarketType, TradingMode
from valuecell.server.db import get_db
from valuecell.server.db.models.strategy import Strategy
from valuecell.server.db.repositories import get_strategy_repository
from valuecell.server.services.strategy_service import StrategyService


# Shared orchestrator instance for strategy operations
_shared_orchestrator: Optional["AgentOrchestrator"] = None


def _get_orchestrator() -> "AgentOrchestrator":
    """Get or create shared orchestrator instance."""
    global _shared_orchestrator
    if _shared_orchestrator is None:
        from valuecell.core.coordinate.orchestrator import AgentOrchestrator

        _shared_orchestrator = AgentOrchestrator()
    return _shared_orchestrator


def create_strategy_router() -> APIRouter:
    """Create and configure the strategy router."""

    router = APIRouter(
        prefix="/strategies",
        tags=["strategies"],
        responses={404: {"description": "Not found"}},
    )

    @router.get(
        "/",
        response_model=StrategyListResponse,
        summary="Get all strategies",
        description="Get a list of strategies created via StrategyAgent with optional filters",
    )
    async def get_strategies(
        user_id: Optional[str] = Query(None, description="Filter by user ID"),
        status: Optional[str] = Query(None, description="Filter by status"),
        name_filter: Optional[str] = Query(
            None, description="Filter by strategy name or ID (supports fuzzy matching)"
        ),
        db: Session = Depends(get_db),
    ) -> StrategyListResponse:
        """
        Get all strategies list.

        - **user_id**: Filter by owner user ID
        - **status**: Filter by strategy status (running, stopped)
        - **name_filter**: Filter by strategy name or ID with fuzzy matching

        Returns a response containing the strategy list and statistics.
        """
        try:
            query = db.query(Strategy)

            filters = []
            if user_id:
                filters.append(Strategy.user_id == user_id)
            if status:
                filters.append(Strategy.status == status)
            if name_filter:
                filters.append(
                    or_(
                        Strategy.name.ilike(f"%{name_filter}%"),
                        Strategy.strategy_id.ilike(f"%{name_filter}%"),
                    )
                )

            if filters:
                query = query.filter(and_(*filters))

            strategies = query.order_by(Strategy.created_at.desc()).all()

            def map_status(raw: Optional[str]) -> str:
                return "running" if (raw or "").lower() == "running" else "stopped"

            def normalize_trading_mode(meta: dict, cfg: dict) -> Optional[str]:
                v = meta.get("trading_mode") or cfg.get("trading_mode")
                if not v:
                    return None
                v = str(v).lower()
                if v in ("live", "real", "realtime"):
                    return "live"
                if v in ("virtual", "paper", "sim"):
                    return "virtual"
                return None

            def to_optional_float(value) -> Optional[float]:
                if value is None:
                    return None
                try:
                    return float(value)
                except Exception:
                    return None

            def normalize_strategy_type(
                meta: dict, cfg: dict
            ) -> Optional[StrategyType]:
                val = meta.get("strategy_type")
                if not val:
                    val = (cfg.get("trading_config", {}) or {}).get("strategy_type")
                if val is None:
                    agent_name = str(meta.get("agent_name") or "").lower()
                    if "prompt" in agent_name:
                        return StrategyType.PROMPT
                    if "grid" in agent_name:
                        return StrategyType.GRID
                    return None

                raw = str(val).strip().lower()
                if raw.startswith("strategytype."):
                    raw = raw.split(".", 1)[1]
                raw_compact = "".join(ch for ch in raw if ch.isalnum())

                if raw in ("prompt based strategy", "grid strategy"):
                    return (
                        StrategyType.PROMPT
                        if raw.startswith("prompt")
                        else StrategyType.GRID
                    )
                if raw_compact in ("promptbasedstrategy", "gridstrategy"):
                    return (
                        StrategyType.PROMPT
                        if raw_compact.startswith("prompt")
                        else StrategyType.GRID
                    )
                if raw in ("prompt", "grid"):
                    return StrategyType.PROMPT if raw == "prompt" else StrategyType.GRID

                agent_name = str(meta.get("agent_name") or "").lower()
                if "prompt" in agent_name:
                    return StrategyType.PROMPT
                if "grid" in agent_name:
                    return StrategyType.GRID
                return None

            strategy_data_list = []
            for s in strategies:
                meta = s.strategy_metadata or {}
                cfg = s.config or {}
                item = StrategySummaryData(
                    strategy_id=s.strategy_id,
                    strategy_name=s.name,
                    strategy_type=normalize_strategy_type(meta, cfg),
                    status=map_status(s.status),
                    trading_mode=normalize_trading_mode(meta, cfg),
                    unrealized_pnl=to_optional_float(meta.get("unrealized_pnl", 0.0)),
                    unrealized_pnl_pct=to_optional_float(
                        meta.get("unrealized_pnl_pct", 0.0)
                    ),
                    created_at=s.created_at,
                    exchange_id=(meta.get("exchange_id") or cfg.get("exchange_id")),
                    model_id=(
                        meta.get("model_id")
                        or meta.get("llm_model_id")
                        or cfg.get("model_id")
                        or cfg.get("llm_model_id")
                    ),
                )
                strategy_data_list.append(item)

            running_count = sum(1 for s in strategy_data_list if s.status == "running")

            list_data = StrategyListData(
                strategies=strategy_data_list,
                total=len(strategy_data_list),
                running_count=running_count,
            )

            return SuccessResponse.create(
                data=list_data,
                msg=f"Successfully retrieved {list_data.total} strategies",
            )
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to retrieve strategy list: {str(e)}"
            )

    @router.get(
        "/holding",
        response_model=StrategyHoldingFlatResponse,
        summary="Get current holdings for a strategy",
        description="Return the latest portfolio holdings of the specified strategy",
    )
    async def get_strategy_holding(
        id: str = Query(..., description="Strategy ID"),
    ) -> StrategyHoldingFlatResponse:
        try:
            data = await StrategyService.get_strategy_holding(id)
            if not data:
                return SuccessResponse.create(
                    data=[],
                    msg="No holdings found for strategy",
                )

            items: List[StrategyHoldingFlatItem] = []
            for p in data.positions or []:
                try:
                    t = p.trade_type or ("LONG" if p.quantity >= 0 else "SHORT")
                    qty = abs(p.quantity)
                    items.append(
                        StrategyHoldingFlatItem(
                            symbol=p.symbol,
                            type=t,
                            leverage=p.leverage,
                            entry_price=p.avg_price,
                            quantity=qty,
                            unrealized_pnl=p.unrealized_pnl,
                            unrealized_pnl_pct=p.unrealized_pnl_pct,
                        )
                    )
                except Exception:
                    continue

            return SuccessResponse.create(
                data=items,
                msg="Successfully retrieved strategy holdings",
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to retrieve holdings: {str(e)}"
            )

    @router.get(
        "/portfolio_summary",
        response_model=StrategyPortfolioSummaryResponse,
        summary="Get latest portfolio summary for a strategy",
        description=(
            "Return aggregated portfolio metrics (cash, total value, unrealized PnL)"
            " for the most recent snapshot."
        ),
    )
    async def get_strategy_portfolio_summary(
        id: str = Query(..., description="Strategy ID"),
    ) -> StrategyPortfolioSummaryResponse:
        try:
            data = await StrategyService.get_strategy_portfolio_summary(id)
            if not data:
                return SuccessResponse.create(
                    data=None,
                    msg="No portfolio summary found for strategy",
                )

            return SuccessResponse.create(
                data=data,
                msg="Successfully retrieved strategy portfolio summary",
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to retrieve portfolio summary: {str(e)}",
            )

    @router.get(
        "/assets",
        response_model=StrategyAssetsResponse,
        summary="Get exchange assets for a strategy",
        description=(
            "Return exchange account assets (available balance, frozen balance, equity, unrealized PnL) "
            "for the specified strategy. Only works for live trading strategies with exchange credentials."
        ),
    )
    async def get_strategy_assets(
        id: str = Query(..., description="Strategy ID"),
        db: Session = Depends(get_db),
    ) -> StrategyAssetsResponse:
        """Get exchange assets for a strategy."""
        try:
            # Get strategy from database
            strategy = db.query(Strategy).filter(Strategy.strategy_id == id).first()
            if not strategy:
                raise HTTPException(status_code=404, detail=f"Strategy {id} not found")

            # Extract exchange config from strategy config
            config = strategy.config or {}
            exchange_config_dict = config.get("exchange_config", {})
            
            exchange_id = exchange_config_dict.get("exchange_id")
            trading_mode = exchange_config_dict.get("trading_mode", "virtual")
            
            if trading_mode != "live":
                raise HTTPException(
                    status_code=400,
                    detail="Assets can only be fetched for live trading strategies",
                )
            
            if not exchange_id:
                raise HTTPException(
                    status_code=400,
                    detail="Strategy does not have exchange configuration",
                )

            # Only support Weex for now (can be extended to other exchanges)
            if exchange_id.lower() != "weex":
                raise HTTPException(
                    status_code=400,
                    detail=f"Asset fetching is not yet supported for exchange: {exchange_id}",
                )

            # Get exchange credentials
            api_key = exchange_config_dict.get("api_key")
            secret_key = exchange_config_dict.get("secret_key")
            passphrase = exchange_config_dict.get("passphrase")

            if not api_key or not secret_key:
                raise HTTPException(
                    status_code=400,
                    detail="Strategy does not have exchange API credentials",
                )

            # Create execution gateway
            exchange_config = ExchangeConfig(
                exchange_id=exchange_id,
                trading_mode=TradingMode.LIVE,
                api_key=api_key,
                secret_key=secret_key,
                passphrase=passphrase,
                testnet=False,
                market_type=MarketType.SWAP,
                margin_mode=MarginMode.CROSS,
            )

            gateway = await create_execution_gateway(exchange_config)

            try:
                # Fetch assets
                if hasattr(gateway, "fetch_assets"):
                    assets_raw = await gateway.fetch_assets()
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Exchange {exchange_id} does not support asset fetching",
                    )

                # Convert to response format
                assets = []
                for asset in assets_raw:
                    assets.append(
                        ExchangeAssetItem(
                            coin_id=asset.get("coinId") or asset.get("coin_id"),
                            coin_name=asset.get("coinName") or asset.get("coin_name"),
                            available=float(asset.get("available", 0.0) or 0.0),
                            frozen=float(asset.get("frozen", 0.0) or 0.0),
                            equity=float(asset.get("equity", 0.0) or 0.0),
                            unrealized_pnl=float(
                                asset.get("unrealizePnl")
                                or asset.get("unrealizedPnl", 0.0)
                                or 0.0
                            ),
                        )
                    )

                return SuccessResponse.create(
                    data=StrategyAssetsData(
                        strategy_id=id,
                        exchange_id=exchange_id,
                        assets=assets,
                    ),
                    msg="Successfully retrieved strategy assets",
                )
            finally:
                await gateway.close()

        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Failed to retrieve strategy assets: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to retrieve strategy assets: {str(e)}",
            )

    @router.get(
        "/account_info",
        response_model=StrategyAccountInfoResponse,
        summary="Get exchange account information for a strategy",
        description=(
            "Return comprehensive account information from /capi/v2/account/accounts endpoint "
            "including total equity, available balance, and frozen balance. "
            "Only works for live trading strategies with exchange credentials."
        ),
    )
    async def get_strategy_account_info(
        id: str = Query(..., description="Strategy ID"),
        db: Session = Depends(get_db),
    ) -> StrategyAccountInfoResponse:
        """Get exchange account information for a strategy."""
        try:
            # Get strategy from database
            strategy = db.query(Strategy).filter(Strategy.strategy_id == id).first()
            if not strategy:
                raise HTTPException(status_code=404, detail=f"Strategy {id} not found")

            # Extract exchange config from strategy config
            config = strategy.config or {}
            exchange_config_dict = config.get("exchange_config", {})
            
            exchange_id = exchange_config_dict.get("exchange_id")
            trading_mode = exchange_config_dict.get("trading_mode", "virtual")
            
            if trading_mode != "live":
                raise HTTPException(
                    status_code=400,
                    detail="Account info can only be fetched for live trading strategies",
                )
            
            if not exchange_id:
                raise HTTPException(
                    status_code=400,
                    detail="Strategy does not have exchange configuration",
                )

            # Only support Weex for now (can be extended to other exchanges)
            if exchange_id.lower() != "weex":
                raise HTTPException(
                    status_code=400,
                    detail=f"Account info fetching is not yet supported for exchange: {exchange_id}",
                )

            # Get exchange credentials
            api_key = exchange_config_dict.get("api_key")
            secret_key = exchange_config_dict.get("secret_key")
            passphrase = exchange_config_dict.get("passphrase")

            if not api_key or not secret_key:
                raise HTTPException(
                    status_code=400,
                    detail="Strategy does not have exchange API credentials",
                )

            # Create execution gateway
            exchange_config = ExchangeConfig(
                exchange_id=exchange_id,
                trading_mode=TradingMode.LIVE,
                api_key=api_key,
                secret_key=secret_key,
                passphrase=passphrase,
                testnet=False,
                market_type=MarketType.SWAP,
                margin_mode=MarginMode.CROSS,
            )

            gateway = await create_execution_gateway(exchange_config)

            try:
                # Fetch account info
                if hasattr(gateway, "fetch_account_info"):
                    account_info = await gateway.fetch_account_info()
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Exchange {exchange_id} does not support account info fetching",
                    )

                return SuccessResponse.create(
                    data=AccountInfoData(
                        strategy_id=id,
                        exchange_id=exchange_id,
                        total_equity=account_info.get("total_equity", 0.0),
                        total_available=account_info.get("total_available", 0.0),
                        total_frozen=account_info.get("total_frozen", 0.0),
                        account=account_info.get("account"),
                        collateral=account_info.get("collateral"),
                        position=account_info.get("position"),
                    ),
                    msg="Successfully retrieved strategy account info",
                )
            finally:
                await gateway.close()

        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Failed to retrieve strategy account info: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to retrieve strategy account info: {str(e)}",
            )

    @router.get(
        "/detail",
        response_model=StrategyDetailResponse,
        summary="Get strategy trade details",
        description="Return a list of trade details generated from the latest portfolio snapshot",
    )
    async def get_strategy_detail(
        id: str = Query(..., description="Strategy ID"),
    ) -> StrategyDetailResponse:
        try:
            data = await StrategyService.get_strategy_detail(id)
            if not data:
                # Return empty list with success instead of 404
                return SuccessResponse.create(
                    data=[],
                    msg="No details found for strategy",
                )
            return SuccessResponse.create(
                data=data,
                msg="Successfully retrieved strategy details",
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to retrieve details: {str(e)}"
            )

    @router.get(
        "/holding_price_curve",
        response_model=StrategyCurveResponse,
        summary="Get strategy holding price curve (single or all)",
        description="If id is provided, return single strategy curve. If omitted, return combined curves for all strategies with nulls for missing data.",
    )
    async def get_strategy_holding_price_curve(
        id: Optional[str] = Query(None, description="Strategy ID (optional)"),
        limit: Optional[int] = Query(
            None,
            description="Limit number of strategies when id omitted (most recent first)",
            ge=1,
            le=200,
        ),
        db: Session = Depends(get_db),
    ) -> StrategyCurveResponse:
        try:
            repo = get_strategy_repository(db_session=db)

            # Case 1: Single strategy
            if id:
                strategy = repo.get_strategy_by_strategy_id(id)
                if not strategy:
                    raise HTTPException(status_code=404, detail="Strategy not found")

                strategy_name = strategy.name or f"Strategy-{id.split('-')[-1][:8]}"
                created_at = strategy.created_at or datetime.utcnow()

                data = [["Time", strategy_name]]

                # Build series from aggregated portfolio snapshots (StrategyPortfolioView).
                snapshots = repo.get_portfolio_snapshots(id)
                if snapshots:
                    # repository returns desc order; present oldest->newest
                    for s in reversed(snapshots):
                        t = s.snapshot_ts or created_at
                        time_str = t.strftime("%Y-%m-%d %H:%M:%S")
                        try:
                            v = (
                                float(s.total_value)
                                if s.total_value is not None
                                else None
                            )
                        except Exception:
                            v = None
                        data.append([time_str, v])
                else:
                    return SuccessResponse.create(
                        data=[],
                        msg="No holding price curve found for strategy",
                    )

                return SuccessResponse.create(
                    data=data,
                    msg="Fetched holding price curve successfully",
                )

            # Case 2: Combined curves for all strategies
            query = db.query(Strategy).order_by(Strategy.created_at.desc())
            if limit:
                query = query.limit(limit)
            strategies = query.all()

            # Build series per strategy: {strategy_id: {time_str: value}}
            series_map = {}
            strategy_order = []  # Keep consistent header order
            name_map = {}
            created_times = []

            for s in strategies:
                sid = s.strategy_id
                sname = s.name or f"Strategy-{sid.split('-')[-1][:8]}"
                strategy_order.append(sid)
                name_map[sid] = sname
                created_at = s.created_at or datetime.utcnow()
                created_times.append(created_at)

                # Build per-strategy entries from aggregated portfolio snapshots
                entries = {}
                snapshots = repo.get_portfolio_snapshots(sid)
                if snapshots:
                    for s in reversed(snapshots):
                        t = s.snapshot_ts or created_at
                        time_str = t.strftime("%Y-%m-%d %H:%M:%S")
                        try:
                            v = (
                                float(s.total_value)
                                if s.total_value is not None
                                else None
                            )
                        except Exception:
                            v = None
                        entries[time_str] = v
                series_map[sid] = entries

            # Union of all timestamps
            all_times = set()
            for entries in series_map.values():
                for ts in entries.keys():
                    all_times.add(ts)

            data = [["Time"] + [name_map[sid] for sid in strategy_order]]

            if all_times:
                for time_str in sorted(all_times):
                    row = [time_str]
                    for sid in strategy_order:
                        v = series_map.get(sid, {}).get(time_str)
                        row.append(v if v is not None else None)
                    data.append(row)
            else:
                # No data across all strategies: return empty array
                return SuccessResponse.create(
                    data=[],
                    msg="No holding price curves found",
                )

            return SuccessResponse.create(
                data=data,
                msg="Fetched merged holding price curves successfully",
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to retrieve holding price curve: {str(e)}",
            )

    @router.post(
        "/start",
        response_model=StrategyStatusSuccessResponse,
        summary="Start a strategy",
        description="Set the strategy status to 'running' by ID (via query param 'id') and resume it",
    )
    async def start_strategy(
        id: str = Query(..., description="Strategy ID"),
        background_tasks: BackgroundTasks = BackgroundTasks(),
        db: Session = Depends(get_db),
    ) -> StrategyStatusSuccessResponse:
        """Start a stopped strategy by setting its status to 'running' and resuming it."""
        try:
            import asyncio
            from valuecell.core.coordinate.orchestrator import AgentOrchestrator

            repo = get_strategy_repository(db_session=db)
            strategy = repo.get_strategy_by_strategy_id(id)
            if not strategy:
                raise HTTPException(status_code=404, detail="Strategy not found")

            # Update status to 'running'
            repo.upsert_strategy(strategy_id=id, status="running")

            # Resume the strategy using auto-resume logic in background
            # Use asyncio.create_task to run in background without blocking HTTP response
            async def _resume_in_background() -> None:
                """Background task to resume strategy."""
                try:
                    # Use shared orchestrator instance to avoid port conflicts
                    orchestrator = _get_orchestrator()
                    from valuecell.server.services.strategy_autoresume import _resume_one

                    # Use the existing _resume_one function which handles the resume logic
                    await _resume_one(orchestrator, strategy)
                except asyncio.CancelledError:
                    # Task was cancelled, this is expected
                    raise
                except Exception as e:
                    logger.warning("Failed to resume strategy {} in background: {}", id, e)
                    # If resume fails, mark strategy as stopped
                    try:
                        repo = get_strategy_repository()
                        repo.upsert_strategy(strategy_id=id, status="stopped")
                    except Exception:
                        pass

            # Start background task without awaiting
            # This allows the HTTP response to return immediately
            asyncio.create_task(_resume_in_background())

            response_data = StrategyStatusUpdateResponse(
                strategy_id=id,
                status="running",
                message=f"Strategy '{id}' has been started",
            )

            return SuccessResponse.create(
                data=response_data,
                msg=f"Successfully started strategy '{id}'",
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to start strategy: {str(e)}",
            )

    @router.post(
        "/stop",
        response_model=StrategyStatusSuccessResponse,
        summary="Stop a strategy",
        description="Set the strategy status to 'stopped' by ID (via query param 'id')",
    )
    async def stop_strategy(
        id: str = Query(..., description="Strategy ID"),
        db: Session = Depends(get_db),
    ) -> StrategyStatusSuccessResponse:
        try:
            repo = get_strategy_repository(db_session=db)
            strategy = repo.get_strategy_by_strategy_id(id)
            if not strategy:
                raise HTTPException(status_code=404, detail="Strategy not found")

            # Update status to 'stopped' (idempotent)
            repo.upsert_strategy(strategy_id=id, status="stopped")

            response_data = StrategyStatusUpdateResponse(
                strategy_id=id,
                status="stopped",
                message=f"Strategy '{id}' has been stopped",
            )

            return SuccessResponse.create(
                data=response_data,
                msg=f"Successfully stopped strategy '{id}'",
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to stop strategy: {str(e)}",
            )

    return router
