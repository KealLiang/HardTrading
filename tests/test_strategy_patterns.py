import numpy as np
import talib
import pandas as pd
import random
import sys

def create_realistic_data(num_days=100, seed=42):
    """创建一个更加真实的价格数据集"""
    random.seed(seed)
    np.random.seed(seed)
    
    # 基准价格和波动性
    price = 100.0
    daily_volatility = 2.0
    
    # 创建价格数据
    open_prices = []
    high_prices = []
    low_prices = []
    close_prices = []
    
    for i in range(num_days):
        # 添加一些趋势和随机噪声
        if i > 0:
            # 40% 概率继续前一天的趋势，60% 概率反转
            if random.random() < 0.4:
                trend = close_prices[-1] - open_prices[-1]
            else:
                trend = -(close_prices[-1] - open_prices[-1])
        else:
            trend = 0
            
        # 每日开盘价，基于前一天收盘价加一点随机变化
        if i > 0:
            open_price = close_prices[-1] + np.random.normal(0, daily_volatility * 0.5)
        else:
            open_price = price
        
        # 基于开盘价和趋势设置收盘价
        close_price = open_price + trend + np.random.normal(0, daily_volatility)
        
        # 高低价
        price_range = abs(daily_volatility * (1 + np.random.random()))
        high_price = max(open_price, close_price) + price_range * random.random()
        low_price = min(open_price, close_price) - price_range * random.random()
        
        # 保存数据
        open_prices.append(open_price)
        high_prices.append(high_price)
        low_prices.append(low_price)
        close_prices.append(close_price)
        
    return np.array(open_prices), np.array(high_prices), np.array(low_prices), np.array(close_prices)

def inject_patterns(open_data, high_data, low_data, close_data):
    """注入几个典型的K线形态"""
    # 随机选择一些位置注入形态
    positions = [20, 40, 60, 80]
    
    # 1. 注入吞没形态(看涨) - 位置20
    if len(open_data) > positions[0] + 1:
        i = positions[0]
        # 前一根是阴线
        open_data[i-1] = 100.0
        close_data[i-1] = 98.0
        high_data[i-1] = 100.5
        low_data[i-1] = 97.5
        # 当前根是吞没的阳线
        open_data[i] = 97.5  # 低开
        close_data[i] = 101.0  # 高收
        high_data[i] = 101.5
        low_data[i] = 97.0
    
    # 2. 注入锤子线形态 - 位置40
    if len(open_data) > positions[1]:
        i = positions[1]
        # 下跌趋势
        for j in range(i-3, i):
            if j >= 0:
                open_data[j] = 100.0 - (i-j)*1.5
                close_data[j] = open_data[j] - 1.0
                high_data[j] = open_data[j] + 0.5
                low_data[j] = close_data[j] - 0.5
                
        # 锤子线
        open_data[i] = 93.0
        close_data[i] = 93.5
        high_data[i] = 94.0
        low_data[i] = 90.0  # 长下影线
    
    # 3. 注入启明星形态 - 位置60
    if len(open_data) > positions[2] + 2:
        i = positions[2]
        # 第一天 - 大阴线
        open_data[i] = 95.0
        close_data[i] = 92.0
        high_data[i] = 95.5
        low_data[i] = 91.5
        
        # 第二天 - 星(小实体，跳空低开)
        open_data[i+1] = 91.0
        close_data[i+1] = 91.5
        high_data[i+1] = 91.8
        low_data[i+1] = 90.5
        
        # 第三天 - 大阳线
        open_data[i+2] = 92.0
        close_data[i+2] = 94.5
        high_data[i+2] = 95.0
        low_data[i+2] = 91.8
    
    # 4. 注入黄昏星形态 - 位置80
    if len(open_data) > positions[3] + 2:
        i = positions[3]
        # 第一天 - 大阳线
        open_data[i] = 103.0
        close_data[i] = 106.0
        high_data[i] = 106.5
        low_data[i] = 102.5
        
        # 第二天 - 星(小实体，跳空高开)
        open_data[i+1] = 107.0
        close_data[i+1] = 106.5
        high_data[i+1] = 107.5
        low_data[i+1] = 106.0
        
        # 第三天 - 大阴线
        open_data[i+2] = 106.0
        close_data[i+2] = 103.5
        high_data[i+2] = 106.5
        low_data[i+2] = 103.0
    
    return open_data, high_data, low_data, close_data

def test_patterns_with_data():
    """创建数据并测试各种K线形态"""
    # 将输出重定向到文件
    with open('../pattern_test_results.txt', 'w') as f:
        # 将输出同时显示在控制台和写入文件
        def write_output(text):
            print(text)
            f.write(text + '\n')
        
        write_output(f"TA-Lib版本: {talib.__version__}")
        
        # 创建基础数据
        open_data, high_data, low_data, close_data = create_realistic_data(100)
        
        # 注入特定形态
        open_data, high_data, low_data, close_data = inject_patterns(open_data, high_data, low_data, close_data)
        
        # 要测试的形态列表
        patterns = {
            'CDLHAMMER': '锤子线',
            'CDLENGULFING': '吞没形态',
            'CDLMORNINGSTAR': '启明星',
            'CDL3WHITESOLDIERS': '三白兵',
            'CDLHANGINGMAN': '上吊线',
            'CDLEVENINGSTAR': '黄昏星',
            'CDL3BLACKCROWS': '三黑鸦'
        }
        
        # 测试每种形态
        write_output("\n=== 形态检测结果 ===")
        for func_name, pattern_name in patterns.items():
            pattern_func = getattr(talib, func_name)
            result = pattern_func(open_data, high_data, low_data, close_data)
            
            # 找出非零值（识别出的形态）的位置
            indices = np.where(result != 0)[0]
            
            if len(indices) > 0:
                write_output(f"\n{pattern_name} ({func_name}) 识别结果:")
                for i in indices:
                    write_output(f"  在第 {i+1} 天检测到，信号值: {result[i]}")
                    
                    # 打印该位置的OHLC数据
                    write_output(f"  该位置的价格数据:")
                    start_idx = max(0, i-2)
                    end_idx = min(len(open_data), i+3)
                    write_output("    日期   开盘    最高    最低    收盘")
                    for j in range(start_idx, end_idx):
                        marker = "==>" if j == i else "   "
                        write_output(f"    {marker} {j+1:2d}: {open_data[j]:.2f}  {high_data[j]:.2f}  {low_data[j]:.2f}  {close_data[j]:.2f}")
                    write_output("")
            else:
                write_output(f"\n{pattern_name} ({func_name}): 未检测到")

if __name__ == "__main__":
    test_patterns_with_data()
    print("\n结果已写入 pattern_test_results.txt 文件") 