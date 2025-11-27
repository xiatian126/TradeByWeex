#!/usr/bin/env python3
"""检查策略状态和最近的交易记录"""

import sys
sys.path.insert(0, '.')

from valuecell.server.db.repositories.strategy_repository import get_strategy_repository

def check_strategy_status():
    """检查策略状态"""
    repo = get_strategy_repository()
    
    # 获取所有策略
    strategies = repo.list_strategies_by_status(['running', 'stopped'], limit=10)
    
    print('=' * 80)
    print('策略状态检查')
    print('=' * 80)
    
    for s in strategies:
        print(f'\n策略 ID: {s.strategy_id}')
        print(f'状态: {s.status}')
        print(f'名称: {s.name or "N/A"}')
        
        # 检查最近的交易记录
        details = repo.get_details(s.strategy_id, limit=5)
        print(f'最近的交易记录数: {len(details)}')
        
        if details:
            print('最近的交易:')
            for d in details[:3]:
                print(f'  - {d.symbol}: {d.type} {d.quantity} @ {d.entry_price or "N/A"}')
                if d.realized_pnl is not None:
                    print(f'    已实现盈亏: {d.realized_pnl}')
        else:
            print('  (无交易记录)')
        
        # 检查持仓
        holdings = repo.get_latest_holdings(s.strategy_id)
        print(f'持仓数量: {len(holdings)}')
        
        # 检查最新的 portfolio snapshot
        snapshot = repo.get_latest_portfolio_snapshot(s.strategy_id)
        if snapshot:
            print(f'最新快照: {snapshot.snapshot_ts}')
            print(f'  总价值: {snapshot.total_value}')
            print(f'  现金: {snapshot.cash}')
    
    print('\n' + '=' * 80)
    print('说明:')
    print('=' * 80)
    print('1. 如果"持仓数量"为 0，说明策略还没有成功开仓')
    print('2. 如果"最近的交易记录数"为 0，说明策略还没有执行任何交易')
    print('3. 持仓数据只有在策略成功开仓后才会显示在页面上')
    print('4. 请检查策略日志，确认是否有订单成功执行')

if __name__ == "__main__":
    check_strategy_status()

