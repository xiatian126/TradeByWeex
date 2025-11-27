#!/usr/bin/env python3
"""查看 Weex 账户资产

根据 Weex API 文档: https://www.weex.com/api-doc/zh-CN/contract/Account_API/GetAccountBalance
使用 GET /capi/v2/account/assets 接口获取账户资产
"""

import asyncio
import os
from loguru import logger
import httpx

from valuecell.agents.common.trading.execution.weex_trading import WeexExecutionGateway


async def show_account_assets():
    """查看账户资产"""
    # API 凭证
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
        logger.info("正在获取 Weex 账户资产...")
        logger.info("=" * 80)

        # 使用 /capi/v2/account/assets 接口获取账户资产
        request_path = "/capi/v2/account/assets"
        headers = gateway._get_headers("GET", request_path, "", "")
        
        client = await gateway._get_client()
        try:
            response = await client.get(request_path, headers=headers)
            response.raise_for_status()
            result = response.json()
            
            # Weex API 返回数组格式
            assets = result if isinstance(result, list) else result.get("data", [])
            
            if not assets:
                logger.info("✅ 账户无资产")
                return
            
            logger.info(f"\n📊 账户资产数量: {len(assets)}")
            logger.info("")
            
            # 计算总资产
            total_equity = 0.0
            total_available = 0.0
            total_frozen = 0.0
            total_unrealized_pnl = 0.0
            
            # 币种 ID 到名称的映射（常见币种）
            coin_id_map = {
                1: "BTC",
                2: "USDT",
                3: "ETH",
            }
            
            logger.info("账户资产详情:")
            logger.info("-" * 80)
            
            for asset in assets:
                coin_id = asset.get("coinId")
                coin_name = asset.get("coinName") or coin_id_map.get(coin_id, f"COIN_{coin_id}")
                available = float(asset.get("available", 0.0) or 0.0)
                frozen = float(asset.get("frozen", 0.0) or 0.0)
                equity = float(asset.get("equity", 0.0) or 0.0)
                unrealized_pnl = float(asset.get("unrealizePnl") or asset.get("unrealizedPnl", 0.0) or 0.0)
                
                logger.info(f"\n币种: {coin_name} (ID: {coin_id})")
                logger.info(f"  可用资产: {available}")
                logger.info(f"  冻结资产: {frozen}")
                logger.info(f"  全部资产: {equity}")
                logger.info(f"  未实现盈亏: {unrealized_pnl}")
                
                # 累计统计（只统计 USDT 或主要币种）
                if coin_name.upper() in ("USDT", "USD", "USDC"):
                    total_equity += equity
                    total_available += available
                    total_frozen += frozen
                    total_unrealized_pnl += unrealized_pnl
            
            logger.info("\n" + "=" * 80)
            logger.info("资产汇总 (USDT/USD/USDC):")
            logger.info(f"  总可用资产: {total_available}")
            logger.info(f"  总冻结资产: {total_frozen}")
            logger.info(f"  总资产: {total_equity}")
            logger.info(f"  总未实现盈亏: {total_unrealized_pnl}")
            logger.info("=" * 80)
            
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ HTTP 错误: {e.response.status_code}")
            logger.error(f"响应: {e.response.text}")
            raise
        except Exception as e:
            logger.exception(f"❌ 获取账户资产失败: {e}")
            raise

    except Exception as e:
        logger.exception(f"❌ 查询失败: {e}")
    finally:
        await gateway.close()


if __name__ == "__main__":
    asyncio.run(show_account_assets())

