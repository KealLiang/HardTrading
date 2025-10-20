"""
测试同一天信号的一致性

场景对比：
A1: 在10/20使用数据截止到10/20，扫描10/17的信号
A2: 在10/17使用数据截止到10/17，扫描10/17的信号

检查A1和A2是否一致
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from bin.scanner_analyzer import _scan_single_stock_analyzer
from strategy.breakout_strategy import BreakoutStrategy


def analyze_signal_consistency():
    """分析可能导致信号不一致的因素"""
    
    print("="*80)
    print("同一天信号一致性分析")
    print("="*80)
    
    print("\n【场景定义】")
    print("-" * 80)
    print("A1: 在10/20执行扫描，使用数据到10/20，看10/17的信号")
    print("A2: 在10/17执行扫描，使用数据到10/17，看10/17的信号")
    
    print("\n【可能导致A1 ≠ A2的因素】")
    print("-" * 80)
    
    print("\n1️⃣ 候选列表差异")
    print("   问题: 候选列表a在10/17和10/20时是否相同？")
    print("   分析:")
    print("   - 如果候选列表是手动维护的 → 可能不同")
    print("   - 如果候选列表是程序生成的 → 取决于生成逻辑")
    print("   - 如果候选列表是静态文件 → 应该相同")
    
    print("\n2️⃣ 数据修正/更新")
    print("   问题: 个股历史数据在10/17到10/20之间是否发生变化？")
    print("   分析:")
    print("   - 数据源可能会修正历史数据（如除权除息调整）")
    print("   - 停牌复牌可能导致数据变化")
    print("   - 这会影响技术指标的计算")
    
    print("\n3️⃣ 观察期状态依赖")
    print("   问题: BreakoutStrategy的观察期状态是否依赖未来数据？")
    print("   分析:")
    print("   - 10/17的二次确认信号需要先触发初始突破信号")
    print("   - 初始突破信号可能在10/15或更早触发")
    print("   - 关键：初始信号的触发条件是否依赖10/17之后的数据？")
    
    print("\n4️⃣ 扫描日期范围")
    print("   问题: scan_start_date是否影响结果？")
    print("   分析:")
    print("   - 如果scan_start_date都是'20250730'，应该一致")
    print("   - 但如果scan_start_date不同，可能影响数据预热期")


def check_observation_period_logic():
    """检查观察期逻辑是否可能导致差异"""
    
    print("\n" + "="*80)
    print("观察期逻辑分析")
    print("="*80)
    
    print("\n【BreakoutStrategy工作流程】")
    print("-" * 80)
    print("假设时间线：")
    print("  10/15: 触发初始突破信号 → 进入观察期（15天）")
    print("  10/16: 观察期第2天")
    print("  10/17: 观察期第3天 → 触发二次确认信号（蓄势待发）")
    print("  10/18: 买入成交")
    
    print("\n【场景A2：在10/17扫描，数据到10/17】")
    print("  - 策略从头运行，处理10/15的K线 → 触发初始突破")
    print("  - 继续处理10/16的K线 → 观察期第2天")
    print("  - 继续处理10/17的K线 → 检测到二次确认条件 ✓")
    print("  - 结果：捕获10/17的信号")
    
    print("\n【场景A1：在10/20扫描，数据到10/20】")
    print("  - 策略从头运行，处理10/15的K线 → 触发初始突破")
    print("  - 继续处理10/16的K线 → 观察期第2天")
    print("  - 继续处理10/17的K线 → 检测到二次确认条件 ✓")
    print("  - 继续处理10/18的K线 → （已经触发买入）")
    print("  - 结果：捕获10/17的信号（信号在10/17就已经确定）")
    
    print("\n【理论结论】")
    print("  ✅ 从逻辑上看，A1和A2应该一致")
    print("  原因：二次确认信号在10/17就已经触发，不依赖10/18~10/20的数据")


def check_potential_issues():
    """检查可能导致不一致的具体问题"""
    
    print("\n" + "="*80)
    print("潜在问题检查")
    print("="*80)
    
    print("\n【需要验证的点】")
    print("-" * 80)
    
    print("\n1. 观察期状态是否正确重置？")
    print("   代码位置: strategy/breakout_strategy.py")
    print("   关键变量: self.observation_mode, self.observation_counter")
    print("   问题: 如果状态没有正确重置，可能影响后续扫描")
    print("   验证: 每次cerebro.run()都会创建新的策略实例 ✓")
    
    print("\n2. 二次确认信号的过滤器是否依赖未来数据？")
    print("   过滤器1: 动态价格接受窗口")
    print("   - sentry_highest_high: 观察期内的最高价")
    print("   - 问题: 这个值在10/17时和10/20时是否相同？")
    print("   - 分析: 只要观察期是从10/15开始，10/17时的highest_high应该一致")
    
    print("\n   过滤器2: 过热分数")
    print("   - last_overheat_score: 基于当前K线计算")
    print("   - 问题: 在10/17这天计算，结果应该一致")
    
    print("\n   过滤器3: VCP分数")
    print("   - 仅用于日志输出，不影响信号")
    
    print("\n3. SignalCaptureAnalyzer是否正确捕获信号？")
    print("   - 信号日期: self.strategy.datas[0].datetime.datetime(0).date()")
    print("   - 这是10/17当天的日期，不依赖未来数据 ✓")


def test_real_scenario():
    """实际测试场景"""
    
    print("\n" + "="*80)
    print("实际测试")
    print("="*80)
    
    # 选择一个测试股票
    test_code = '000531'  # 穗恒运Ａ，在10/17有信号
    
    print(f"\n测试股票: {test_code}")
    print("-" * 80)
    
    signal_patterns = ['*** 二次确认信号']
    data_path = './data/astocks'
    scan_start = '20250730'
    
    # 场景A2: 数据到10/17
    print("\n【场景A2】数据截止到10/17")
    signals_a2 = _scan_single_stock_analyzer(
        test_code, BreakoutStrategy, None, data_path,
        scan_start, '20251017', signal_patterns
    )
    
    if signals_a2:
        oct17_signals_a2 = [s for s in signals_a2 if s['datetime'].strftime('%Y-%m-%d') == '2025-10-17']
        print(f"  10/17的信号数: {len(oct17_signals_a2)}")
        if oct17_signals_a2:
            print(f"  信号详情: {oct17_signals_a2[0]['details'][:100]}...")
    else:
        print("  未找到信号")
    
    # 场景A1: 数据到10/20
    print("\n【场景A1】数据截止到10/20")
    signals_a1 = _scan_single_stock_analyzer(
        test_code, BreakoutStrategy, None, data_path,
        scan_start, '20251020', signal_patterns
    )
    
    if signals_a1:
        oct17_signals_a1 = [s for s in signals_a1 if s['datetime'].strftime('%Y-%m-%d') == '2025-10-17']
        print(f"  10/17的信号数: {len(oct17_signals_a1)}")
        if oct17_signals_a1:
            print(f"  信号详情: {oct17_signals_a1[0]['details'][:100]}...")
    else:
        print("  未找到信号")
    
    # 对比
    print("\n【对比结果】")
    print("-" * 80)
    
    if signals_a1 is None or signals_a2 is None:
        print("  ⚠️  某个场景扫描失败")
    else:
        oct17_a1 = [s for s in signals_a1 if s['datetime'].strftime('%Y-%m-%d') == '2025-10-17']
        oct17_a2 = [s for s in signals_a2 if s['datetime'].strftime('%Y-%m-%d') == '2025-10-17']
        
        if len(oct17_a1) == len(oct17_a2):
            print(f"  ✅ A1和A2的10/17信号数量一致: {len(oct17_a1)}")
            
            # 进一步对比细节
            if oct17_a1 and oct17_a2:
                price_diff = abs(oct17_a1[0]['close'] - oct17_a2[0]['close'])
                if price_diff < 0.01:
                    print(f"  ✅ 信号价格一致: {oct17_a1[0]['close']:.2f}")
                else:
                    print(f"  ⚠️  信号价格不同: A1={oct17_a1[0]['close']:.2f}, A2={oct17_a2[0]['close']:.2f}")
        else:
            print(f"  ⚠️  A1和A2的信号数量不同: A1={len(oct17_a1)}, A2={len(oct17_a2)}")


def main():
    print("\n" + "="*80)
    print("同一天信号一致性完整检查")
    print("="*80)
    
    analyze_signal_consistency()
    check_observation_period_logic()
    check_potential_issues()
    test_real_scenario()
    
    print("\n" + "="*80)
    print("结论")
    print("="*80)
    
    print("\n【理论分析】")
    print("  ✅ 从策略逻辑看，A1和A2应该一致")
    print("  ✅ 二次确认信号在10/17触发，不依赖10/18~10/20的数据")
    print("  ✅ backtrader每次都重新运行策略，不存在状态污染")
    
    print("\n【可能的差异来源】")
    print("  1. 候选列表在10/17和10/20时不同 → 股票池不同")
    print("  2. 数据源在10/17到10/20之间修正了历史数据 → 技术指标变化")
    print("  3. （不太可能）策略实现有bug")
    
    print("\n【验证方法】")
    print("  1. 保存候选列表的历史版本，确保使用相同的股票池")
    print("  2. 如果发现差异，检查个股数据是否被修正")
    print("  3. 使用上述测试脚本进行实际验证")
    
    print("\n" + "="*80)


if __name__ == '__main__':
    main() 