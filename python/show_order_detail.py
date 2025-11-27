#!/usr/bin/env python3
"""查看 Weex 订单详细信息

根据 Weex API 文档: https://www.weex.com/api-doc/zh-CN/contract/Transaction_API/GetSingleOrderInfo
使用 GET /capi/v2/order/detail 接口获取单个订单的详细信息
"""

import asyncio
import os
import sys
from datetime import datetime
from loguru import logger

from valuecell.agents.common.trading.execution.weex_trading import WeexExecutionGateway


async def show_order_detail(order_id: str, symbol: str = None):
    """查看订单详细信息"""
    # 从环境变量读取 API 凭证
    api_key = "weex_0d7ed29358e4802ffbb1c9ce43296a37"
    secret_key = "895d69f826c02de7e1a9cc25f7af36e6aefd47f014a44c590be0f293740d2093"
    passphrase = "weex1234"

    if not api_key or not secret_key or not passphrase:
        logger.error("请设置环境变量: WEEX_API_KEY, WEEX_SECRET_KEY, WEEX_PASSPHRASE")
        return

    gateway = WeexExecutionGateway(
        api_key=api_key,
        secret_key=secret_key,
        passphrase=passphrase,
        margin_mode="cross",
    )

    try:
        logger.info("=" * 80)
        logger.info(f"正在获取订单详细信息: {order_id}")
        if symbol:
            logger.info(f"交易对: {symbol}")
        logger.info("=" * 80)

        # 获取订单详细信息
        order = await gateway.fetch_order(order_id, symbol)

        if not order:
            logger.warning(f"❌ 未找到订单: {order_id}")
            return

        logger.info("\n订单详细信息:")
        logger.info("-" * 80)
        
        # 根据 Weex API 文档显示所有字段
        logger.info(f"订单 ID: {order.get('order_id') or order.get('orderId') or order.get('id', 'N/A')}")
        logger.info(f"客户端订单ID: {order.get('client_oid') or order.get('clientOid', 'N/A')}")
        logger.info(f"交易对: {order.get('symbol', 'N/A')}")
        logger.info(f"委托类型: {order.get('type', 'N/A')}")
        logger.info(f"订单类型: {order.get('order_type', 'N/A')}")
        logger.info(f"委托数量: {order.get('size', 'N/A')}")
        logger.info(f"委托价格: {order.get('price', 'N/A')}")
        logger.info(f"成交数量: {order.get('filled_qty') or order.get('filledQty', 'N/A')}")
        logger.info(f"成交均价: {order.get('price_avg', 'N/A')}")
        logger.info(f"手续费: {order.get('fee', 'N/A')}")
        logger.info(f"订单状态: {order.get('status', 'N/A')}")
        logger.info(f"总盈亏: {order.get('totalProfits', 'N/A')}")
        logger.info(f"订单张数: {order.get('contracts', 'N/A')}")
        logger.info(f"已成交张数: {order.get('filledQtyContracts', 'N/A')}")
        
        if order.get('presetTakeProfitPrice'):
            logger.info(f"预设止盈价格: {order.get('presetTakeProfitPrice')}")
        if order.get('presetStopLossPrice'):
            logger.info(f"预设止损价格: {order.get('presetStopLossPrice')}")
        
        create_time = order.get('createTime') or order.get('create_time') or order.get('timestamp')
        if create_time:
            try:
                if isinstance(create_time, (int, float)):
                    dt = datetime.fromtimestamp(int(create_time) / 1000)
                elif isinstance(create_time, str):
                    dt = datetime.fromtimestamp(int(create_time) / 1000)
                else:
                    dt = create_time
                logger.info(f"创建时间: {dt.strftime('%Y-%m-%d %H:%M:%S') if hasattr(dt, 'strftime') else dt}")
            except Exception as e:
                logger.info(f"创建时间: {create_time}")
        
        logger.info("\n" + "=" * 80)
        logger.info("订单状态说明:")
        logger.info("  pending: 委托单已提交撮合，但未收到处理结果")
        logger.info("  open: 委托单已被撮合引擎处理(已挂单)，可能部分成交")
        logger.info("  filled: 委托单已完全成交【终态】")
        logger.info("  canceling: 正在取消处理中")
        logger.info("  canceled: 委托单已被取消。可能部分成交。【终态】")
        logger.info("  untriggered: 条件委托单尚未被触发")
        logger.info("=" * 80)

    except Exception as e:
        logger.exception(f"❌ 查询订单详细信息失败: {e}")
    finally:
        await gateway.close()


async def show_all_orders_with_details():
    """获取所有当前委托订单，并为每个订单获取详细信息"""
    api_key = "weex_0d7ed29358e4802ffbb1c9ce43296a37"
    secret_key = "895d69f826c02de7e1a9cc25f7af36e6aefd47f014a44c590be0f293740d2093"
    passphrase = "weex1234"

    gateway = WeexExecutionGateway(
        api_key=api_key,
        secret_key=secret_key,
        passphrase=passphrase,
        margin_mode="cross",
    )

    try:
        logger.info("=" * 80)
        logger.info("正在获取所有当前委托订单及其详细信息...")
        logger.info("=" * 80)

        # 先获取所有当前委托订单
        orders = await gateway.fetch_open_orders()

        if not orders:
            logger.info("✅ 当前无委托订单")
            return

        logger.info(f"📊 找到 {len(orders)} 个当前委托订单\n")

        # 为每个订单获取详细信息
        for idx, order in enumerate(orders, 1):
            order_id = order.get("id") or order.get("order_id") or order.get("orderId")
            symbol = order.get("symbol", "N/A")
            
            logger.info(f"\n{'=' * 80}")
            logger.info(f"订单 #{idx} / {len(orders)}")
            logger.info(f"{'=' * 80}")
            
            try:
                await show_order_detail(order_id, symbol)
            except Exception as e:
                logger.warning(f"无法获取订单 {order_id} 的详细信息: {e}")
                logger.info(f"基本信息: {order}")

    except Exception as e:
        logger.exception(f"❌ 查询失败: {e}")
    finally:
        await gateway.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # 查看指定订单的详细信息
        order_id = sys.argv[1]
        symbol = sys.argv[2] if len(sys.argv) > 2 else None
        asyncio.run(show_order_detail(order_id, symbol))
    else:
        # 查看所有当前委托订单的详细信息
        asyncio.run(show_all_orders_with_details())

