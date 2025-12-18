"""
测试成交量趋势分析功能
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.helper.volume_ladder_chart import (
    calculate_volume_ma, 
    get_volume_trend_indicator,
    VOLUME_MA_DAYS,
    VOLUME_TREND_DAYS,
    VOLUME_RATIO_HIGH_THRESHOLD,
    VOLUME_RATIO_LOW_THRESHOLD,
    VOLUME_MA_SLOPE_THRESHOLD
)

def test_volume_ma_calculation():
    """测试成交量均线计算"""
    print("=== 测试成交量均线计算 ===")
    
    # 测试一些常见股票
    test_stocks = ['000001', '000002', '300001']
    test_date = '20250915'  # 使用最近的交易日
    
    for stock_code in test_stocks:
        try:
            volume_ma = calculate_volume_ma(stock_code, test_date)
            if volume_ma is not None:
                print(f"股票 {stock_code} 在 {test_date} 的{VOLUME_MA_DAYS}日成交量均线: {volume_ma:,.0f}")
            else:
                print(f"股票 {stock_code} 在 {test_date} 无法计算成交量均线")
        except Exception as e:
            print(f"股票 {stock_code} 计算成交量均线时出错: {e}")
    
    print()

def test_volume_trend_indicator():
    """测试成交量趋势指标"""
    print("=== 测试成交量趋势指标 ===")
    
    # 模拟交易日列表和日期映射
    formatted_trading_days = [
        '2025年09月09日', '2025年09月10日', '2025年09月11日', 
        '2025年09月12日', '2025年09月13日', '2025年09月14日', '2025年09月15日'
    ]
    
    date_mapping = {
        '2025年09月09日': '20250909',
        '2025年09月10日': '20250910', 
        '2025年09月11日': '20250911',
        '2025年09月12日': '20250912',
        '2025年09月13日': '20250913',
        '2025年09月14日': '20250914',
        '2025年09月15日': '20250915'
    }
    
    test_stocks = ['000001', '000002', '300001']
    test_date = '20250915'
    
    for stock_code in test_stocks:
        try:
            trend_indicator = get_volume_trend_indicator(
                stock_code, test_date, formatted_trading_days, date_mapping
            )
            if trend_indicator:
                print(f"股票 {stock_code} 在 {test_date} 的成交量趋势: {trend_indicator}")
            else:
                print(f"股票 {stock_code} 在 {test_date} 无明显成交量趋势")
        except Exception as e:
            print(f"股票 {stock_code} 计算成交量趋势时出错: {e}")
    
    print()

def test_parameters():
    """测试参数配置"""
    print("=== 当前参数配置 ===")
    print(f"成交量均线天数: {VOLUME_MA_DAYS}")
    print(f"趋势判断天数: {VOLUME_TREND_DAYS}")
    print(f"高活跃阈值: {VOLUME_RATIO_HIGH_THRESHOLD}")
    print(f"低活跃阈值: {VOLUME_RATIO_LOW_THRESHOLD}")
    print(f"均线斜率阈值: {VOLUME_MA_SLOPE_THRESHOLD}")
    print()

def main():
    """主测试函数"""
    print("开始测试成交量趋势分析功能...\n")
    
    test_parameters()
    test_volume_ma_calculation()
    test_volume_trend_indicator()
    
    print("测试完成！")

if __name__ == "__main__":
    main()
