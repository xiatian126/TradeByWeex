#!/usr/bin/env python3
"""测试脚本：验证 Weex 市场快照特征生成

测试功能：
1. 获取市场快照数据
2. 计算市场快照特征
3. 验证特征格式是否正确
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
from valuecell.agents.common.trading.features.market_snapshot import MarketSnapshotFeatureComputer


async def test_market_snapshot_features():
    """测试市场快照特征生成"""
    # API 凭证
    api_key = "weex_0d7ed29358e4802ffbb1c9ce43296a37"
    secret_key = "895d69f826c02de7e1a9cc25f7af36e6aefd47f014a44c590be0f293740d2093"
    passphrase = "weex1234"

    logger.info("=" * 60)
    logger.info("测试 Weex 市场快照特征生成")
    logger.info("=" * 60)

    # 创建执行网关
    gateway = WeexExecutionGateway(
        api_key=api_key,
        secret_key=secret_key,
        passphrase=passphrase,
        default_type="swap",
        margin_mode="cross",
    )

    # 测试交易对
    test_symbols = ["BTC-USDT", "ETH-USDT"]

    try:
        # 1. 获取市场快照数据
        logger.info("\n" + "=" * 60)
        logger.info("1. 获取市场快照数据")
        logger.info("=" * 60)

        market_data_source = SimpleMarketDataSource(
            exchange_id="weex",
            execution_gateway=gateway,
        )

        market_snapshot = await market_data_source.get_market_snapshot(test_symbols)
        logger.info(f"获取到 {len(market_snapshot)} 个交易对的市场快照")
        
        for symbol, data in market_snapshot.items():
            logger.info(f"\n{symbol}:")
            logger.info(f"  数据类型: {type(data)}")
            if isinstance(data, dict):
                logger.info(f"  键: {list(data.keys())}")
                price_data = data.get("price", {})
                if price_data:
                    logger.info(f"  价格数据键: {list(price_data.keys()) if isinstance(price_data, dict) else 'N/A'}")
                    logger.info(f"  价格数据: {price_data}")

        # 2. 计算市场快照特征
        logger.info("\n" + "=" * 60)
        logger.info("2. 计算市场快照特征")
        logger.info("=" * 60)

        feature_computer = MarketSnapshotFeatureComputer()
        market_features = feature_computer.build(market_snapshot, "weex")
        
        logger.info(f"生成了 {len(market_features)} 个市场快照特征")
        
        for feature in market_features:
            logger.info(f"\n特征: {feature.instrument.symbol}")
            logger.info(f"  时间戳: {feature.ts}")
            logger.info(f"  特征值: {feature.values}")
            logger.info(f"  元数据: {feature.meta}")

        if not market_features:
            logger.warning("⚠️ 没有生成任何市场快照特征！")
            logger.warning("这可能是导致 'Market snapshot features are missing' 错误的原因")
            
            # 调试：检查数据格式
            logger.info("\n调试信息：")
            for symbol, data in market_snapshot.items():
                logger.info(f"\n{symbol} 的数据结构:")
                logger.info(f"  data 类型: {type(data)}")
                logger.info(f"  data 内容: {data}")
                if isinstance(data, dict):
                    price_obj = data.get("price")
                    logger.info(f"  price_obj 类型: {type(price_obj)}")
                    logger.info(f"  price_obj 内容: {price_obj}")
                    if isinstance(price_obj, dict):
                        logger.info(f"  price_obj 键: {list(price_obj.keys())}")

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

    asyncio.run(test_market_snapshot_features())

