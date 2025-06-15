import pandas as pd
import numpy as np
import talib
import matplotlib.pyplot as plt
import os
import sys

def load_and_prepare_data(file_path):
    """加载并准备数据"""
    df = pd.read_csv(file_path)
    print(f"成功加载数据: {file_path}")
    print(f"数据行数: {len(df)}")
    
    # 检查是否有时间列
    date_col = None
    for col in df.columns:
        if col.lower() in ['date', 'time', 'datetime', 'trade_date']:
            date_col = col
            break
    
    if date_col:
        # 确保日期格式正确
        try:
            if df[date_col].dtype == 'object':
                # 尝试转换为日期格式
                if len(str(df[date_col].iloc[0])) == 8 and str(df[date_col].iloc[0]).isdigit():
                    # 可能是YYYYMMDD格式
                    df['date'] = pd.to_datetime(df[date_col], format='%Y%m%d')
                else:
                    # 尝试通用日期格式解析
                    df['date'] = pd.to_datetime(df[date_col])
            else:
                df['date'] = pd.to_datetime(df[date_col])
                
            print(f"使用 {date_col} 列作为日期")
        except Exception as e:
            print(f"将 {date_col} 转换为日期时出错: {str(e)}")
            date_col = None
    
    # 标准化列名
    columns_map = {}
    for col in df.columns:
        lower_col = col.lower()
        if lower_col in ['open', 'high', 'low', 'close', 'volume']:
            columns_map[col] = lower_col
    
    if columns_map:
        df = df.rename(columns=columns_map)
        print(f"标准化列名: {list(columns_map.keys())} -> {list(columns_map.values())}")
    
    # 确保数据按时间排序
    if date_col:
        df = df.sort_values('date')
        print("数据已按日期排序")
    
    # 将OHLC数据转换为float64
    for col in ['open', 'high', 'low', 'close']:
        if col in df.columns:
            df[col] = df[col].astype(np.float64)
    
    return df

def test_window_effect(df, pattern_name, func_name, window_sizes=[5, 10, 15, 20]):
    """测试不同窗口大小对形态识别的影响"""
    # 准备数据
    open_data = np.array(df['open'].values, dtype=np.float64)
    high_data = np.array(df['high'].values, dtype=np.float64)
    low_data = np.array(df['low'].values, dtype=np.float64)
    close_data = np.array(df['close'].values, dtype=np.float64)
    
    # 获取形态识别函数
    pattern_func = getattr(talib, func_name)
    
    # 对整个序列进行形态识别
    full_result = pattern_func(open_data, high_data, low_data, close_data)
    full_detected = np.sum(full_result != 0)
    
    print(f"\n测试窗口大小对 {pattern_name} ({func_name}) 识别的影响:")
    print(f"全序列识别: 检测到 {full_detected} 个形态信号")
    
    # 测试不同窗口大小
    for window_size in window_sizes:
        detection_count = 0
        signals_lost = 0
        signals_new = 0
        
        for i in range(window_size, len(df)):
            # 获取窗口内的数据
            window_open = np.array(open_data[i-window_size:i], dtype=np.float64)
            window_high = np.array(high_data[i-window_size:i], dtype=np.float64)
            window_low = np.array(low_data[i-window_size:i], dtype=np.float64)
            window_close = np.array(close_data[i-window_size:i], dtype=np.float64)
            
            # 对窗口进行形态识别
            window_result = pattern_func(window_open, window_high, window_low, window_close)
            
            # 检查窗口末尾的信号 (最后一个元素)
            window_signal = window_result[-1]
            full_signal = full_result[i-1]  # 对应于全序列中的同一位置
            
            if window_signal != 0:
                detection_count += 1
            
            # 比较窗口识别结果与全序列识别结果
            if window_signal == 0 and full_signal != 0:
                signals_lost += 1
            elif window_signal != 0 and full_signal == 0:
                signals_new += 1
        
        print(f"窗口大小 {window_size}: 检测到 {detection_count} 个形态信号")
        print(f"  相比全序列: 丢失 {signals_lost} 个信号，新增 {signals_new} 个信号")
        
        # 如果有明显差异，输出一些详细信息
        if signals_lost > 0 or signals_new > 0:
            print("  差异原因可能是窗口大小影响了形态识别的上下文信息")

