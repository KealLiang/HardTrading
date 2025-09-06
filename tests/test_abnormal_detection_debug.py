#!/usr/bin/env python3
"""
异动检测调试脚本 - 专门用于调试吉视传媒的异动预警问题
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from analysis.abnormal_movement_detector import AbnormalMovementDetector
from datetime import datetime

def test_jishi_chuanmei():
    """测试吉视传媒的异动检测"""
    
    # 创建异动检测器
    detector = AbnormalMovementDetector()
    
    # 吉视传媒的股票代码（根据截图，应该是600929）
    stock_code = "600929"  # 吉视传媒
    
    # 测试日期（根据截图，应该是2025年9月5日左右）
    test_dates = [
        "20250905",
        "20250904", 
        "20250903",
        "20250902"
    ]
    
    print(f"=== 测试股票: {stock_code} (吉视传媒) ===\n")
    
    for test_date in test_dates:
        print(f"检查日期: {test_date}")
        print("-" * 50)
        
        try:
            # 1. 计算各周期的偏离值
            deviation_3d = detector.calculate_deviation_values(stock_code, test_date, 3)
            deviation_10d = detector.calculate_deviation_values(stock_code, test_date, 10)
            deviation_30d = detector.calculate_deviation_values(stock_code, test_date, 30)
            
            print(f"3日偏离值: {deviation_3d}")
            print(f"10日偏离值: {deviation_10d}")
            print(f"30日偏离值: {deviation_30d}")
            
            if deviation_3d:
                cumulative_3d = sum(deviation_3d)
                print(f"3日累计偏离值: {cumulative_3d:.2f}%")
            
            if deviation_10d:
                cumulative_10d = sum(deviation_10d)
                print(f"10日累计偏离值: {cumulative_10d:.2f}%")
                
            if deviation_30d:
                cumulative_30d = sum(deviation_30d)
                print(f"30日累计偏离值: {cumulative_30d:.2f}%")
            
            # 2. 检查异动状态
            is_abnormal, abnormal_type, abnormal_detail = detector.check_abnormal_movement(stock_code, test_date)
            is_severe, severe_type, severe_detail = detector.check_severe_abnormal_movement(stock_code, test_date)
            
            print(f"\n异动检测结果:")
            print(f"  普通异动: {is_abnormal} - {abnormal_type} - {abnormal_detail}")
            print(f"  严重异动: {is_severe} - {severe_type} - {severe_detail}")
            
            # 3. 获取预警信息
            warning_message = detector.get_warning_message(stock_code, test_date)
            print(f"\n预警信息: {warning_message}")
            
            # 4. 详细分析30日偏离值情况
            if deviation_30d and len(deviation_30d) >= 15:
                cumulative_30d = sum(deviation_30d)
                if cumulative_30d >= 0:
                    remaining_for_severe = 200 - cumulative_30d
                    print(f"\n30日严重异动分析:")
                    print(f"  当前30日累计偏离值: {cumulative_30d:.2f}%")
                    print(f"  距离严重异动阈值(200%): {remaining_for_severe:.2f}%")
                    print(f"  是否应该预警即将严重异动: {remaining_for_severe > 0 and remaining_for_severe <= 50}")
            
        except Exception as e:
            print(f"检测出错: {e}")
        
        print("\n" + "="*80 + "\n")

def test_specific_date_calculation():
    """测试特定日期的偏离值计算"""
    detector = AbnormalMovementDetector()
    stock_code = "600929"
    test_date = "20250905"
    
    print(f"=== 详细分析 {stock_code} 在 {test_date} 的偏离值计算 ===\n")
    
    # 获取股票数据
    stock_df = detector.get_stock_data_cached(stock_code)
    if stock_df is not None:
        print(f"股票数据加载成功，共{len(stock_df)}条记录")
        print(f"数据日期范围: {stock_df['日期'].min()} 到 {stock_df['日期'].max()}")
        
        # 显示最近几天的数据
        print("\n最近10天的股票数据:")
        recent_data = stock_df.tail(10)[['日期', '开盘', '收盘', '涨跌幅']]
        print(recent_data.to_string(index=False))
    else:
        print("无法加载股票数据")
        return
    
    # 获取指数数据
    index_df = detector.get_market_index_data(stock_code)
    if not index_df.empty:
        print(f"\n指数数据加载成功，共{len(index_df)}条记录")
        print(f"指数数据日期范围: {index_df['日期'].min()} 到 {index_df['日期'].max()}")
        
        # 显示最近几天的指数数据
        print("\n最近10天的指数数据:")
        recent_index = index_df.tail(10)[['日期', '开盘', '收盘', '涨跌幅']]
        print(recent_index.to_string(index=False))
    else:
        print("无法加载指数数据")

if __name__ == "__main__":
    print("开始调试异动检测...")
    
    # 测试吉视传媒的异动检测
    test_jishi_chuanmei()
    
    # 测试具体的计算过程
    test_specific_date_calculation()
    
    print("调试完成")
