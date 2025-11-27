#!/usr/bin/env python3
"""平仓并删除策略

如果策略有持仓，先平仓；如果策略未开单成功，则删除策略
"""

import sys
sys.path.insert(0, '.')

from valuecell.server.db.repositories.strategy_repository import get_strategy_repository
from valuecell.server.services.strategy_persistence import set_strategy_status

def close_and_delete_strategy(strategy_id: str):
    """平仓并删除策略"""
    repo = get_strategy_repository()
    
    print('=' * 80)
    print(f'处理策略: {strategy_id}')
    print('=' * 80)
    
    # 1. 检查策略是否存在
    strategy = repo.get_strategy_by_strategy_id(strategy_id)
    if not strategy:
        print(f'❌ 策略 {strategy_id} 不存在')
        return False
    
    print(f'策略名称: {strategy.name or "N/A"}')
    print(f'当前状态: {strategy.status}')
    
    # 2. 检查持仓
    holdings = repo.get_latest_holdings(strategy_id)
    print(f'持仓数量: {len(holdings)}')
    
    if holdings:
        print('\n⚠️  发现持仓，需要先平仓')
        for h in holdings:
            print(f'  - {h.symbol}: {h.quantity} ({h.type})')
        print('\n注意: 策略停止时会自动尝试平仓')
        print('如果自动平仓失败，请手动在交易所平仓')
    else:
        print('✅ 无持仓')
    
    # 3. 检查交易记录
    details = repo.get_details(strategy_id, limit=10)
    print(f'交易记录数: {len(details)}')
    
    if details:
        print('最近的交易:')
        for d in details[:3]:
            print(f'  - {d.symbol}: {d.type} {d.quantity} @ {d.entry_price or "N/A"}')
    else:
        print('✅ 无交易记录（未开单成功）')
    
    # 4. 停止策略（如果正在运行）
    if strategy.status == 'running':
        print('\n正在停止策略...')
        success = set_strategy_status(strategy_id, "stopped")
        if success:
            print('✅ 策略已停止')
        else:
            print('❌ 停止策略失败')
            return False
    else:
        print(f'\n策略已处于 {strategy.status} 状态')
    
    # 5. 删除策略
    print('\n正在删除策略...')
    try:
        ok = repo.delete_strategy(strategy_id, cascade=True)
        if ok:
            print('✅ 策略已删除')
            print('\n已删除的内容:')
            print('  - 策略记录')
            print('  - 持仓记录')
            print('  - 交易记录')
            print('  - 组合记录')
            print('  - 投资组合快照')
            return True
        else:
            print('❌ 删除策略失败')
            return False
    except Exception as e:
        print(f'❌ 删除策略时出错: {e}')
        return False

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print('用法: python close_and_delete_strategy.py <strategy_id>')
        print('\n示例:')
        print('  python close_and_delete_strategy.py strategy-819890efa7e0421687e7f0a3047abb63')
        sys.exit(1)
    
    strategy_id = sys.argv[1]
    success = close_and_delete_strategy(strategy_id)
    sys.exit(0 if success else 1)

