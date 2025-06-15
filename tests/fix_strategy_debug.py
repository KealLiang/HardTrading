import numpy as np
import talib
import backtrader as bt
import pandas as pd
import matplotlib.pyplot as plt

def debug_pattern_functions():
    """测试单独的形态函数"""
    # 创建测试数据
    size = 20  # 数据点数
    np.random.seed(42)
    
    # 基础价格数据
    open_data = np.random.uniform(90, 110, size=size)
    high_data = open_data + np.random.uniform(0, 5, size=size)
    low_data = open_data - np.random.uniform(0, 5, size=size)
    close_data = open_data + np.random.uniform(-3, 3, size=size)
    
    # 确保数据合理性
    for i in range(size):
        high_data[i] = max(high_data[i], open_data[i], close_data[i])
        low_data[i] = min(low_data[i], open_data[i], close_data[i])
    
    # 打印TA-Lib版本
    print(f"TA-Lib版本: {talib.__version__}")
    
    # 测试各种形态函数
    patterns = {
        'CDLHAMMER': '锤子线',
        'CDLENGULFING': '吞没形态',
        'CDLMORNINGSTAR': '启明星',
        'CDL3WHITESOLDIERS': '三白兵',
        'CDLHANGINGMAN': '上吊线',
        'CDLEVENINGSTAR': '黄昏星',
        'CDL3BLACKCROWS': '三黑鸦'
    }
    
    print("\n单独测试各形态函数:")
    for func_name, pattern_name in patterns.items():
        try:
            # 确保数据是float64类型
            o = np.array(open_data, dtype=np.float64)
            h = np.array(high_data, dtype=np.float64)
            l = np.array(low_data, dtype=np.float64)
            c = np.array(close_data, dtype=np.float64)
            
            # 调用函数
            pattern_func = getattr(talib, func_name)
            result = pattern_func(o, h, l, c)
            
            # 输出结果
            print(f"{pattern_name} ({func_name}): 函数调用成功")
            print(f"  结果: {result}")
            print(f"  是否检测到形态: {np.any(result != 0)}\n")
            
        except Exception as e:
            print(f"{pattern_name} ({func_name}): 函数调用失败")
            print(f"  错误: {str(e)}\n")

def test_strategy_code():
    """测试策略中使用的K线形态识别代码块"""
    # 创建测试数据
    size = 20  # 数据点数
    np.random.seed(42)
    
    # 基础价格数据
    open_data = np.array(np.random.uniform(90, 110, size=size), dtype=np.float64)
    high_data = np.array(open_data + np.random.uniform(0, 5, size=size), dtype=np.float64)
    low_data = np.array(open_data - np.random.uniform(0, 5, size=size), dtype=np.float64)
    close_data = np.array(open_data + np.random.uniform(-3, 3, size=size), dtype=np.float64)
    
    # 确保数据合理性
    for i in range(size):
        high_data[i] = max(high_data[i], open_data[i], close_data[i])
        low_data[i] = min(low_data[i], open_data[i], close_data[i])
    
    # 在第10天注入吞没形态
    open_data[9] = 105.0
    close_data[9] = 102.0  # 阴线
    open_data[10] = 101.0
    close_data[10] = 106.0  # 阳线，吞没前一天
    
    # 在第15天注入锤子线
    open_data[14] = 95.0
    close_data[14] = 95.2
    high_data[14] = 95.5
    low_data[14] = 91.0  # 长下影线
    
    print("\n测试策略中使用的K线形态识别代码块:")
    
    # 模拟策略中的代码
    min_history = 10
    
    # 1. 计算最近的10天数据，就像策略中一样
    test_idx = 15  # 选择一个有足够历史数据的点
    if test_idx >= min_history:
        try:
            # 获取最近的OHLC数据
            o_arr = np.array(open_data[test_idx-min_history+1:test_idx+1])
            h_arr = np.array(high_data[test_idx-min_history+1:test_idx+1])
            l_arr = np.array(low_data[test_idx-min_history+1:test_idx+1])
            c_arr = np.array(close_data[test_idx-min_history+1:test_idx+1])
            
            # 确保数据类型是float64
            o_arr = o_arr.astype(np.float64)
            h_arr = h_arr.astype(np.float64)
            l_arr = l_arr.astype(np.float64)
            c_arr = c_arr.astype(np.float64)
            
            print(f"数据点数: {len(o_arr)}")
            print(f"数据类型: {o_arr.dtype}")
            
            # 计算K线形态信号，就像策略中一样
            pattern_results = {
                '锤子线': talib.CDLHAMMER(o_arr, h_arr, l_arr, c_arr)[-1],
                '吞没形态': talib.CDLENGULFING(o_arr, h_arr, l_arr, c_arr)[-1],
                '启明星': talib.CDLMORNINGSTAR(o_arr, h_arr, l_arr, c_arr)[-1],
                '三白兵': talib.CDL3WHITESOLDIERS(o_arr, h_arr, l_arr, c_arr)[-1],
                '上吊线': talib.CDLHANGINGMAN(o_arr, h_arr, l_arr, c_arr)[-1],
                '黄昏星': talib.CDLEVENINGSTAR(o_arr, h_arr, l_arr, c_arr)[-1],
                '三黑鸦': talib.CDL3BLACKCROWS(o_arr, h_arr, l_arr, c_arr)[-1]
            }
            
            # 提取看涨和看跌信号
            bullish_patterns = {k: v for k, v in pattern_results.items() if v > 0}
            bearish_patterns = {k: v for k, v in pattern_results.items() if v < 0}
            
            print("\n检测到的形态:")
            for pattern, value in pattern_results.items():
                print(f"{pattern}: {value}")
            
            print("\n看涨形态:")
            for pattern, value in bullish_patterns.items():
                print(f"{pattern}: {value}")
            
            print("\n看跌形态:")
            for pattern, value in bearish_patterns.items():
                print(f"{pattern}: {value}")
            
        except Exception as e:
            print(f"形态识别错误: {str(e)}")

