#!/usr/bin/env python3
"""查看 Weex 交易所当前委托订单

根据 Weex API 文档: https://www.weex.com/api-doc/zh-CN/ai/orderAPI
使用"获取订单当前委托"接口
"""

import asyncio
import os
from loguru import logger

from valuecell.agents.common.trading.execution.weex_trading import WeexExecutionGateway


async def show_open_orders(symbol: str = None):
    """查看当前委托订单"""
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
        margin_mode="cross",  # 或 "isolated"
    )

    try:
        logger.info("=" * 80)
        logger.info("正在获取 Weex 当前委托订单...")
        if symbol:
            logger.info(f"交易对: {symbol}")
        logger.info("=" * 80)

        # 获取当前委托订单
        orders = await gateway.fetch_open_orders(symbol=symbol)

        if not orders:
            logger.info("✅ 当前无委托订单")
            return

        logger.info(f"📊 当前委托订单数量: {len(orders)}")
        logger.info("")

        # 按交易对分组
        orders_by_symbol = {}
        for order in orders:
            sym = order.get("symbol", "N/A")
            if sym not in orders_by_symbol:
                orders_by_symbol[sym] = []
            orders_by_symbol[sym].append(order)

        # 显示订单详情，并为每个订单获取详细信息
        total_count = 0
        for sym, order_list in orders_by_symbol.items():
            logger.info(f"交易对: {sym} ({len(order_list)} 个订单)")
            logger.info("-" * 80)
            
            for idx, order in enumerate(order_list, 1):
                total_count += 1
                order_id = order.get("id") or order.get("order_id") or order.get("orderId")
                client_oid = order.get("client_oid") or order.get("clientOid")
                
                # 使用 fetch_order 获取订单详细信息
                try:
                    detailed_order = await gateway.fetch_order(order_id, sym)
                    if detailed_order:
                        logger.info(f"订单 #{idx} (ID: {order_id}) - 详细信息")
                        logger.info(f"  交易对: {detailed_order.get('symbol', 'N/A')}")
                        logger.info(f"  客户端订单ID: {detailed_order.get('client_oid') or detailed_order.get('clientOid') or 'N/A'}")
                        logger.info(f"  委托类型: {detailed_order.get('type', 'N/A')}")
                        logger.info(f"  订单类型: {detailed_order.get('order_type', 'N/A')}")
                        logger.info(f"  委托数量: {detailed_order.get('size', 'N/A')}")
                        logger.info(f"  委托价格: {detailed_order.get('price', 'N/A')}")
                        logger.info(f"  成交数量: {detailed_order.get('filled_qty', 'N/A')}")
                        logger.info(f"  成交均价: {detailed_order.get('price_avg', 'N/A')}")
                        logger.info(f"  手续费: {detailed_order.get('fee', 'N/A')}")
                        logger.info(f"  订单状态: {detailed_order.get('status', 'N/A')}")
                        logger.info(f"  总盈亏: {detailed_order.get('totalProfits', 'N/A')}")
                        logger.info(f"  订单张数: {detailed_order.get('contracts', 'N/A')}")
                        logger.info(f"  已成交张数: {detailed_order.get('filledQtyContracts', 'N/A')}")
                        if detailed_order.get('presetTakeProfitPrice'):
                            logger.info(f"  预设止盈价格: {detailed_order.get('presetTakeProfitPrice')}")
                        if detailed_order.get('presetStopLossPrice'):
                            logger.info(f"  预设止损价格: {detailed_order.get('presetStopLossPrice')}")
                        create_time = detailed_order.get('createTime')
                        if create_time:
                            from datetime import datetime
                            try:
                                dt = datetime.fromtimestamp(int(create_time) / 1000)
                                logger.info(f"  创建时间: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                            except:
                                logger.info(f"  创建时间: {create_time}")
                    else:
                        # 如果获取详细信息失败，显示基本信息
                        logger.info(f"订单 #{idx} (ID: {order_id}) - 基本信息")
                        logger.info(f"  客户端订单ID: {client_oid or 'N/A'}")
                        logger.info(f"  方向: {order.get('side', 'N/A')}")
                        logger.info(f"  订单类型: {order.get('type', 'N/A')}")
                        logger.info(f"  数量: {order.get('amount') or order.get('size') or 'N/A'}")
                        logger.info(f"  价格: {order.get('price') or order.get('limit_price') or '市价'}")
                        logger.info(f"  已成交: {order.get('filled') or order.get('filled_qty') or 0.0}")
                        logger.info(f"  状态: {order.get('status', 'N/A')}")
                except Exception as e:
                    logger.warning(f"  无法获取订单 {order_id} 的详细信息: {e}")
                    # 显示基本信息
                    logger.info(f"订单 #{idx} (ID: {order_id}) - 基本信息")
                    logger.info(f"  客户端订单ID: {client_oid or 'N/A'}")
                    logger.info(f"  方向: {order.get('side', 'N/A')}")
                    logger.info(f"  订单类型: {order.get('type', 'N/A')}")
                    logger.info(f"  数量: {order.get('amount') or order.get('size') or 'N/A'}")
                    logger.info(f"  价格: {order.get('price') or order.get('limit_price') or '市价'}")
                    logger.info(f"  已成交: {order.get('filled') or order.get('filled_qty') or 0.0}")
                    logger.info(f"  状态: {order.get('status', 'N/A')}")
                
                logger.info("")

        logger.info("=" * 80)
        logger.info(f"总计: {total_count} 个委托订单")
        logger.info("=" * 80)

    except Exception as e:
        logger.exception(f"❌ 查询订单失败: {e}")
    finally:
        await gateway.close()


if __name__ == "__main__":
    import sys
    
    symbol = None
    if len(sys.argv) > 1:
        symbol = sys.argv[1]
    
    asyncio.run(show_open_orders(symbol=symbol))

