#!/usr/bin/env python3
"""检查策略持仓数据"""

import sys
sys.path.insert(0, '.')

from valuecell.server.db.repositories.strategy_repository import get_strategy_repository

def check_positions():
    """检查策略持仓"""
    repo = get_strategy_repository()
    strategies = repo.list_strategies_by_status(['running', 'stopped'], limit=10)

    print('=' * 80)
    print('策略持仓检查')
    print('=' * 80)
    
    if not strategies:
        print('没有找到策略')
        return
    
    for s in strategies:
        print(f'\n策略 ID: {s.strategy_id}')
        print(f'状态: {s.status}')
        if s.config:
            exchange_id = s.config.get('exchange_config', {}).get('exchange_id', 'N/A')
            print(f'交易所: {exchange_id}')
        
        # 检查持仓
        holdings = repo.get_latest_holdings(s.strategy_id)
        print(f'持仓数量: {len(holdings)}')
        
        if holdings:
            print('持仓详情:')
            for h in holdings:
                print(f'  - {h.symbol}: {h.quantity} ({h.type})')
                if h.entry_price:
                    print(f'    开仓价格: {h.entry_price}')
                if h.unrealized_pnl is not None:
                    print(f'    未实现盈亏: {h.unrealized_pnl}')
        else:
            print('  (无持仓)')
        
        # 检查最新的 portfolio snapshot
        snapshot = repo.get_latest_portfolio_snapshot(s.strategy_id)
        if snapshot:
            print(f'最新快照时间: {snapshot.snapshot_ts}')
            print(f'总价值: {snapshot.total_value}')
            print(f'现金: {snapshot.cash}')
            if snapshot.total_unrealized_pnl is not None:
                print(f'总未实现盈亏: {snapshot.total_unrealized_pnl}')
        else:
            print('  (无快照数据)')
    
    print('\n' + '=' * 80)

if __name__ == "__main__":
    check_positions()

