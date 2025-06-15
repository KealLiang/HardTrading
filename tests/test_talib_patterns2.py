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
    indices = np.where(result != 0)[0]
    if len(indices) > 0:
        print(f"{pattern_name}在索引 {indices} 处有信号: {result[indices]}")
    has_signal = np.any(result != 0)
    print(f"{pattern_name}是否有信号: {has_signal}\n")
    return has_signal

print(f"TA-Lib版本: {talib.__version__}")
print("=" * 50)

# 测试吞没形态 (CDLENGULFING) - 改进版
# 吞没形态需要前一天的交易与当天交易形成强烈对比
print("测试吞没形态 (CDLENGULFING)")
# 前一个蜡烛是明显的下跌趋势中的小阴线，当天是大阳线完全包围前一个阴线
engulfing_open = [110.0, 105.0, 90.0]  # 前段下跌趋势，前一天开盘价高于收盘价，当天开盘低
engulfing_high = [115.0, 105.0, 105.0]  # 当天最高价高于前一天
engulfing_low = [100.0, 90.0, 85.0]    # 当天最低价低于前一天
engulfing_close = [105.0, 95.0, 103.0]  # 前一天收盘价低于开盘价(阴线)，当天收盘价大幅高于开盘价(阳线)
test_pattern("CDLENGULFING", engulfing_open, engulfing_high, engulfing_low, engulfing_close)

# 测试锤子线 (CDLHAMMER) - 改进版
print("测试锤子线 (CDLHAMMER)")
# 锤子线通常出现在下跌趋势底部，有很长的下影线，几乎没有上影线，小实体
hammer_open = [100.0, 90.0, 80.0, 70.0]  # 下跌趋势
hammer_high = [105.0, 95.0, 85.0, 72.0]  # 最高点接近开盘价或收盘价
hammer_low = [90.0, 80.0, 70.0, 60.0]    # 最低点远低于开盘价和收盘价（长下影线）
hammer_close = [95.0, 85.0, 75.0, 71.0]  # 收盘价接近最高价
test_pattern("CDLHAMMER", hammer_open, hammer_high, hammer_low, hammer_close)

# 测试启明星 (CDLMORNINGSTAR) - 改进版
print("测试启明星 (CDLMORNINGSTAR)")
# 三天形态：第一天大阴线，第二天小实体（星），第三天大阳线
morning_star_open = [100.0, 90.0, 80.0, 82.0, 83.0]  # 前一段下跌趋势，然后第一天开盘高
morning_star_high = [105.0, 95.0, 90.0, 84.0, 95.0]  # 第三天有较高的最高价
morning_star_low = [95.0, 85.0, 75.0, 80.0, 82.0]    # 最低价逐渐降低后回升
morning_star_close = [95.0, 85.0, 75.0, 82.0, 93.0]  # 第一天阴线，第二天十字星，第三天阳线
test_pattern("CDLMORNINGSTAR", morning_star_open, morning_star_high, morning_star_low, morning_star_close)

# 测试三白兵 (CDL3WHITESOLDIERS) - 改进版
print("测试三白兵 (CDL3WHITESOLDIERS)")
# 连续三根上升的阳线，每天的开盘价在前一天实体范围内，收盘价创新高
soldiers_open = [90.0, 95.0, 100.0, 105.0, 110.0]  # 每天开盘价逐渐升高
soldiers_high = [100.0, 105.0, 110.0, 115.0, 125.0]  # 每天最高价逐渐升高
soldiers_low = [85.0, 90.0, 95.0, 100.0, 105.0]      # 每天最低价逐渐升高
soldiers_close = [95.0, 100.0, 105.0, 110.0, 120.0]  # 连续阳线，且收盘价逐渐升高
test_pattern("CDL3WHITESOLDIERS", soldiers_open, soldiers_high, soldiers_low, soldiers_close)

# 测试上吊线 (CDLHANGINGMAN) - 改进版
print("测试上吊线 (CDLHANGINGMAN)")
# 上吊线出现在上升趋势顶部，有长下影线，几乎没有上影线，小实体
hanging_man_open = [80.0, 85.0, 90.0, 100.0, 105.0]  # 上升趋势后形成上吊线
hanging_man_high = [85.0, 90.0, 95.0, 105.0, 106.0]  # 当天最高价接近开盘价
hanging_man_low = [75.0, 80.0, 85.0, 95.0, 95.0]     # 最后一天有长下影线
hanging_man_close = [80.0, 85.0, 90.0, 100.0, 105.0] # 当天收盘价接近开盘价，形成小实体
test_pattern("CDLHANGINGMAN", hanging_man_open, hanging_man_high, hanging_man_low, hanging_man_close)

# 测试黄昏星 (CDLEVENINGSTAR) - 改进版
print("测试黄昏星 (CDLEVENINGSTAR)")
# 三天形态：第一天大阳线，第二天小实体（星），第三天大阴线
evening_star_open = [90.0, 95.0, 100.0, 110.0, 115.0]  # 上升趋势中
evening_star_high = [95.0, 100.0, 110.0, 116.0, 115.0]  # 第二天形成星星形态
evening_star_low = [85.0, 90.0, 95.0, 109.0, 100.0]     # 第三天低点明显下降
evening_star_close = [90.0, 95.0, 105.0, 110.0, 102.0]  # 第一天阳线，第二天小阳线，第三天阴线
test_pattern("CDLEVENINGSTAR", evening_star_open, evening_star_high, evening_star_low, evening_star_close)

# 测试三黑鸦 (CDL3BLACKCROWS) - 改进版
print("测试三黑鸦 (CDL3BLACKCROWS)")
# 连续三根下降的阴线，每天的开盘价在前一天实体范围内，收盘价创新低
crows_open = [90.0, 100.0, 95.0, 90.0, 85.0]    # 开盘价逐日递减
crows_high = [95.0, 105.0, 100.0, 95.0, 90.0]   # 最高价逐日递减
crows_low = [85.0, 90.0, 85.0, 80.0, 75.0]      # 最低价逐日递减
crows_close = [90.0, 95.0, 90.0, 85.0, 80.0]    # 连续三天阴线，收盘价逐日递减
test_pattern("CDL3BLACKCROWS", crows_open, crows_high, crows_low, crows_close) 