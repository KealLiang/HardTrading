"""
诊断脚本：检查策略扫描中的未来数据泄漏问题

用法：
1. 对比不同数据截止日期的扫描结果
2. 检查VCP分数计算是否使用未来数据
3. 验证10/17信号在不同数据条件下的差异
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import backtrader as bt
from datetime import datetime, timedelta
from bin.scanner_analyzer import _scan_single_stock_analyzer
from bin.simulator import read_stock_data
from strategy.breakout_strategy import BreakoutStrategy
from utils import date_util


def diagnose_single_stock(code, scan_start_date='20250730'):
    """
    诊断单只股票，对比截止到10/17和10/18时的扫描结果
    """
    print(f"\n{'='*70}")
    print(f"诊断股票: {code}")
    print(f"{'='*70}")
    
    # 信号模式
    signal_patterns = ['*** 二次确认信号']
    
    # 读取原始数据
    data_path = './data/astocks'
    df_full = read_stock_data(code, data_path)
    
    if df_full is None or df_full.empty:
        print(f"❌ 无法读取股票 {code} 的数据")
        return
    
    print(f"\n📊 数据信息:")
    print(f"  - 数据起始日期: {df_full.index[0].strftime('%Y-%m-%d')}")
    print(f"  - 数据结束日期: {df_full.index[-1].strftime('%Y-%m-%d')}")
    print(f"  - 总数据天数: {len(df_full)}")
    
    # 场景1: 截止到10/17
    end_date_1 = '20251017'
    print(f"\n🔍 场景1: 数据截止到 {end_date_1}")
    signals_1 = _scan_single_stock_analyzer(
        code, BreakoutStrategy, None, data_path,
        scan_start_date, end_date_1, signal_patterns
    )
    
    if signals_1:
        print(f"  ✅ 找到 {len(signals_1)} 个信号:")
        for sig in signals_1:
            print(f"    - 日期: {sig['datetime']}, 价格: {sig['close']:.2f}")
            print(f"      详情: {sig.get('details', '')[:100]}...")
    else:
        print(f"  ❌ 未找到信号")
    
    # 场景2: 截止到10/18  
    end_date_2 = '20251018'
    print(f"\n🔍 场景2: 数据截止到 {end_date_2}")
    signals_2 = _scan_single_stock_analyzer(
        code, BreakoutStrategy, None, data_path,
        scan_start_date, end_date_2, signal_patterns
    )
    
    if signals_2:
        print(f"  ✅ 找到 {len(signals_2)} 个信号:")
        for sig in signals_2:
            print(f"    - 日期: {sig['datetime']}, 价格: {sig['close']:.2f}")
            print(f"      详情: {sig.get('details', '')[:100]}...")
    else:
        print(f"  ❌ 未找到信号")
    
    # 对比分析
    print(f"\n📊 对比分析:")
    if signals_1 is None and signals_2 is None:
        print("  ⚠️  两个场景都扫描失败")
    elif signals_1 is None:
        print("  ⚠️  场景1扫描失败，场景2成功")
    elif signals_2 is None:
        print("  ⚠️  场景1成功，场景2扫描失败")
    else:
        # 提取10/17的信号
        oct17_signals_1 = [s for s in signals_1 if s['datetime'].strftime('%Y-%m-%d') == '2025-10-17']
        oct17_signals_2 = [s for s in signals_2 if s['datetime'].strftime('%Y-%m-%d') == '2025-10-17']
        
        print(f"  - 场景1中10/17的信号数: {len(oct17_signals_1)}")
        print(f"  - 场景2中10/17的信号数: {len(oct17_signals_2)}")
        
        if len(oct17_signals_1) != len(oct17_signals_2):
            print(f"\n  ⚠️ 【发现差异】增加10/18数据后，10/17的信号数量发生变化！")
            print(f"  这表明策略可能使用了未来数据（10/18）来判断10/17的信号")
            
            # 详细对比
            if len(oct17_signals_2) > len(oct17_signals_1):
                print(f"\n  新增的信号:")
                for sig in oct17_signals_2:
                    if sig not in oct17_signals_1:
                        print(f"    {sig.get('details', '')[:150]}")
        else:
            print(f"  ✅ 10/17的信号数量一致，未发现明显的未来数据泄漏")


def check_vcp_future_data_usage():
    """
    检查VCP分数计算中的未来数据使用
    """
    print(f"\n{'='*70}")
    print("VCP分数计算中的未来数据使用检查")
    print(f"{'='*70}")
    
    print("\n📖 代码分析:")
    print("在 strategy/breakout_strategy.py 的 _calculate_vcp_score() 方法中:")
    print("```python")
    print("days_since_signal = (len(self.data) - 1) - self.signal_day_index")
    print("start_offset = days_since_signal + 1  # ⚠️ 关键点")
    print("end_offset = start_offset + lookback")
    print("recent_highs = [self.data.high[-j] for j in range(start_offset, end_offset)]")
    print("```")
    
    print("\n⚠️ 问题:")
    print("  - start_offset = days_since_signal + 1 意味着从信号日的【下一天】开始查看")
    print("  - 这会使用信号日【之后】的数据来计算VCP分数")
    print("  - 虽然VCP不直接影响买卖决策，但可能影响策略的内部状态")
    
    print("\n💡 影响:")
    print("  - 如果数据只到10/17，计算10/17信号的VCP时，数据可能不足")
    print("  - 如果数据到10/18，计算10/17信号的VCP时，会使用10/18的数据")
    print("  - 这可能导致VCP分数不同，进而影响日志输出或异常处理")


def main():
    """主函数"""
    print("="*70)
    print("策略扫描未来数据泄漏诊断工具")
    print("="*70)
    
    # 首先做代码分析
    check_vcp_future_data_usage()
    
    # 从扫描结果文件中提取10/17有信号的股票
    print(f"\n{'='*70}")
    print("从扫描结果中提取需要诊断的股票")
    print(f"{'='*70}")
    
    result_file = 'bin/candidate_stocks_breakout_b/scan_summary_20250730-20251020.txt'
    
    if not os.path.exists(result_file):
        print(f"❌ 结果文件不存在: {result_file}")
        return
    
    # 提取10/17有信号的股票
    oct17_stocks = []
    with open(result_file, 'r', encoding='utf-8') as f:
        for line in f:
            if '2025-10-17' in line:
                # 提取股票代码（格式：股票: 000531 穗恒运Ａ）
                parts = line.split('股票:')
                if len(parts) > 1:
                    code = parts[1].strip().split()[0]
                    oct17_stocks.append(code)
    
    print(f"\n找到 {len(oct17_stocks)} 只在10/17有信号的股票:")
    for code in oct17_stocks[:5]:  # 只显示前5个
        print(f"  - {code}")
    
    if len(oct17_stocks) > 5:
        print(f"  ... 还有 {len(oct17_stocks) - 5} 只")
    
    # 选择几只股票进行详细诊断
    test_stocks = oct17_stocks[:3] if oct17_stocks else []
    
    if not test_stocks:
        print("\n⚠️  没有找到10/17的信号股票，将使用默认测试股票")
        test_stocks = ['000531', '002279', '002940']
    
    print(f"\n将对以下股票进行详细诊断:")
    for code in test_stocks:
        print(f"  - {code}")
    
    # 逐个诊断
    for code in test_stocks:
        diagnose_single_stock(code)
    
    # 总结
    print(f"\n{'='*70}")
    print("诊断总结")
    print(f"{'='*70}")
    print("\n如果上述诊断显示：")
    print("  1. 场景1（数据到10/17）和场景2（数据到10/18）的10/17信号【数量不同】")
    print("     → 确认存在未来数据泄漏问题")
    print("\n  2. 场景1扫描失败，场景2成功")
    print("     → 可能是数据不足导致的，需要检查VCP计算的数据要求")
    print("\n  3. 两个场景的10/17信号数量【一致】")
    print("     → 未来数据泄漏问题不明显，可能是其他原因")
    
    print("\n💡 建议修复方案:")
    print("  - 修改 _calculate_vcp_score() 中的供给吸收分计算逻辑")
    print("  - 将 start_offset = days_since_signal + 1 改为 start_offset = days_since_signal")
    print("  - 或者在信号日不计算VCP分数，延后到下一天再计算")


if __name__ == '__main__':
    main() 