#!/usr/bin/env python3
"""测试脚本：验证 Weex 交易所行情数据获取

测试功能：
1. 获取 ticker 数据（市场快照）
2. 获取 K 线数据（OHLCV）
3. 验证数据格式是否正确
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


async def test_market_data():
    """测试市场数据获取"""
    # API 凭证（从测试脚本中获取）
    api_key = "weex_0d7ed29358e4802ffbb1c9ce43296a37"
    secret_key = "895d69f826c02de7e1a9cc25f7af36e6aefd47f014a44c590be0f293740d2093"
    passphrase = "weex1234"

    logger.info("=" * 60)
    logger.info("测试 Weex 交易所行情数据获取")
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
        # 1. 测试获取 Ticker 数据
        logger.info("\n" + "=" * 60)
        logger.info("1. 测试获取 Ticker 数据（市场快照）")
        logger.info("=" * 60)

        for symbol in test_symbols:
            try:
                logger.info(f"\n获取 {symbol} 的 Ticker 数据...")
                ticker = await gateway.fetch_ticker(symbol)
                
                logger.info(f"✓ 成功获取 {symbol} Ticker:")
                logger.info(f"  最新价格 (last): {ticker.get('last', 'N/A')}")
                logger.info(f"  开盘价 (open): {ticker.get('open', 'N/A')}")
                logger.info(f"  最高价 (high): {ticker.get('high', 'N/A')}")
                logger.info(f"  最低价 (low): {ticker.get('low', 'N/A')}")
                logger.info(f"  成交量 (baseVolume): {ticker.get('baseVolume', 'N/A')}")
                logger.info(f"  涨跌幅 (percentage): {ticker.get('percentage', 'N/A')}%")
                
                if ticker.get("last", 0) == 0:
                    logger.warning(f"  ⚠️ {symbol} 的价格为 0，可能数据获取有问题")
                else:
                    logger.info(f"  ✓ {symbol} 数据正常")
                    
            except Exception as e:
                logger.error(f"  ❌ 获取 {symbol} Ticker 失败: {e}")

        # 2. 测试获取 K 线数据
        logger.info("\n" + "=" * 60)
        logger.info("2. 测试获取 K 线数据（OHLCV）")
        logger.info("=" * 60)

        for symbol in test_symbols:
            for interval in ["1m", "5m", "1h"]:
                try:
                    logger.info(f"\n获取 {symbol} 的 {interval} K 线数据...")
                    candles = await gateway.fetch_ohlcv(symbol, timeframe=interval, limit=10)
                    
                    if candles:
                        logger.info(f"✓ 成功获取 {len(candles)} 根 {interval} K 线")
                        # 显示最新的几根 K 线
                        for i, candle in enumerate(candles[-3:]):
                            ts, open_p, high_p, low_p, close_p, vol = candle
                            logger.info(
                                f"  K线 {i+1}: 时间={ts}, 开={open_p}, 高={high_p}, "
                                f"低={low_p}, 收={close_p}, 量={vol}"
                            )
                    else:
                        logger.warning(f"  ⚠️ {symbol} {interval} K 线数据为空")
                        
                except Exception as e:
                    logger.error(f"  ❌ 获取 {symbol} {interval} K 线失败: {e}")

        # 3. 测试通过 SimpleMarketDataSource 获取数据
        logger.info("\n" + "=" * 60)
        logger.info("3. 测试通过 SimpleMarketDataSource 获取数据")
        logger.info("=" * 60)

        market_data_source = SimpleMarketDataSource(
            exchange_id="weex",
            execution_gateway=gateway,
        )

        # 测试获取市场快照
        logger.info("\n获取市场快照...")
        try:
            market_snapshot = await market_data_source.get_market_snapshot(test_symbols)
            logger.info(f"✓ 成功获取市场快照，包含 {len(market_snapshot)} 个交易对")
            
            for symbol, data in market_snapshot.items():
                price_data = data.get("price", {})
                if price_data:
                    logger.info(
                        f"  {symbol}: 价格={price_data.get('last', 'N/A')}, "
                        f"成交量={price_data.get('baseVolume', 'N/A')}"
                    )
                else:
                    logger.warning(f"  {symbol}: 无价格数据")
        except Exception as e:
            logger.error(f"  ❌ 获取市场快照失败: {e}")

        # 测试获取 K 线
        logger.info("\n获取 K 线数据...")
        try:
            candles = await market_data_source.get_recent_candles(
                test_symbols, interval="1m", lookback=10
            )
            logger.info(f"✓ 成功获取 {len(candles)} 根 K 线")
            
            # 按交易对分组显示
            candles_by_symbol = {}
            for candle in candles:
                symbol = candle.instrument.symbol
                if symbol not in candles_by_symbol:
                    candles_by_symbol[symbol] = []
                candles_by_symbol[symbol].append(candle)
            
            for symbol, symbol_candles in candles_by_symbol.items():
                logger.info(f"  {symbol}: {len(symbol_candles)} 根 K 线")
                if symbol_candles:
                    latest = symbol_candles[-1]
                    logger.info(
                        f"    最新: 时间={latest.ts}, 开={latest.open}, "
                        f"高={latest.high}, 低={latest.low}, 收={latest.close}, 量={latest.volume}"
                    )
        except Exception as e:
            logger.error(f"  ❌ 获取 K 线数据失败: {e}")

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

    asyncio.run(test_market_data())

