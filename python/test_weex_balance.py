#!/usr/bin/env python3
"""测试脚本：Weex 交易所功能测试

功能：
1. 查看账户余额
2. 查看账户持仓
3. 下单（限价/市价）
4. 撤单/关单

使用方法:
    python test_weex_balance.py [command]

命令:
    balance  - 查看账户余额（默认）
    positions - 查看账户持仓
    order    - 下单（需要参数）
    cancel   - 撤单（需要参数）
"""

import asyncio
import os
import sys
import argparse
import time
from pathlib import Path
from typing import Optional

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from loguru import logger
from valuecell.agents.common.trading.execution.weex_trading import WeexExecutionGateway
from valuecell.agents.common.trading.models import (
    TradeInstruction,
    InstrumentRef,
    TradeSide,
    PriceMode,
    TradeDecisionAction,
)


async def test_weex_balance():
    """测试 Weex 账户余额查询"""
    # 从环境变量获取 API 凭证
    api_key = "xxxxxx"
    secret_key = "xxxxxx"
    passphrase = "xxxxxx"

    if not all([api_key, secret_key, passphrase]):
        logger.error(
            "请设置环境变量: WEEX_API_KEY, WEEX_SECRET_KEY, WEEX_PASSPHRASE"
        )
        logger.info(
            "示例:\n"
            "export WEEX_API_KEY='your_api_key'\n"
            "export WEEX_SECRET_KEY='your_secret_key'\n"
            "export WEEX_PASSPHRASE='your_passphrase'\n"
            "python test_weex_balance.py"
        )
        return

    logger.info("正在连接 Weex 交易所...")
    logger.info(f"API Key: {api_key[:10]}...")
    gateway = WeexExecutionGateway(
        api_key=api_key,
        secret_key=secret_key,
        passphrase=passphrase,
        default_type="swap",  # 合约交易
        margin_mode="cross",  # 全仓模式
    )

    try:
        # 获取账户余额
        logger.info("正在获取账户余额...")
        balance = await gateway.fetch_balance()

        logger.info("=" * 60)
        logger.info("账户余额信息:")
        logger.info("=" * 60)

        # 显示所有币种的余额
        if "free" in balance and balance["free"]:
            logger.info("\n可用余额 (Free):")
            for currency, amount in balance["free"].items():
                if float(amount) > 0:
                    logger.info(f"  {currency}: {amount:,.8f}")

        if "used" in balance and balance["used"]:
            logger.info("\n冻结余额 (Used):")
            has_used = False
            for currency, amount in balance["used"].items():
                if float(amount) > 0:
                    logger.info(f"  {currency}: {amount:,.8f}")
                    has_used = True
            if not has_used:
                logger.info("  (无冻结余额)")

        if "total" in balance and balance["total"]:
            logger.info("\n总余额 (Total):")
            for currency, amount in balance["total"].items():
                if float(amount) > 0:
                    logger.info(f"  {currency}: {amount:,.8f}")

        # 计算总资产（以 USDT 计价）
        total_usdt = 0.0
        if "total" in balance:
            # 优先使用 USDT
            total_usdt = float(balance["total"].get("USDT", 0.0))
            # 如果没有 USDT，尝试其他稳定币
            if total_usdt == 0:
                total_usdt = float(balance["total"].get("USD", 0.0))
            if total_usdt == 0:
                total_usdt = float(balance["total"].get("USDC", 0.0))

        logger.info("\n" + "=" * 60)
        if total_usdt > 0:
            logger.info(f"账户总资产 (USDT): {total_usdt:,.2f} USDT")
        else:
            logger.warning("未找到 USDT/USD/USDC 余额，账户可能为空")
            logger.info("请检查其他币种的余额")

        # 获取持仓信息
        logger.info("\n" + "=" * 60)
        logger.info("正在获取持仓信息...")
        try:
            positions = await gateway.fetch_positions()
            if positions:
                logger.info(f"当前持仓数量: {len(positions)}")
                for pos in positions:
                    symbol = pos.get("symbol", "N/A")
                    qty = pos.get("quantity", 0.0)
                    if float(qty) != 0:
                        logger.info(
                            f"  {symbol}: {qty} (未实现盈亏: {pos.get('unrealized_pnl', 0.0)})"
                        )
            else:
                logger.info("当前无持仓")
        except Exception as e:
            logger.warning(f"获取持仓信息失败: {e}")

        logger.info("=" * 60)

    except Exception as e:
        logger.exception(f"查询账户余额失败: {e}")
        logger.error("请检查:")
        logger.error("1. API 凭证是否正确")
        logger.error("2. API 是否有查询余额的权限")
        logger.error("3. 网络连接是否正常")
    finally:
        await gateway.close()


async def test_positions(gateway: WeexExecutionGateway):
    """测试查看账户持仓"""
    try:
        logger.info("=" * 60)
        logger.info("正在获取账户持仓信息...")
        logger.info("=" * 60)

        positions = await gateway.fetch_positions()

        if not positions:
            logger.info("当前无持仓")
            return

        logger.info(f"当前持仓数量: {len(positions)}")
        logger.info("")

        for pos in positions:
            symbol = pos.get("symbol", "N/A")
            side = pos.get("side", "N/A")
            size = pos.get("size", 0.0)
            leverage = pos.get("leverage", "N/A")
            margin_mode = pos.get("margin_mode", "N/A")
            open_value = pos.get("open_value", 0.0)
            unrealized_pnl = pos.get("unrealized_pnl", 0.0)

            logger.info(f"交易对: {symbol}")
            logger.info(f"  方向: {side}")
            logger.info(f"  数量: {size}")
            logger.info(f"  杠杆: {leverage}x")
            logger.info(f"  保证金模式: {margin_mode}")
            logger.info(f"  开仓价值: {open_value}")
            logger.info(f"  未实现盈亏: {unrealized_pnl}")
            logger.info("")

        logger.info("=" * 60)

    except Exception as e:
        logger.exception(f"查询持仓失败: {e}")
    finally:
        await gateway.close()


