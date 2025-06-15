import numpy as np
import talib
from talib import abstract
import pandas as pd

def print_pattern_functions():
    """打印所有可用的K线形态识别函数"""
    pattern_functions = [func for func in dir(talib) if func.startswith('CDL')]
    print(f"TA-Lib版本: {talib.__version__}")
    print(f"可用的K线形态识别函数数量: {len(pattern_functions)}")
    print("=" * 50)
    for func in sorted(pattern_functions):
        print(func)

def test_engulfing_pattern():
    """测试吞没形态"""
    print("\n测试吞没形态 (CDLENGULFING)")
    open_data = np.array([43.10, 42.40, 41.55], dtype=np.float64)
    high_data = np.array([43.15, 42.82, 42.72], dtype=np.float64)
    low_data = np.array([42.38, 41.87, 41.31], dtype=np.float64)
    close_data = np.array([42.65, 42.10, 42.22], dtype=np.float64)
    
    # 直接调用函数
    result = talib.CDLENGULFING(open_data, high_data, low_data, close_data)
    print(f"结果: {result}")
    print(f"是否检测到吞没形态: {np.any(result != 0)}")

def test_all_patterns():
    """使用单一数据集测试所有K线形态"""
    # 创建一个更长的数据集，增加识别几率
    num_days = 20
    np.random.seed(42)  # 设置随机种子以便结果可重现
    
    # 使用更真实的价格数据
    base_price = 100.0
    volatility = 2.0
    trend = np.linspace(-3, 3, num_days)  # 创建一个从下跌到上涨的趋势
    
    # 生成开盘价
    open_data = np.random.normal(base_price + trend, volatility, num_days)
    
    # 生成最高价和最低价
    daily_volatility = np.random.uniform(0.5, 1.5, num_days) * volatility
    high_data = open_data + np.abs(np.random.normal(0, daily_volatility, num_days))
    low_data = open_data - np.abs(np.random.normal(0, daily_volatility, num_days))
    
    # 生成收盘价 - 50%的概率上涨，50%的概率下跌
    close_direction = np.random.choice([-1, 1], size=num_days)
    close_movement = np.abs(np.random.normal(0, daily_volatility, num_days)) * close_direction
    close_data = open_data + close_movement
    
    # 确保最高价大于开盘价和收盘价，最低价低于开盘价和收盘价
    for i in range(num_days):
        high_data[i] = max(high_data[i], open_data[i], close_data[i])
        low_data[i] = min(low_data[i], open_data[i], close_data[i])
    
    # 创建一些特定形态
    # 在索引10处创建吞没形态
    if num_days > 11:
        open_data[10] = close_data[9] + 1.0  # 当天开盘高于前一天收盘
        close_data[10] = open_data[9] - 1.0  # 当天收盘低于前一天开盘
    
    print(f"\n测试所有K线形态")
    print(f"数据集大小: {num_days}天")
    
    # 获取所有K线形态函数
    pattern_functions = [func for func in dir(talib) if func.startswith('CDL')]
    
    # 测试每个形态
    detected_patterns = []
    
    print("\n识别到的K线形态:")
    print("-" * 30)
    for pattern_name in pattern_functions:
        pattern_func = getattr(talib, pattern_name)
        result = pattern_func(open_data, high_data, low_data, close_data)
        
        # 找出非零结果的索引
        nonzero_indices = np.nonzero(result)[0]
        
        if len(nonzero_indices) > 0:
            detected_patterns.append(pattern_name)
            print(f"{pattern_name}:")
            for idx in nonzero_indices:
                print(f"  在第{idx+1}天检测到，信号值: {result[idx]}")
    
    # 输出总结
    print("\n总结:")
    print(f"总共测试了 {len(pattern_functions)} 种K线形态")
    print(f"检测到 {len(detected_patterns)} 种形态：{', '.join(detected_patterns)}")

if __name__ == "__main__":
    print_pattern_functions()
    test_engulfing_pattern()
    test_all_patterns() 