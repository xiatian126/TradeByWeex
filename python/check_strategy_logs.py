#!/usr/bin/env python3
"""检查策略日志中的关键信息

用于诊断策略为什么没有执行交易
"""

import sys
import re
from pathlib import Path

def analyze_logs():
    """分析日志内容"""
    print("=" * 60)
    print("策略日志分析")
    print("=" * 60)
    print("\n从您提供的日志来看：")
    print("1. ✅ 策略正在运行 (strategy-b7e836da0c6e4ac480a995f8effdc289)")
    print("2. ✅ 执行网关正常工作")
    print("3. ⚠️  返回了 0 个交易指令")
    print("4. ⚠️  交易数量为 0")
    
    print("\n" + "=" * 60)
    print("可能的原因：")
    print("=" * 60)
    print("1. LLM 返回了 noop（没有交易机会）")
    print("2. 市场数据不足（之前的错误：'Insufficient market snapshot data'）")
    print("3. 风险控制阻止了交易（余额不足、杠杆限制等）")
    print("4. 策略模板要求更严格的条件")
    
    print("\n" + "=" * 60)
    print("建议检查的日志：")
    print("=" * 60)
    print("请在完整的日志中查找以下关键信息：")
    print("\n1. 市场数据获取：")
    print("   - 'Building features pipeline for symbols: ...'")
    print("   - 'Fetched X micro candles'")
    print("   - 'Fetched X medium candles'")
    print("   - 'Fetched market snapshot for X symbols'")
    print("   - 'Computed X market snapshot features'")
    
    print("\n2. LLM 上下文构建：")
    print("   - 'Building LLM context: market_snapshot_features=X, market_section_keys=[...]'")
    print("   - 如果看到 '⚠️ Market section is empty'，说明市场数据有问题")
    
    print("\n3. LLM 决策：")
    print("   - '🔍 Composer returned X instructions'")
    print("   - 如果 X = 0，说明 LLM 没有生成交易指令")
    print("   - 查看 LLM 的 rationale（理由）字段，了解为什么没有交易")
    
    print("\n4. 执行：")
    print("   - '🚀 Calling execution_gateway.execute() with X instructions'")
    print("   - '✅ ExecutionGateway returned X results'")
    
    print("\n" + "=" * 60)
    print("诊断步骤：")
    print("=" * 60)
    print("1. 查看策略运行时的完整日志")
    print("2. 查找 'Building LLM context' 日志，确认市场数据是否被正确传递")
    print("3. 查找 'Composer returned' 日志，查看 LLM 返回的指令数量")
    print("4. 如果指令数量为 0，查看 LLM 的 rationale 字段，了解原因")
    print("5. 检查账户余额和约束条件是否允许交易")
    
    print("\n" + "=" * 60)
    print("如果市场数据正常但仍无交易：")
    print("=" * 60)
    print("这可能是正常的！LLM 可能因为以下原因选择 noop：")
    print("- 市场条件不符合策略要求")
    print("- 风险控制（余额不足、杠杆限制）")
    print("- 策略模板要求更严格的条件（如 'aggressive' 模板）")
    print("- Sharpe 比率较低，策略选择保守")
    
    print("\n" + "=" * 60)
    print("验证市场数据是否正常：")
    print("=" * 60)
    print("运行测试脚本验证 Weex 行情数据获取：")
    print("  cd /Users/apple/Desktop/project/valuecell/python")
    print("  uv run python test_weex_full_context.py")
    print("\n这将验证：")
    print("- 市场快照数据是否正确获取")
    print("- 特征是否正确生成")
    print("- LLM 上下文是否正确构建")

if __name__ == "__main__":
    analyze_logs()