async def test_place_order(
    gateway: WeexExecutionGateway,
    symbol: str,
    side: str,
    quantity: float,
    price: Optional[float] = None,
    order_type: str = "limit",
):
    """测试下单"""
    try:
        logger.info("=" * 60)
        logger.info("正在下单...")
        logger.info("=" * 60)

        # 创建交易指令
        action_map = {
            "buy": TradeDecisionAction.OPEN_LONG,
            "sell": TradeDecisionAction.OPEN_SHORT,
        }
        action = action_map.get(side.lower(), TradeDecisionAction.OPEN_LONG)

        compose_id = f"test_compose_{int(time.time() * 1000)}"
        instruction_id = f"test_{int(time.time() * 1000)}"
        
        instruction = TradeInstruction(
            instruction_id=instruction_id,
            compose_id=compose_id,
            instrument=InstrumentRef(symbol=symbol, exchange_id="weex"),
            side=TradeSide.BUY if side.lower() == "buy" else TradeSide.SELL,
            quantity=quantity,
            limit_price=price,
            price_mode=PriceMode.MARKET if order_type == "market" else PriceMode.LIMIT,
            action=action,
        )

        logger.info(f"交易对: {symbol}")
        logger.info(f"方向: {side}")
        logger.info(f"数量: {quantity}")
        logger.info(f"价格: {price if price else '市价'}")
        logger.info(f"订单类型: {order_type}")
        logger.info("")

        result = await gateway._execute_single(instruction)

        logger.info("下单结果:")
        logger.info(f"  订单ID: {result.reason}")
        logger.info(f"  状态: {result.status.value}")
        logger.info(f"  请求数量: {result.requested_qty}")
        logger.info(f"  成交数量: {result.filled_qty}")
        logger.info(f"  成交均价: {result.avg_exec_price}")
        logger.info("=" * 60)

    except Exception as e:
        logger.exception(f"下单失败: {e}")
    finally:
        await gateway.close()


async def test_cancel_order(
    gateway: WeexExecutionGateway, order_id: str, symbol: str, client_oid: Optional[str] = None
):
    """测试撤单"""
    try:
        logger.info("=" * 60)
        logger.info("正在撤单...")
        logger.info("=" * 60)

        logger.info(f"订单ID: {order_id}")
        logger.info(f"交易对: {symbol}")
        if client_oid:
            logger.info(f"客户端订单ID: {client_oid}")
        logger.info("")

        result = await gateway.cancel_order(order_id=order_id, symbol=symbol, client_oid=client_oid)

        logger.info("撤单结果:")
        logger.info(f"  结果: {result.get('result', 'N/A')}")
        logger.info(f"  订单ID: {result.get('order_id', 'N/A')}")
        logger.info("=" * 60)

    except Exception as e:
        logger.exception(f"撤单失败: {e}")
    finally:
        await gateway.close()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Weex 交易所功能测试")
    parser.add_argument(
        "command",
        nargs="?",
        default="balance",
        choices=["balance", "positions", "order", "cancel"],
        help="要执行的命令",
    )

    # 下单参数
    parser.add_argument("--symbol", help="交易对 (例如: BTC-USDT)")
    parser.add_argument("--side", choices=["buy", "sell"], help="方向: buy 或 sell")
    parser.add_argument("--quantity", type=float, help="数量")
    parser.add_argument("--price", type=float, help="价格 (限价单)")
    parser.add_argument("--market", action="store_true", help="使用市价单")

    # 撤单参数
    parser.add_argument("--order-id", help="订单ID")
    parser.add_argument("--client-oid", help="客户端订单ID")

    args = parser.parse_args()

    # 配置日志
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO",
    )

    # 获取 API 凭证
    api_key = "xxxxxx"
    secret_key = "xxxxxx"
    passphrase = "xxxxxx"

    if not all([api_key, secret_key, passphrase]):
        logger.error("请设置 API 凭证")
        return

    gateway = WeexExecutionGateway(
        api_key=api_key,
        secret_key=secret_key,
        passphrase=passphrase,
        default_type="swap",
        margin_mode="cross",
    )

    if args.command == "balance":
        asyncio.run(test_weex_balance())
    elif args.command == "positions":
        asyncio.run(test_positions(gateway))
    elif args.command == "order":
        if not args.symbol or not args.side or not args.quantity:
            logger.error("下单需要参数: --symbol, --side, --quantity")
            logger.info("示例: python test_weex_balance.py order --symbol BTC-USDT --side buy --quantity 0.001 --price 50000")
            return
        order_type = "market" if args.market else "limit"
        asyncio.run(
            test_place_order(
                gateway, args.symbol, args.side, args.quantity, args.price, order_type
            )
        )
    elif args.command == "cancel":
        if not args.order_id and not args.client_oid:
            logger.error("撤单需要参数: --order-id 或 --client-oid")
            logger.info("示例: python test_weex_balance.py cancel --order-id 123456 --symbol BTC-USDT")
            return
        if not args.symbol:
            logger.error("撤单需要参数: --symbol")
            return
        asyncio.run(test_cancel_order(gateway, args.order_id or "", args.symbol, args.client_oid))


if __name__ == "__main__":
    main()

