#!/usr/bin/env python3
"""停止正在运行的策略"""

import sys
import asyncio
sys.path.insert(0, '.')

from valuecell.server.db.repositories.strategy_repository import get_strategy_repository
from valuecell.server.services.strategy_persistence import set_strategy_status

def stop_strategy(strategy_id: str):
    """停止策略"""
    print(f'正在停止策略: {strategy_id}')
    
    # 设置策略状态为 stopped
    success = set_strategy_status(strategy_id, "stopped")
    
    if success:
        print(f'✅ 策略 {strategy_id} 已停止')
    else:
        print(f'❌ 停止策略失败: {strategy_id}')
        print('可能的原因:')
        print('  1. 策略不存在')
        print('  2. 策略已经被停止')
    
    return success

def stop_all_running_strategies():
    """停止所有正在运行的策略"""
    repo = get_strategy_repository()
    strategies = repo.list_strategies_by_status(['running'], limit=100)
    
    if not strategies:
        print('没有正在运行的策略')
        return
    
    print(f'找到 {len(strategies)} 个正在运行的策略')
    print('=' * 80)
    
    for s in strategies:
        print(f'\n策略 ID: {s.strategy_id}')
        print(f'名称: {s.name or "N/A"}')
        success = stop_strategy(s.strategy_id)
        if success:
            print('✅ 已停止')
        else:
            print('❌ 停止失败')
    
    print('\n' + '=' * 80)

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # 停止指定的策略
        strategy_id = sys.argv[1]
        stop_strategy(strategy_id)
    else:
        # 停止所有正在运行的策略
        stop_all_running_strategies()

