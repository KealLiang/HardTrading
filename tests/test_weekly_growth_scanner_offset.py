"""
测试周成交量增长扫描器的时间偏移功能

用途：
1. 验证时间偏移功能是否正常工作
2. 演示如何批量扫描历史数据
3. 对比不同日期的候选股池
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def test_single_offset():
    """测试单个时间偏移"""
    from main import find_candidate_stocks_weekly_growth
    
    print("=" * 60)
    print("测试1: 扫描T-1日（昨天）")
    print("=" * 60)
    find_candidate_stocks_weekly_growth(offset_days=1)


def test_batch_offset():
    """批量扫描最近7天"""
    from main import find_candidate_stocks_weekly_growth
    
    print("\n" + "=" * 60)
    print("测试2: 批量扫描最近7天")
    print("=" * 60)
    
    for i in range(7):
        print(f"\n{'='*60}")
        print(f"扫描T-{i}日")
        print('='*60)
        find_candidate_stocks_weekly_growth(offset_days=i)


def test_current_vs_yesterday():
    """对比今天和昨天的扫描结果"""
    from main import find_candidate_stocks_weekly_growth
    import os
    
    print("\n" + "=" * 60)
    print("测试3: 对比今天和昨天的扫描结果")
    print("=" * 60)
    
    # 扫描今天
    print("\n📅 扫描今天（T-0日）")
    find_candidate_stocks_weekly_growth(offset_days=0)
    
    # 扫描昨天
    print("\n📅 扫描昨天（T-1日）")
    find_candidate_stocks_weekly_growth(offset_days=1)
    
    # 读取并对比结果
    print("\n" + "=" * 60)
    print("📊 结果对比")
    print("=" * 60)
    
    from datetime import datetime, timedelta
    today = datetime.now().strftime('%Y%m%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    
    file_today = f'./bin/candidate_stocks_weekly_growth_{today}.txt'
    file_yesterday = f'./bin/candidate_stocks_weekly_growth_{yesterday}.txt'
    
    def read_stocks(filepath):
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return set(line.strip() for line in f if line.strip())
        return set()
    
    stocks_today = read_stocks(file_today)
    stocks_yesterday = read_stocks(file_yesterday)
    
    print(f"\n今天候选股数量: {len(stocks_today)}")
    print(f"昨天候选股数量: {len(stocks_yesterday)}")
    
    common = stocks_today & stocks_yesterday
    only_today = stocks_today - stocks_yesterday
    only_yesterday = stocks_yesterday - stocks_today
    
    print(f"\n共同候选股: {len(common)} 只")
    if common:
        print(f"  {', '.join(sorted(common)[:10])}{'...' if len(common) > 10 else ''}")
    
    print(f"\n仅今天出现: {len(only_today)} 只")
    if only_today:
        print(f"  {', '.join(sorted(only_today)[:10])}{'...' if len(only_today) > 10 else ''}")
    
    print(f"\n仅昨天出现: {len(only_yesterday)} 只")
    if only_yesterday:
        print(f"  {', '.join(sorted(only_yesterday)[:10])}{'...' if len(only_yesterday) > 10 else ''}")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='测试时间偏移功能')
    parser.add_argument('--test', type=str, default='all',
                       choices=['single', 'batch', 'compare', 'all'],
                       help='选择测试类型')
    
    args = parser.parse_args()
    
    if args.test == 'single' or args.test == 'all':
        test_single_offset()
    
    if args.test == 'batch':
        test_batch_offset()
    
    if args.test == 'compare' or args.test == 'all':
        test_current_vs_yesterday()
    
    print("\n✅ 测试完成！") 