def propose_fix():
    """提出修复策略的方法"""
    print("\n问题分析与修复方案:")
    print("1. 数据类型问题: 确保所有输入数据都是float64类型")
    print("2. 数据点数问题: 确保有足够的历史数据点")
    print("3. 数据质量问题: 确保OHLC数据的合理性")
    print("4. 修复策略代码:\n")
    
    print("```python")
    print("def next(self):")
    print("    # 如果有未完成的订单，不操作")
    print("    if self.order:")
    print("        return")
    print("        ")
    print("    # 确保有足够的历史数据进行形态识别")
    print("    if len(self.data) < self.min_history:")
    print("        return")
    print("        ")
    print("    # 获取最近的OHLC数据并确保是float64类型")
    print("    open_arr = np.array(self.dataopen.get(size=self.min_history), dtype=np.float64)")
    print("    high_arr = np.array(self.datahigh.get(size=self.min_history), dtype=np.float64)")
    print("    low_arr = np.array(self.datalow.get(size=self.min_history), dtype=np.float64)")
    print("    close_arr = np.array(self.dataclose.get(size=self.min_history), dtype=np.float64)")
    print("        ")
    print("    # 计算K线形态信号")
    print("    try:")
    print("        # 存储形态及其信号值的字典")
    print("        pattern_results = {")
    print("            '锤子线': talib.CDLHAMMER(open_arr, high_arr, low_arr, close_arr)[-1],")
    print("            '吞没形态': talib.CDLENGULFING(open_arr, high_arr, low_arr, close_arr)[-1],")
    print("            '启明星': talib.CDLMORNINGSTAR(open_arr, high_arr, low_arr, close_arr)[-1],")
    print("            '三白兵': talib.CDL3WHITESOLDIERS(open_arr, high_arr, low_arr, close_arr)[-1],")
    print("            '上吊线': talib.CDLHANGINGMAN(open_arr, high_arr, low_arr, close_arr)[-1],")
    print("            '黄昏星': talib.CDLEVENINGSTAR(open_arr, high_arr, low_arr, close_arr)[-1],")
    print("            '三黑鸦': talib.CDL3BLACKCROWS(open_arr, high_arr, low_arr, close_arr)[-1]")
    print("        }")
    print("        ")
    print("        # 提取看涨和看跌信号")
    print("        bullish_patterns = {k: v for k, v in pattern_results.items() if v > 0}")
    print("        bearish_patterns = {k: v for k, v in pattern_results.items() if v < 0}")
    print("        ")
    print("        # 调试信息 (可在实际使用时删除)")
    print("        if bullish_patterns or bearish_patterns:")
    print("            self.log(f'检测到的看涨形态: {bullish_patterns}')")
    print("            self.log(f'检测到的看跌形态: {bearish_patterns}')")
    print("        ")
    print("        # 风险管理 - 止损")
    print("        if self.position and self.dataclose[0] < self.stop_loss:")
    print("            self.log(f'触发止损: 当前价格 {self.dataclose[0]:.2f}, 止损价 {self.stop_loss:.2f}')")
    print("            self.order = self.sell(size=self.position.size)")
    print("            return")
    print("```")

if __name__ == "__main__":
    debug_pattern_functions()
    test_strategy_code()
    propose_fix() 