def analyze_trade_dates(df):
    """分析交易日期的连续性"""
    if 'date' not in df.columns:
        print("\n无法分析交易日期连续性：缺少日期列")
        return
    
    # 确保日期已排序
    df = df.sort_values('date')
    
    # 计算日期间隔
    df['next_date'] = df['date'].shift(-1)
    df['date_diff'] = (df['next_date'] - df['date']).dt.days
    
    # 分析间隔
    gaps = df[df['date_diff'] > 1]
    
    print("\n交易日期分析:")
    print(f"总交易日数: {len(df)}")
    print(f"日期范围: {df['date'].min()} 到 {df['date'].max()}")
    
    if len(gaps) > 0:
        print(f"发现 {len(gaps)} 个非连续交易日间隔")
        print("前5个最大间隔:")
        for _, row in gaps.nlargest(5, 'date_diff').iterrows():
            print(f"  {row['date']} 到 {row['next_date']}: {row['date_diff']} 天")
    else:
        print("所有交易日都是连续的")

def test_specific_patterns(df):
    """测试特定K线形态的识别条件"""
    # 准备数据
    open_data = df['open'].values
    high_data = df['high'].values
    low_data = df['low'].values
    close_data = df['close'].values
    
    # 确保数据类型正确
    open_data = np.array(open_data, dtype=np.float64)
    high_data = np.array(high_data, dtype=np.float64)
    low_data = np.array(low_data, dtype=np.float64)
    close_data = np.array(close_data, dtype=np.float64)
    
    # 测试启明星和黄昏星形态
    print("\n测试启明星和黄昏星形态识别:")
    
    # 尝试不同的渗透率参数
    penetration_values = [0.3, 0.5, 0.7, 0]
    
    for penetration in penetration_values:
        # 启明星
        morning_star = talib.CDLMORNINGSTAR(open_data, high_data, low_data, close_data, penetration=penetration)
        morning_star_count = np.sum(morning_star != 0)
        
        # 黄昏星
        evening_star = talib.CDLEVENINGSTAR(open_data, high_data, low_data, close_data, penetration=penetration)
        evening_star_count = np.sum(evening_star != 0)
        
        print(f"渗透率 {penetration}:")
        print(f"  启明星: 检测到 {morning_star_count} 个形态信号")
        print(f"  黄昏星: 检测到 {evening_star_count} 个形态信号")
        
        if morning_star_count > 0:
            indices = np.where(morning_star != 0)[0]
            print(f"  启明星信号位置: {indices[:5]}")
            for idx in indices[:3]:  # 只显示前3个
                if idx > 1:
                    print(f"    位置 {idx}: O={open_data[idx]:.2f} H={high_data[idx]:.2f} L={low_data[idx]:.2f} C={close_data[idx]:.2f}")
                    print(f"    前一天: O={open_data[idx-1]:.2f} H={high_data[idx-1]:.2f} L={low_data[idx-1]:.2f} C={close_data[idx-1]:.2f}")
                    print(f"    前两天: O={open_data[idx-2]:.2f} H={high_data[idx-2]:.2f} L={low_data[idx-2]:.2f} C={close_data[idx-2]:.2f}")
        
        if evening_star_count > 0:
            indices = np.where(evening_star != 0)[0]
            print(f"  黄昏星信号位置: {indices[:5]}")
            for idx in indices[:3]:  # 只显示前3个
                if idx > 1:
                    print(f"    位置 {idx}: O={open_data[idx]:.2f} H={high_data[idx]:.2f} L={low_data[idx]:.2f} C={close_data[idx]:.2f}")
                    print(f"    前一天: O={open_data[idx-1]:.2f} H={high_data[idx-1]:.2f} L={low_data[idx-1]:.2f} C={close_data[idx-1]:.2f}")
                    print(f"    前两天: O={open_data[idx-2]:.2f} H={high_data[idx-2]:.2f} L={low_data[idx-2]:.2f} C={close_data[idx-2]:.2f}")
    
    # 测试三白兵和三黑鸦
    print("\n测试三白兵和三黑鸦形态识别:")
    three_white = talib.CDL3WHITESOLDIERS(open_data, high_data, low_data, close_data)
    three_black = talib.CDL3BLACKCROWS(open_data, high_data, low_data, close_data)
    
    white_count = np.sum(three_white != 0)
    black_count = np.sum(three_black != 0)
    
    print(f"三白兵: 检测到 {white_count} 个形态信号")
    print(f"三黑鸦: 检测到 {black_count} 个形态信号")
    
    # 如果没有检测到，手动检查是否有类似形态
    if white_count == 0:
        print("分析可能的三白兵形态:")
        for i in range(3, len(df)):
            # 检查是否有连续三个阳线
            bull1 = close_data[i-3] > open_data[i-3]
            bull2 = close_data[i-2] > open_data[i-2]
            bull3 = close_data[i-1] > open_data[i-1]
            
            # 检查收盘价是否逐日上涨
            rising = close_data[i-3] < close_data[i-2] < close_data[i-1]
            
            if bull1 and bull2 and bull3 and rising:
                print(f"位置 {i-1} 可能是三白兵形态，但未被识别:")
                print(f"  第一天: O={open_data[i-3]:.2f} C={close_data[i-3]:.2f} (差: {close_data[i-3]-open_data[i-3]:.2f})")
                print(f"  第二天: O={open_data[i-2]:.2f} C={close_data[i-2]:.2f} (差: {close_data[i-2]-open_data[i-2]:.2f})")
                print(f"  第三天: O={open_data[i-1]:.2f} C={close_data[i-1]:.2f} (差: {close_data[i-1]-open_data[i-1]:.2f})")
    
    if black_count == 0:
        print("分析可能的三黑鸦形态:")
        for i in range(3, len(df)):
            # 检查是否有连续三个阴线
            bear1 = close_data[i-3] < open_data[i-3]
            bear2 = close_data[i-2] < open_data[i-2]
            bear3 = close_data[i-1] < open_data[i-1]
            
            # 检查收盘价是否逐日下跌
            falling = close_data[i-3] > close_data[i-2] > close_data[i-1]
            
            if bear1 and bear2 and bear3 and falling:
                print(f"位置 {i-1} 可能是三黑鸦形态，但未被识别:")
                print(f"  第一天: O={open_data[i-3]:.2f} C={close_data[i-3]:.2f} (差: {open_data[i-3]-close_data[i-3]:.2f})")
                print(f"  第二天: O={open_data[i-2]:.2f} C={close_data[i-2]:.2f} (差: {open_data[i-2]-close_data[i-2]:.2f})")
                print(f"  第三天: O={open_data[i-1]:.2f} C={close_data[i-1]:.2f} (差: {open_data[i-1]-close_data[i-1]:.2f})")

