#!/usr/bin/env python3
"""测试脚本：验证 Weex 特征是否正确传递到 LLM 上下文

测试功能：
1. 构建完整的特征管道
2. 检查特征分组
3. 检查市场快照提取
4. 验证 LLM 上下文构建
"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from loguru import logger
from valuecell.agents.common.trading.execution.weex_trading import WeexExecutionGateway
from valuecell.agents.common.trading.data.market import SimpleMarketDataSource
from valuecell.agents.common.trading.features.pipeline import DefaultFeaturesPipeline
from valuecell.agents.common.trading.features.market_snapshot import MarketSnapshotFeatureComputer
from valuecell.agents.common.trading.utils import group_features, extract_market_section
from valuecell.agents.common.trading.models import UserRequest, ExchangeConfig, TradingConfig, LLMModelConfig


async def test_feature_context():
    """测试特征上下文构建"""
    # API 凭证
    api_key = "weex_0d7ed29358e4802ffbb1c9ce43296a37"
    secret_key = "895d69f826c02de7e1a9cc25f7af36e6aefd47f014a44c590be0f293740d2093"
    passphrase = "weex1234"

    logger.info("=" * 60)
    logger.info("测试 Weex 特征上下文构建")
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

        # 2. 检查特征分组
        logger.info("\n" + "=" * 60)
        logger.info("2. 检查特征分组")
        logger.info("=" * 60)

        grouped = group_features(result.features)
        logger.info(f"分组键: {list(grouped.keys())}")
        
        for group_key, features in grouped.items():
            logger.info(f"\n分组 '{group_key}': {len(features)} 个特征")
            if features:
                # 显示第一个特征的示例
                first_feature = features[0]
                logger.info(f"  示例特征键: {list(first_feature.keys())}")
                if "instrument" in first_feature:
                    logger.info(f"  交易对: {first_feature['instrument'].get('symbol', 'N/A')}")
                if "values" in first_feature:
                    logger.info(f"  特征值键: {list(first_feature['values'].keys())[:10]}")  # 只显示前10个

        # 3. 检查市场快照提取
        logger.info("\n" + "=" * 60)
        logger.info("3. 检查市场快照提取")
        logger.info("=" * 60)

        market_snapshot_features = grouped.get("market_snapshot", [])
        logger.info(f"市场快照特征数: {len(market_snapshot_features)}")
        
        if market_snapshot_features:
            logger.info("\n市场快照特征详情:")
            for feature in market_snapshot_features:
                symbol = feature.get("instrument", {}).get("symbol", "N/A")
                values = feature.get("values", {})
                logger.info(f"  {symbol}:")
                logger.info(f"    特征值: {list(values.keys())}")
                # 显示一些关键值
                for key in ["price.last", "price.high", "price.low", "price.change_pct", "price.volume"]:
                    if key in values:
                        logger.info(f"    {key}: {values[key]}")
        else:
            logger.warning("⚠️ 没有找到市场快照特征！")

        # 4. 检查市场部分提取
        logger.info("\n" + "=" * 60)
        logger.info("4. 检查市场部分提取（用于 LLM 上下文）")
        logger.info("=" * 60)

        market_section = extract_market_section(market_snapshot_features)
        logger.info(f"市场部分包含 {len(market_section)} 个交易对")
        
        if market_section:
            logger.info("\n市场部分详情:")
            for symbol, data in market_section.items():
                logger.info(f"  {symbol}: {list(data.keys())}")
                logger.info(f"    数据: {data}")
        else:
            logger.warning("⚠️ 市场部分为空！这可能是导致 'No market features provided' 错误的原因")

        # 5. 检查其他特征（1m, 1s）
        logger.info("\n" + "=" * 60)
        logger.info("5. 检查其他特征（1m, 1s）")
        logger.info("=" * 60)

        for group_key in ["interval_1m", "interval_1s"]:
            if group_key in grouped:
                features = grouped[group_key]
                logger.info(f"{group_key}: {len(features)} 个特征")
                if features:
                    first = features[0]
                    symbol = first.get("instrument", {}).get("symbol", "N/A")
                    logger.info(f"  示例交易对: {symbol}")
            else:
                logger.warning(f"⚠️ 没有找到 {group_key} 特征")

        logger.info("\n" + "=" * 60)
        logger.info("测试完成")
        logger.info("=" * 60)

        # 总结
        logger.info("\n" + "=" * 60)
        logger.info("总结")
        logger.info("=" * 60)
        
        has_market_snapshot = len(market_snapshot_features) > 0
        has_market_section = len(market_section) > 0
        has_candle_features = any(k.startswith("interval_") for k in grouped.keys())
        
        logger.info(f"✓ 市场快照特征: {'是' if has_market_snapshot else '否'}")
        logger.info(f"✓ 市场部分提取: {'是' if has_market_section else '否'}")
        logger.info(f"✓ K线特征: {'是' if has_candle_features else '否'}")
        
        if not has_market_section:
            logger.error("❌ 市场部分为空，这会导致 'No market features provided' 错误！")
            logger.error("   请检查 extract_market_section 函数是否正确处理了特征数据")

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

    asyncio.run(test_feature_context())

