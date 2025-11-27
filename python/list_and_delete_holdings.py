#!/usr/bin/env python3
"""列出并删除持仓记录

打印持仓记录（主要是 ID），然后删除持仓
"""

import sys
sys.path.insert(0, '.')

from valuecell.server.db.repositories.strategy_repository import get_strategy_repository

def list_and_delete_holdings(strategy_id: str = None, delete: bool = False):
    """列出并删除持仓记录"""
    repo = get_strategy_repository()
    
    print('=' * 80)
    print('持仓记录列表')
    print('=' * 80)
    
    # 获取所有策略的持仓，或指定策略的持仓
    if strategy_id:
        holdings = repo.get_latest_holdings(strategy_id)
        print(f'\n策略 ID: {strategy_id}')
    else:
        # 获取所有策略的持仓
        from valuecell.server.db.models.strategy_holding import StrategyHolding
        from sqlalchemy.orm import Session
        from valuecell.server.db.connection import get_database_manager
        
        session = get_database_manager().get_session()
        try:
            holdings = session.query(StrategyHolding).all()
        finally:
            session.close()
    
    if not holdings:
        print('✅ 没有持仓记录')
        return
    
    print(f'\n找到 {len(holdings)} 条持仓记录:')
    print('-' * 80)
    
    # 按策略分组显示
    holdings_by_strategy = {}
    for h in holdings:
        sid = h.strategy_id
        if sid not in holdings_by_strategy:
            holdings_by_strategy[sid] = []
        holdings_by_strategy[sid].append(h)
    
    # 显示持仓 ID 列表（主要信息）
    print('\n持仓 ID 列表:')
    print('-' * 80)
    holding_ids = []
    
    for sid, h_list in holdings_by_strategy.items():
        print(f'\n策略 ID: {sid} ({len(h_list)} 条持仓)')
        for h in h_list:
            holding_ids.append(h.id)
            print(f'  - 持仓 ID: {h.id} | {h.symbol} | {h.type} | 数量: {h.quantity} | 快照时间: {h.snapshot_ts}')
    
    print('\n' + '=' * 80)
    print(f'总计: {len(holding_ids)} 条持仓记录')
    print(f'持仓 ID: {holding_ids}')
    print('=' * 80)
    
    # 如果指定删除，则删除持仓
    if delete:
        print('\n⚠️  准备删除持仓记录...')
        
        from valuecell.server.db.connection import get_database_manager
        from valuecell.server.db.models.strategy_holding import StrategyHolding
        
        if strategy_id:
            # 删除指定策略的持仓
            session = get_database_manager().get_session()
            try:
                deleted_ids = [h.id for h in holdings]
                deleted = session.query(StrategyHolding).filter(
                    StrategyHolding.strategy_id == strategy_id
                ).delete(synchronize_session=False)
                session.commit()
                print(f'✅ 已删除 {deleted} 条持仓记录（策略: {strategy_id}）')
                print(f'   删除的持仓 ID: {deleted_ids}')
            except Exception as e:
                session.rollback()
                print(f'❌ 删除失败: {e}')
            finally:
                session.close()
        else:
            # 删除所有持仓
            session = get_database_manager().get_session()
            try:
                # 先获取所有 ID
                all_ids = [h.id for h in holdings]
                deleted = session.query(StrategyHolding).delete(synchronize_session=False)
                session.commit()
                print(f'✅ 已删除 {deleted} 条持仓记录（所有策略）')
                print(f'   删除的持仓 ID: {all_ids}')
            except Exception as e:
                session.rollback()
                print(f'❌ 删除失败: {e}')
            finally:
                session.close()
    else:
        print('\n提示: 使用 --delete 参数来删除持仓记录')
        print('示例:')
        if strategy_id:
            print(f'  python list_and_delete_holdings.py --strategy {strategy_id} --delete')
        else:
            print('  python list_and_delete_holdings.py --delete  # 删除所有持仓')
            print('  python list_and_delete_holdings.py --strategy <strategy_id> --delete  # 删除指定策略的持仓')

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='列出并删除持仓记录')
    parser.add_argument('--strategy', type=str, help='策略 ID（可选，不指定则显示所有策略的持仓）')
    parser.add_argument('--delete', action='store_true', help='删除持仓记录')
    
    args = parser.parse_args()
    
    list_and_delete_holdings(strategy_id=args.strategy, delete=args.delete)