def analyze_strategy_implementation():
    """分析策略实现中可能存在的问题"""
    print("\n策略实现问题分析:")
    print("1. 数据类型问题: 已修复 - 确保使用np.float64类型")
    print("2. 窗口大小问题: 当前窗口大小为10 - 不同的窗口大小可能导致不同的形态识别结果")
    print("3. 形态阈值问题: TA-Lib对K线形态有严格的定义条件，可能需要调整某些参数")
    print("4. 数据排序问题: 确保数据按时间正确排序，影响形态的识别")
    print("5. 数据质量问题: 检查数据是否符合价格关系的一致性")
    
    print("\n解决方案:")
    print("1. 尝试不同的窗口大小，找到最佳平衡")
    print("2. 考虑使用自定义形态识别函数，放宽形态识别条件")
    print("3. 对于复杂形态(如启明星、三白兵)，可以尝试不同的渗透率参数")
    print("4. 在策略实现中添加更多日志输出，跟踪形态识别过程")
    print("5. 使用图表可视化检测到的形态，以便更直观地理解")

if __name__ == "__main__":
    # 获取命令行参数
    if len(sys.argv) > 1:
        data_file = sys.argv[1]
    else:
        # 尝试查找可能的数据文件
        possible_dirs = ['data', '.', 'stock_data']
        data_file = None
        
        for dir_path in possible_dirs:
            if os.path.exists(dir_path):
                csv_files = [f for f in os.listdir(dir_path) if f.endswith('.csv')]
                if csv_files:
                    data_file = os.path.join(dir_path, csv_files[0])
                    break
        
        if not data_file:
            print("未找到数据文件，请指定数据文件路径")
            sys.exit(1)
    
    print(f"使用数据文件: {data_file}")
    
    # 加载并准备数据
    df = load_and_prepare_data(data_file)
    
    # 分析交易日期的连续性
    analyze_trade_dates(df)
    
    # 测试窗口大小对形态识别的影响
    test_window_effect(df, "吞没形态", "CDLENGULFING")
    test_window_effect(df, "锤子线", "CDLHAMMER")
    test_window_effect(df, "启明星", "CDLMORNINGSTAR")
    test_window_effect(df, "黄昏星", "CDLEVENINGSTAR")
    test_window_effect(df, "三白兵", "CDL3WHITESOLDIERS")
    test_window_effect(df, "三黑鸦", "CDL3BLACKCROWS")
    
    # 测试特定形态的识别条件
    test_specific_patterns(df)
    
    # 分析策略实现中可能存在的问题
    analyze_strategy_implementation() 