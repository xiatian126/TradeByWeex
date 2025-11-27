#!/usr/bin/env python3
"""检查策略配置和余额"""

import sys
sys.path.insert(0, '.')

from valuecell.server.db.repositories.strategy_repository import get_strategy_repository

def check_config():
    repo = get_strategy_repository()
    strategy = repo.get_strategy_by_strategy_id('strategy-819890efa7e0421687e7f0a3047abb63')
    
    if strategy and strategy.config:
        config = strategy.config
        print('=' * 80)
        print('策略配置检查')
        print('=' * 80)
        print(f'策略 ID: {strategy.strategy_id}')
        print(f'状态: {strategy.status}')
        print(f'名称: {strategy.name or "N/A"}')
        print()
        
        exchange_config = config.get('exchange_config', {})
        print('交易所配置:')
        print(f'  交易所: {exchange_config.get("exchange_id", "N/A")}')
        print(f'  交易模式: {exchange_config.get("trading_mode", "N/A")}')
        print()
        
        trading_config = config.get('trading_config', {})
        print('交易配置:')
        print(f'  初始资金: {trading_config.get("initial_capital", "N/A")}')
        print(f'  交易对: {trading_config.get("symbols", [])}')
        print()
        
        # 检查最新的快照
        snapshot = repo.get_latest_portfolio_snapshot(strategy.strategy_id)
        if snapshot:
            print('最新快照:')
            print(f'  时间: {snapshot.snapshot_ts}')
            print(f'  现金: {snapshot.cash}')
            print(f'  总价值: {snapshot.total_value}')
            print(f'  总未实现盈亏: {snapshot.total_unrealized_pnl}')
            print(f'  总已实现盈亏: {snapshot.total_realized_pnl}')
        
        print('=' * 80)
        print('分析:')
        print('=' * 80)
        if snapshot:
            if snapshot.cash == 0:
                print('⚠️  现金余额为 0')
                if exchange_config.get('trading_mode') == 'live':
                    print('   - LIVE 模式下，余额应该从交易所获取')
                    print('   - 可能的原因:')
                    print('     1. 交易所账户余额确实为 0')
                    print('     2. 余额获取失败（API 问题）')
                    print('     3. 余额被用于开仓（但持仓显示为0，所以不太可能）')
            if snapshot.total_value < 0:
                print('⚠️  总价值为负数，这很不正常')
                print('   - 可能的原因:')
                print('     1. 有未实现的亏损')
                print('     2. 数据计算错误')
    else:
        print('无法获取策略配置')

if __name__ == "__main__":
    check_config()

