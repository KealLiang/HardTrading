"""
数据一致性检查工具

用途：检查同一只股票在不同时间下载的数据是否有差异
特别是检查历史数据是否被修正（除权除息、纠错等）
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from bin.simulator import read_stock_data


def check_historical_data_changes(code, check_date):
    """
    检查指定日期的历史数据是否被修正
    
    参数:
        code: 股票代码
        check_date: 要检查的历史日期（如'2025-10-15'）
    """
    print("="*80)
    print(f"历史数据一致性检查: {code} @ {check_date}")
    print("="*80)
    
    # 读取当前数据
    df = read_stock_data(code, './data/astocks')
    
    if df is None:
        print(f"❌ 无法读取股票 {code} 的数据")
        return
    
    # 检查指定日期的数据
    check_date_dt = pd.to_datetime(check_date)
    
    if check_date_dt not in df.index:
        print(f"❌ 数据中不存在 {check_date} 这一天")
        return
    
    # 获取该日数据
    row = df.loc[check_date_dt]
    
    print(f"\n📊 {check_date} 的数据:")
    print(f"  开盘: {row['open']:.2f}")
    print(f"  收盘: {row['close']:.2f}")
    print(f"  最高: {row['high']:.2f}")
    print(f"  最低: {row['low']:.2f}")
    print(f"  成交量: {row['volume']:.0f}")
    
    print("\n💡 如何检查是否被修正：")
    print("  1. 保存今天的数据快照:")
    print(f"     df.to_csv('data_snapshot_{code}_20251020.csv')")
    print("  2. 明天重新下载数据后，对比:")
    print(f"     df_old = pd.read_csv('data_snapshot_{code}_20251020.csv')")
    print(f"     df_new = read_stock_data('{code}', './data/astocks')")
    print(f"     # 对比 {check_date} 的数据是否一致")
    
    return row


def compare_two_dataframes(df1, df2, date_range=None):
    """
    对比两个DataFrame在指定日期范围内的差异
    
    参数:
        df1: 第一个DataFrame（如10/17下载的）
        df2: 第二个DataFrame（如10/20下载的）
        date_range: 要对比的日期范围，如('2025-10-01', '2025-10-17')
    """
    print("\n" + "="*80)
    print("数据对比分析")
    print("="*80)
    
    if date_range:
        start, end = date_range
        df1 = df1.loc[start:end]
        df2 = df2.loc[start:end]
    
    # 检查日期是否一致
    dates_match = df1.index.equals(df2.index)
    print(f"\n日期索引是否一致: {'✅ 是' if dates_match else '❌ 否'}")
    
    if not dates_match:
        print("  ⚠️  两个数据的日期范围不同，可能数据更新了")
        return
    
    # 检查价格数据
    price_cols = ['open', 'close', 'high', 'low']
    has_diff = False
    
    for col in price_cols:
        diff = (df1[col] - df2[col]).abs()
        max_diff = diff.max()
        
        if max_diff > 0.01:  # 差异超过0.01元
            has_diff = True
            diff_dates = diff[diff > 0.01].index
            print(f"\n⚠️  发现 {col} 数据差异:")
            print(f"  最大差异: {max_diff:.2f} 元")
            print(f"  差异天数: {len(diff_dates)} 天")
            print(f"  示例（前5个）:")
            for date in diff_dates[:5]:
                print(f"    {date.strftime('%Y-%m-%d')}: "
                      f"旧={df1.loc[date, col]:.2f}, "
                      f"新={df2.loc[date, col]:.2f}, "
                      f"差={diff.loc[date]:.2f}")
    
    if not has_diff:
        print("\n✅ 历史数据完全一致，未发现修正")
    
    return has_diff


def explain_scenario():
    """详细解释数据变化的影响"""
    
    print("\n" + "="*80)
    print("详细说明：什么样的数据变化会影响A1和A2？")
    print("="*80)
    
    print("\n【场景定义】")
    print("  A1: 10/20执行，使用10/20下载的数据，扫描10/17的信号")
    print("  A2: 10/17执行，使用10/17下载的数据，扫描10/17的信号")
    
    print("\n【不会影响的数据变化】✅")
    print("  - 10/18、10/19、10/20的新数据")
    print("    原因：扫描10/17的信号只用到10/17及之前的数据")
    print("    验证：已通过测试证实")
    
    print("\n【会影响的数据变化】⚠️")
    print("  - 10/17及之前任何一天的历史数据被修正")
    print("    例如：10/15的收盘价从6.80改成6.60")
    print("    原因：会影响技术指标（布林带、均线等）的计算")
    print("    结果：可能导致信号判断不同")
    
    print("\n【具体例子】")
    print("  假设10/15触发初始突破信号的条件是：")
    print("    close[10/15] > bband.top[10/15]")
    print("    6.80 > 6.75  ✓ 突破")
    
    print("\n  如果10/15的价格在10/17到10/20之间被修正：")
    print("    A2看到的: 6.80 > 6.75  ✓ 触发")
    print("    A1看到的: 6.60 > 6.75  ✗ 不触发")
    
    print("\n  结果：")
    print("    A2: 10/15触发初始突破 → 10/17触发二次确认 ✓")
    print("    A1: 10/15未触发初始突破 → 10/17不会有二次确认 ✗")


def main():
    print("="*80)
    print("数据一致性检查工具")
    print("="*80)
    
    explain_scenario()
    
    print("\n" + "="*80)
    print("使用建议")
    print("="*80)
    
    print("\n1️⃣ 如果你怀疑数据被修正，可以：")
    print("   - 今天保存数据快照")
    print("   - 明天重新下载后对比")
    print("   - 使用本脚本的compare_two_dataframes函数")
    
    print("\n2️⃣ 检查具体股票的历史数据：")
    print("   示例代码：")
    print("   ```python")
    print("   from tests.check_data_consistency import check_historical_data_changes")
    print("   check_historical_data_changes('000531', '2025-10-15')")
    print("   ```")
    
    print("\n3️⃣ 对比两个数据文件：")
    print("   示例代码：")
    print("   ```python")
    print("   from tests.check_data_consistency import compare_two_dataframes")
    print("   import pandas as pd")
    print("   df1 = pd.read_csv('data_snapshot_20251017.csv')")
    print("   df2 = pd.read_csv('data_snapshot_20251020.csv')")
    print("   compare_two_dataframes(df1, df2, ('2025-10-01', '2025-10-17'))")
    print("   ```")
    
    print("\n" + "="*80)
    print("结论")
    print("="*80)
    
    print("\n✅ 正常情况下，A1和A2应该一致")
    print("   因为策略不使用未来数据")
    
    print("\n⚠️  如果A1≠A2，可能原因：")
    print("   1. 候选列表不同（最常见）")
    print("   2. 历史数据被修正（较少见，但可能发生）")
    print("   3. 策略实现有bug（已验证，可能性极低）")
    
    print("\n💡 最佳实践：")
    print("   - 保存候选列表历史版本")
    print("   - 如果需要极高精度，保存数据快照")
    print("   - 使用本工具定期检查数据一致性")
    
    print("\n" + "="*80)


if __name__ == '__main__':
    main() 