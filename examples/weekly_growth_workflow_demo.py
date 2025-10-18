"""
周成交量增长策略 - 完整工作流演示

展示从候选股扫描到策略分析再到图表生成的完整流程
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import (
    find_candidate_stocks_weekly_growth,
    strategy_scan,
    generate_comparison_charts
)


def demo_current_day_workflow():
    """演示1: 当日完整工作流"""
    print("=" * 80)
    print("演示1: 当日完整工作流")
    print("=" * 80)
    
    # 步骤1: 扫描今日候选股
    print("\n📊 步骤1: 扫描今日候选股...")
    find_candidate_stocks_weekly_growth()
    
    # 步骤2: 策略扫描
    print("\n📈 步骤2: 对候选股应用突破策略扫描...")
    strategy_scan('b')
    
    # 步骤3: 生成对比图表
    print("\n📉 步骤3: 生成对比图表...")
    generate_comparison_charts('b')
    
    print("\n✅ 当日工作流完成！")


def demo_historical_validation():
    """演示2: 历史数据验证（使用时间偏移）"""
    print("\n" + "=" * 80)
    print("演示2: 验证历史策略有效性")
    print("=" * 80)
    
    # 扫描5天前的候选股（用于验证策略）
    print("\n📊 扫描T-5日的候选股（5天前）...")
    find_candidate_stocks_weekly_growth(offset_days=5)
    
    print("\n提示: 现在可以查看这些候选股在后续5天的实际表现，验证策略有效性")
    print("文件位置: ./bin/candidate_temp/candidate_stocks_weekly_growth_{date}.txt")


def demo_batch_analysis():
    """演示3: 批量分析最近一周"""
    print("\n" + "=" * 80)
    print("演示3: 批量分析最近7天")
    print("=" * 80)
    
    print("\n📊 批量扫描最近7天的候选股...")
    for i in range(7):
        print(f"\n{'='*60}")
        print(f"扫描T-{i}日")
        print('='*60)
        find_candidate_stocks_weekly_growth(offset_days=i)
    
    print("\n✅ 批量扫描完成！")
    print("提示: 可以统计这7天筛选出的股票数量和重复率")


def demo_file_flow():
    """演示4: 文件流转说明"""
    print("\n" + "=" * 80)
    print("演示4: 文件流转说明")
    print("=" * 80)
    
    print("""
文件流转过程:

1. find_candidate_stocks_weekly_growth(offset_days=2)
   生成两个文件:
   ├─ ./bin/candidate_temp/candidate_stocks_weekly_growth_20251015.txt  (历史记录)
   └─ ./bin/candidate_temp/candidate_stocks_weekly_growth.txt           (最新结果，自动同步)

2. strategy_scan('b')
   读取: ./bin/candidate_temp/candidate_stocks_weekly_growth.txt
   生成: ./bin/candidate_stocks_breakout_b/...

3. generate_comparison_charts('b')
   读取: ./bin/candidate_stocks_breakout_b/...
   生成: 对比图表

优势:
✅ 无需手动复制文件
✅ 历史记录可追溯
✅ 流程自动衔接
    """)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='周成交量增长策略工作流演示')
    parser.add_argument('--demo', type=str, default='current',
                       choices=['current', 'historical', 'batch', 'files', 'all'],
                       help='选择演示类型')
    
    args = parser.parse_args()
    
    try:
        if args.demo == 'current':
            demo_current_day_workflow()
        elif args.demo == 'historical':
            demo_historical_validation()
        elif args.demo == 'batch':
            demo_batch_analysis()
        elif args.demo == 'files':
            demo_file_flow()
        elif args.demo == 'all':
            print("🚀 开始完整演示...\n")
            demo_file_flow()
            demo_current_day_workflow()
            demo_historical_validation()
        
        print("\n" + "=" * 80)
        print("📚 更多信息请参考: doc/weekly_growth_scanner_strategy.md")
        print("=" * 80)
        
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断")
    except Exception as e:
        print(f"\n\n❌ 错误: {e}")
        import traceback
        traceback.print_exc() 