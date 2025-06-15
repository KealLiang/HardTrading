import numpy as np
import talib
import pandas as pd

# 创建测试数据 - 每个K线形态都有专门的样本数据
def test_pattern(pattern_name, open_data, high_data, low_data, close_data):
    """测试指定的K线形态识别函数"""
    # 确保数据是float类型
    open_arr = np.array(open_data, dtype=np.float64)
    high_arr = np.array(high_data, dtype=np.float64)
    low_arr = np.array(low_data, dtype=np.float64)
    close_arr = np.array(close_data, dtype=np.float64)
    
    # 获取函数对象
    pattern_func = getattr(talib, pattern_name)
    # 调用函数
    result = pattern_func(open_arr, high_arr, low_arr, close_arr)
    # 打印结果
    print(f"{pattern_name}结果: {result}")
    # 检查是否有非零值
    has_signal = np.any(result != 0)
    print(f"{pattern_name}是否有信号: {has_signal}\n")
    return has_signal

print(f"TA-Lib版本: {talib.__version__}")
print("=" * 50)

# 测试吞没形态 (CDLENGULFING)
# 典型的吞没形态数据
print("测试吞没形态 (CDLENGULFING)")
engulfing_open = [100.0, 90.0]
engulfing_high = [105.0, 100.0]
engulfing_low = [95.0, 85.0]
engulfing_close = [90.0, 100.0]  # 第一天阴线，第二天阳线且完全吞没前一天
test_pattern("CDLENGULFING", engulfing_open, engulfing_high, engulfing_low, engulfing_close)

# 测试锤子线 (CDLHAMMER)
print("测试锤子线 (CDLHAMMER)")
hammer_open = [100.0, 100.0]
hammer_high = [105.0, 100.0]
hammer_low = [85.0, 90.0]
hammer_close = [95.0, 98.0]  # 第二天是锤子线形态
test_pattern("CDLHAMMER", hammer_open, hammer_high, hammer_low, hammer_close)

# 测试启明星 (CDLMORNINGSTAR)
print("测试启明星 (CDLMORNINGSTAR)")
morning_star_open = [100.0, 90.0, 85.0]
morning_star_high = [105.0, 90.0, 95.0]
morning_star_low = [95.0, 80.0, 85.0]
morning_star_close = [90.0, 85.0, 95.0]  # 三天形成启明星
test_pattern("CDLMORNINGSTAR", morning_star_open, morning_star_high, morning_star_low, morning_star_close)

# 测试三白兵 (CDL3WHITESOLDIERS)
print("测试三白兵 (CDL3WHITESOLDIERS)")
soldiers_open = [100.0, 110.0, 120.0]
soldiers_high = [115.0, 125.0, 135.0]
soldiers_low = [95.0, 105.0, 115.0]
soldiers_close = [110.0, 120.0, 130.0]  # 连续三天阳线上涨
test_pattern("CDL3WHITESOLDIERS", soldiers_open, soldiers_high, soldiers_low, soldiers_close)

# 测试上吊线 (CDLHANGINGMAN)
print("测试上吊线 (CDLHANGINGMAN)")
hanging_man_open = [100.0, 110.0]
hanging_man_high = [115.0, 110.0]
hanging_man_low = [95.0, 90.0]
hanging_man_close = [110.0, 105.0]  # 第二天是上吊线
test_pattern("CDLHANGINGMAN", hanging_man_open, hanging_man_high, hanging_man_low, hanging_man_close)

# 测试黄昏星 (CDLEVENINGSTAR)
print("测试黄昏星 (CDLEVENINGSTAR)")
evening_star_open = [100.0, 115.0, 110.0]
evening_star_high = [115.0, 120.0, 110.0]
evening_star_low = [95.0, 110.0, 95.0]
evening_star_close = [110.0, 115.0, 100.0]  # 三天形成黄昏星
test_pattern("CDLEVENINGSTAR", evening_star_open, evening_star_high, evening_star_low, evening_star_close)

# 测试三黑鸦 (CDL3BLACKCROWS)
print("测试三黑鸦 (CDL3BLACKCROWS)")
crows_open = [100.0, 90.0, 80.0]
crows_high = [110.0, 95.0, 85.0]
crows_low = [90.0, 80.0, 70.0]
crows_close = [90.0, 80.0, 70.0]  # 连续三天阴线下跌
test_pattern("CDL3BLACKCROWS", crows_open, crows_high, crows_low, crows_close) 