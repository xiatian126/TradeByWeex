#!/usr/bin/env python3
"""解释 Sharpe Ratio 和为什么没有下单

帮助用户理解：
1. Sharpe Ratio 是什么
2. 为什么 Sharpe Ratio 可能缺失
3. 为什么策略可能没有下单
"""

print("=" * 70)
print("Sharpe Ratio 和交易决策说明")
print("=" * 70)

print("\n" + "=" * 70)
print("1. Sharpe Ratio 是什么？")
print("=" * 70)
print("""
Sharpe Ratio（夏普比率）是一个风险调整后的收益指标，用于衡量：
- 投资组合的收益是否值得承担的风险
- 公式：(平均收益率 - 无风险利率) / 收益率的标准差

解读：
- < 0:  平均亏损（风险调整后为负）
- 0-1:  正收益但波动性高
- 1-2:  良好的风险调整表现
- > 2:  优秀的风险调整表现

在交易策略中的作用：
- Sharpe < -0.5:  立即停止交易，选择 noop（至少 6 个周期）
- Sharpe -0.5 到 0:  收紧入场条件，降低交易频率
- Sharpe 0 到 0.7:  保持当前纪律，不要过度交易
- Sharpe > 0.7:   策略运行良好，可以考虑适度增加仓位
""")

print("\n" + "=" * 70)
print("2. 为什么 Sharpe Ratio 可能缺失（为 None）？")
print("=" * 70)
print("""
Sharpe Ratio 需要从历史交易记录中计算，需要满足以下条件：

1. 至少需要 2 个历史记录（compose 记录）
   - 策略刚开始运行时，历史记录不足
   - 需要至少运行 2 个决策周期才能计算

2. 需要从历史记录中提取资产价值（equity）
   - 每个 compose 记录需要包含 portfolio 的 total_value
   - 如果记录格式不正确，可能无法提取

3. 需要足够的时间间隔
   - 需要计算收益率，所以需要时间序列数据

当前状态：
- 如果策略刚开始运行，Sharpe Ratio 为 None 是正常的
- 运行几个周期后，应该会有 Sharpe Ratio 值
- 如果一直为 None，可能是历史记录没有正确保存
""")

print("\n" + "=" * 70)
print("3. 为什么策略可能没有下单？")
print("=" * 70)
print("""
可能的原因：

1. LLM 决策返回 noop（没有交易机会）
   - 市场条件不符合策略要求
   - 没有明确的交易信号
   - 这是正常的，不是所有周期都需要交易

2. 市场数据不足
   - 之前的错误："Insufficient market snapshot data"
   - 虽然代码已修复，但需要确认运行时是否正常
   - 检查日志中的 "Building LLM context" 信息

3. 风险控制限制
   - 账户余额不足（free_cash = 0）
   - 杠杆限制
   - 最大持仓数量限制
   - 最小交易金额限制

4. Sharpe Ratio 缺失导致保守策略
   - 如果 Sharpe Ratio 为 None，LLM 可能选择更保守的策略
   - 等待更多数据后再交易

5. 策略模板要求严格
   - "aggressive" 模板可能要求更严格的条件
   - 需要更强的信号才会交易
""")

print("\n" + "=" * 70)
print("4. 如何诊断问题？")
print("=" * 70)
print("""
检查以下日志信息：

1. 市场数据获取：
   - "Building features pipeline for symbols: ..."
   - "Fetched X micro candles"
   - "Fetched X medium candles"
   - "Fetched market snapshot for X symbols"
   - "Computed X market snapshot features"

2. LLM 上下文构建：
   - "Building LLM context: market_snapshot_features=X, market_section_keys=[...]"
   - 如果 market_section_keys 为空，说明市场数据有问题

3. LLM 决策：
   - "🔍 Composer returned X instructions"
   - 如果 X = 0，查看 LLM 的 rationale（理由）
   - rationale 会说明为什么没有交易

4. 账户状态：
   - "free_cash": 可用资金
   - "account_balance": 账户余额
   - "active_positions": 当前持仓数量

5. Sharpe Ratio：
   - "sharpe_ratio": 如果为 null，说明历史数据不足
""")

print("\n" + "=" * 70)
print("5. 解决方案")
print("=" * 70)
print("""
1. 等待几个周期：
   - Sharpe Ratio 需要至少 2 个周期的历史数据
   - 让策略运行一段时间，积累历史记录

2. 检查市场数据：
   - 运行测试脚本验证市场数据获取：
     cd /Users/apple/Desktop/project/valuecell/python
     uv run python test_weex_full_context.py

3. 检查账户余额：
   - 确认账户有足够的资金
   - 检查 free_cash 是否大于 0

4. 查看 LLM 的决策理由：
   - 在日志中查找 "rationale" 字段
   - 了解 LLM 为什么选择 noop

5. 调整策略参数：
   - 如果使用 "aggressive" 模板，可以尝试 "default" 模板
   - 降低最小交易金额限制
   - 调整最大持仓数量
""")

print("\n" + "=" * 70)
print("6. 正常情况说明")
print("=" * 70)
print("""
没有下单不一定是问题！

- 策略可能正确地识别出当前没有好的交易机会
- LLM 可能因为风险控制选择等待更好的时机
- 这是正常的交易行为，不是所有市场条件都适合交易

关键是要查看 LLM 的 rationale，了解决策原因。
如果 rationale 显示"市场数据不足"或"余额不足"，那才是问题。
如果显示"没有明确的交易信号"或"等待更好的机会"，这是正常的。
""")

print("\n" + "=" * 70)

