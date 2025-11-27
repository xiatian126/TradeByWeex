#!/usr/bin/env python3
"""测试脚本：验证完整的 Weex 特征上下文构建，模拟实际运行场景

测试功能：
1. 构建完整的特征管道
2. 模拟 ComposeContext 构建
3. 检查 LLM 提示词构建
4. 验证市场数据是否在最终 payload 中
"""

import asyncio
import json
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from loguru import logger
from valuecell.agents.common.trading.execution.weex_trading import WeexExecutionGateway
from valuecell.agents.common.trading.features.pipeline import DefaultFeaturesPipeline
from valuecell.agents.common.trading.decision.prompt_based.composer import LlmComposer
from valuecell.agents.common.trading.models import (
    UserRequest,
    ExchangeConfig,
    TradingConfig,
    LLMModelConfig,
    ComposeContext,
    PortfolioView,
    TradeDigest,
)
from valuecell.agents.common.trading.utils import prune_none


async def test_full_context():
    """测试完整的上下文构建"""
    # API 凭证
    api_key = "xxxxxx"
    secret_key = "xxxxxx"
    passphrase = "xxxxxx"

    logger.info("=" * 60)
    logger.info("测试完整的 Weex 特征上下文构建")
    logger.info("=" * 60)

    # 创建执行网关
    gateway = WeexExecutionGateway(
        api_key=api_key,
        secret_key=secret_key,
        passphrase=passphrase,
        default_type="swap",
        margin_mode="cross",
    )

    # 创建用户请求
    request = UserRequest(
        exchange_config=ExchangeConfig(
            exchange_id="weex",
            api_key=api_key,
            secret_key=secret_key,
            passphrase=passphrase,
        ),
        trading_config=TradingConfig(
            symbols=["BTC-USDT", "ETH-USDT"],
            max_positions=5,
            max_leverage=10.0,
        ),
        llm_model_config=LLMModelConfig(
            provider="google",
            model_id="gemini-2.0-flash-exp",
            api_key="dummy",
        ),
    )

    try:
        # 1. 构建特征管道
        logger.info("\n" + "=" * 60)
        logger.info("1. 构建特征管道")
        logger.info("=" * 60)

        pipeline = DefaultFeaturesPipeline.from_request(request, execution_gateway=gateway)
        result = await pipeline.build()

        logger.info(f"总特征数: {len(result.features)}")

        # 2. 构建 ComposeContext（模拟实际运行）
        logger.info("\n" + "=" * 60)
        logger.info("2. 构建 ComposeContext")
        logger.info("=" * 60)

        # 创建一个简单的 PortfolioView
        from valuecell.utils.ts import get_current_timestamp_ms
        portfolio = PortfolioView(
            ts=get_current_timestamp_ms(),
            account_balance=10000.0,
            positions={},
            constraints=None,
        )

        # 创建一个简单的 TradeDigest
        digest = TradeDigest(
            ts=get_current_timestamp_ms(),
            sharpe_ratio=None,
            total_trades=0,
            win_rate=0.0,
            avg_return=0.0,
            total_return=0.0,
        )

        context = ComposeContext(
            ts=1764213000000,
            compose_id="test-compose-001",
            strategy_id="test-strategy",
            features=result.features,
            portfolio=portfolio,
            digest=digest,
        )

        logger.info(f"Context 构建完成: features={len(context.features)}")

        # 3. 构建 LLM Composer 并检查提示词
        logger.info("\n" + "=" * 60)
        logger.info("3. 构建 LLM 提示词")
        logger.info("=" * 60)

        composer = LlmComposer(request=request)
        
        # 使用内部方法构建提示词（不实际调用 LLM）
        prompt = composer._build_llm_prompt(context)
        
        # 解析 JSON 部分
        try:
            # 提取 Context 部分的 JSON
            context_start = prompt.find("Context:\n")
            if context_start != -1:
                context_json_str = prompt[context_start + len("Context:\n"):]
                context_data = json.loads(context_json_str)
                
                logger.info("\nContext 数据结构:")
                logger.info(f"  summary: {list(context_data.get('summary', {}).keys())}")
                logger.info(f"  market: {list(context_data.get('market', {}).keys())}")
                logger.info(f"  features: {list(context_data.get('features', {}).keys())}")
                logger.info(f"  positions: {len(context_data.get('positions', []))}")
                
                # 详细检查 market 部分
                market = context_data.get("market", {})
                if market:
                    logger.info(f"\n市场数据详情:")
                    for symbol, data in market.items():
                        logger.info(f"  {symbol}: {list(data.keys())}")
                        logger.info(f"    数据: {data}")
                else:
                    logger.error("❌ 市场数据为空！")
                
                # 详细检查 features 部分
                features = context_data.get("features", {})
                if "market_snapshot" in features:
                    market_snapshot_features = features["market_snapshot"]
                    logger.info(f"\n市场快照特征: {len(market_snapshot_features)} 个")
                    if market_snapshot_features:
                        first = market_snapshot_features[0]
                        logger.info(f"  示例: symbol={first.get('instrument', {}).get('symbol')}")
                        logger.info(f"  特征值: {list(first.get('values', {}).keys())}")
                else:
                    logger.warning("⚠️ features 中没有 market_snapshot")
                
                # 检查其他特征
                for key in ["interval_1m", "interval_1s"]:
                    if key in features:
                        logger.info(f"  {key}: {len(features[key])} 个特征")
                
            else:
                logger.error("无法找到 Context 部分")
        except Exception as e:
            logger.exception(f"解析 Context JSON 失败: {e}")

        logger.info("\n" + "=" * 60)
        logger.info("测试完成")
        logger.info("=" * 60)

    except Exception as e:
        logger.exception(f"测试过程中发生错误: {e}")
    finally:
        await gateway.close()


if __name__ == "__main__":
    # 配置日志
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO",
    )

    asyncio.run(test_full_context())

