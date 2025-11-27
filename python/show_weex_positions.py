#!/usr/bin/env python3
"""展示 Weex 交易所当前持仓信息

根据 Weex API 文档: https://www.weex.com/api-doc/zh-CN/ai/accountAPI
使用账户接口中的"获取全部合约仓位信息"功能
"""

import asyncio
import os
from loguru import logger

from valuecell.agents.common.trading.execution.weex_trading import WeexExecutionGateway


async def show_positions():
    """展示当前持仓信息"""
    # 从环境变量读取 API 凭证
    api_key = os.getenv("WEEX_API_KEY", "")
    secret_key = os.getenv("WEEX_SECRET_KEY", "")
    passphrase = os.getenv("WEEX_PASSPHRASE", "")

    if not api_key or not secret_key or not passphrase:
        logger.error("请设置环境变量: WEEX_API_KEY, WEEX_SECRET_KEY, WEEX_PASSPHRASE")
        return

    gateway = WeexExecutionGateway(
        api_key=api_key,
        secret_key=secret_key,
        passphrase=passphrase,
        margin_mode="cross",  # 或 "isolated"
    )

    try:
        logger.info("=" * 80)
        logger.info("正在获取 Weex 账户持仓信息...")
        logger.info("=" * 80)

        # 获取持仓信息
        positions = await gateway.fetch_positions()

        if not positions:
            logger.info("✅ 当前无持仓")
            return

        logger.info(f"📊 当前持仓数量: {len(positions)}")
        logger.info("")

        # 计算总未实现盈亏
        total_unrealized_pnl = 0.0

        for idx, pos in enumerate(positions, 1):
            symbol = pos.get("symbol", "N/A")
            side = pos.get("side", "N/A")
            quantity = pos.get("quantity", 0.0)
            size = pos.get("size", 0.0)
            leverage = pos.get("leverage", "N/A")
            margin_mode = pos.get("margin_mode", "N/A")
            open_value = pos.get("open_value", 0.0)
            isolated_margin = pos.get("isolated_margin", 0.0)
            unrealized_pnl = pos.get("unrealized_pnl", 0.0)
            entry_price = pos.get("entry_price", 0.0)
            mark_price = pos.get("mark_price", 0.0)

            logger.info(f"持仓 #{idx}: {symbol}")
            logger.info(f"  方向: {side}")
            logger.info(f"  数量: {quantity} (size: {size})")
            if entry_price:
                logger.info(f"  开仓价格: {entry_price}")
            if mark_price:
                logger.info(f"  标记价格: {mark_price}")
            logger.info(f"  杠杆: {leverage}x")
            logger.info(f"  保证金模式: {margin_mode}")
            if open_value:
                logger.info(f"  开仓价值: {open_value}")
            if isolated_margin:
                logger.info(f"  逐仓保证金: {isolated_margin}")
            if unrealized_pnl:
                logger.info(f"  未实现盈亏: {unrealized_pnl}")
                total_unrealized_pnl += unrealized_pnl
            logger.info("")

        if total_unrealized_pnl != 0.0:
            logger.info(f"💰 总未实现盈亏: {total_unrealized_pnl}")
            logger.info("")

        logger.info("=" * 80)

    except Exception as e:
        logger.exception(f"❌ 查询持仓失败: {e}")
    finally:
        await gateway.close()


if __name__ == "__main__":
    asyncio.run(show_positions())

