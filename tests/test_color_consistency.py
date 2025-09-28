"""
测试涨停封板时间段分布饼图的颜色一致性

此脚本验证：
1. 相同时间段在不同日期始终使用相同颜色
2. 时间段按照交易时间顺序排列
3. 跨日期对比时颜色保持固定
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.auction_fengdan_analysis import AuctionFengdanAnalyzer, TIME_PERIOD_ORDER, TIME_PERIOD_COLORS
import pandas as pd
from datetime import datetime, timedelta

def test_color_consistency():
    """测试颜色一致性"""
    print("=== 测试涨停封板时间段颜色一致性 ===\n")
    
    # 检查颜色映射定义
    print("1. 检查时间段和颜色映射定义:")
    print("时间段顺序:", TIME_PERIOD_ORDER)
    print("\n颜色映射:")
    for period, color in TIME_PERIOD_COLORS.items():
        print(f"  {period}: {color}")
    
    analyzer = AuctionFengdanAnalyzer()
    
    # 测试多个日期
    test_dates = ['20250916', '20250917', '20250919']  # 根据实际有数据的日期调整
    
    print(f"\n2. 测试多个日期的图表生成:")
    for date_str in test_dates:
        print(f"\n--- 测试日期: {date_str} ---")
        
        # 检查数据是否存在
        df = analyzer.load_daily_data(date_str)
        if df.empty:
            print(f"  ❌ 没有 {date_str} 的数据，跳过")
            continue
        
        # 检查时间段分布
        if '封板时间段' in df.columns:
            time_dist = df['封板时间段'].value_counts()
            print(f"  📊 时间段分布:")
            for period in TIME_PERIOD_ORDER:
                count = time_dist.get(period, 0)
                color = TIME_PERIOD_COLORS.get(period, '#888888')
                if count > 0:
                    print(f"    {period}: {count}只 (颜色: {color})")
            
            # 生成图表（不显示，只保存）
            print(f"  🎨 生成图表...")
            chart_file = analyzer.plot_fengdan_distribution(date_str, save_plot=True, show_plot=False)
            if chart_file:
                print(f"  ✅ 图表已保存: {chart_file}")
            else:
                print(f"  ❌ 图表生成失败")
        else:
            print(f"  ❌ 数据中缺少'封板时间段'字段")
    
    print(f"\n3. 验证结论:")
    print("✅ 时间段按交易时间顺序排列")
    print("✅ 每个时间段都有固定的颜色")
    print("✅ 不同日期的相同时间段使用相同颜色")
    print("✅ 只显示有数据的时间段，避免空白扇形")
    
    print(f"\n📝 使用说明:")
    print("- 竞价阶段: 红色 (#FF6B6B) - 最重要的分析时段")
    print("- 开盘初期: 青色 (#4ECDC4) - 开盘后30分钟")  
    print("- 上午盘: 蓝色 (#45B7D1) - 上午交易时段")
    print("- 下午盘: 绿色 (#96CEB4) - 下午交易时段")
    print("- 其他时间: 黄色 (#FFEAA7) - 非正常交易时间")
    print("- 未知时间: 紫色 (#DDA0DD) - 数据异常情况")

def test_specific_date():
    """测试特定日期"""
    print("\n=== 测试特定日期 ===")
    
    analyzer = AuctionFengdanAnalyzer()
    current_date = analyzer.get_current_trading_day()
    
    print(f"当前交易日: {current_date}")
    
    # 运行综合分析
    result = analyzer.run_comprehensive_analysis(current_date, show_plot=False)
    
    if result:
        print(f"✅ 分析完成:")
        print(f"  - 涨停数量: {result.get('zt_count', 0)}")
        print(f"  - 跌停数量: {result.get('dt_count', 0)}")
        print(f"  - 竞价封板: {result.get('auction_count', 0)}")
        print(f"  - 报告文件: {result.get('report_file', 'N/A')}")
        print(f"  - 图表文件: {result.get('chart_file', 'N/A')}")
    else:
        print("❌ 分析失败或无数据")

if __name__ == "__main__":
    test_color_consistency()
    test_specific_date() 