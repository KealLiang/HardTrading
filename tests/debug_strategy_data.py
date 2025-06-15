import pandas as pd
import numpy as np
import talib
import os
import matplotlib.pyplot as plt
from datetime import datetime
import sys

def load_stock_data(file_path):
    """加载股票数据"""
    if os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path)
            print(f"成功加载数据文件: {file_path}")
            return df
        except Exception as e:
            print(f"加载数据文件出错: {str(e)}")
            return None
    else:
        print(f"文件不存在: {file_path}")
        return None

def analyze_data(df):
    """分析数据特征"""
    print("\n数据基本信息:")
    print(f"数据行数: {len(df)}")
    print(f"数据列: {df.columns.tolist()}")
    
    # 检查是否有必要的OHLC列
    required_cols = ['open', 'high', 'low', 'close']
    missing_cols = [col for col in required_cols if col.lower() not in [c.lower() for c in df.columns]]
    if missing_cols:
        print(f"缺少必要的列: {missing_cols}")
        return
    
    # 标准化列名
    col_map = {}
    for col in df.columns:
        lower_col = col.lower()
        if lower_col in ['open', 'high', 'low', 'close', 'volume', 'date']:
            col_map[col] = lower_col
    
    # 重命名列
    if col_map:
        df = df.rename(columns=col_map)
    
    # 分析数据特征
    print("\n数据统计信息:")
    print(df[['open', 'high', 'low', 'close']].describe())
    
    # 检查是否有缺失值
    missing_values = df[['open', 'high', 'low', 'close']].isnull().sum()
    if missing_values.sum() > 0:
        print("\n存在缺失值:")
        print(missing_values)
    
    # 检查价格一致性 (high >= open, close and low <= open, close)
    inconsistent_high = ((df['high'] < df['open']) | (df['high'] < df['close'])).sum()
    inconsistent_low = ((df['low'] > df['open']) | (df['low'] > df['close'])).sum()
    if inconsistent_high > 0 or inconsistent_low > 0:
        print("\n存在价格不一致:")
        print(f"high < max(open, close) 的行数: {inconsistent_high}")
        print(f"low > min(open, close) 的行数: {inconsistent_low}")
    
    return df

def test_pattern_detection(df, window_size=10):
    """测试K线形态识别"""
    # 确保数据类型正确
    open_data = np.array(df['open'].values, dtype=np.float64)
    high_data = np.array(df['high'].values, dtype=np.float64)
    low_data = np.array(df['low'].values, dtype=np.float64)
    close_data = np.array(df['close'].values, dtype=np.float64)
    
    # 特定关注的K线形态
    patterns = {
        'CDLHAMMER': '锤子线',
        'CDLENGULFING': '吞没形态',
        'CDLMORNINGSTAR': '启明星',
        'CDL3WHITESOLDIERS': '三白兵',
        'CDLHANGINGMAN': '上吊线',
        'CDLEVENINGSTAR': '黄昏星',
        'CDL3BLACKCROWS': '三黑鸦'
    }
    
    # 创建结果DataFrame
    result_df = pd.DataFrame(index=df.index)
    result_df['date'] = df['date'] if 'date' in df.columns else df.index
    
    # 对每个形态进行检测
    detection_counts = {}
    
    print("\n测试K线形态识别:")
    for func_name, pattern_name in patterns.items():
        try:
            # 获取函数对象
            pattern_func = getattr(talib, func_name)
            
            # 执行形态识别
            result = pattern_func(open_data, high_data, low_data, close_data)
            
            # 添加到结果DataFrame
            result_df[pattern_name] = result
            
            # 统计检测到的形态数量
            detected = np.sum(result != 0)
            detection_counts[pattern_name] = detected
            
            print(f"{pattern_name} ({func_name}): 检测到 {detected} 个形态信号")
            
            # 如果检测到信号，显示一些详细信息
            if detected > 0:
                nonzero_indices = np.where(result != 0)[0]
                print(f"  检测到的信号位置: {nonzero_indices[:5]} ...")
                print(f"  信号值: {result[nonzero_indices][:5]} ...")
            
        except Exception as e:
            print(f"{pattern_name} ({func_name}): 执行出错 - {str(e)}")
    
    # 输出汇总结果
    print("\n形态检测汇总:")
    for pattern_name, count in detection_counts.items():
        print(f"{pattern_name}: {count} 个信号")
    
    # 使用模拟策略算法:
    print("\n模拟策略中的形态检测:")
    window_size = 10
    for i in range(window_size, len(df)):
        try:
            # 获取窗口内的数据
            window_open = np.array(open_data[i-window_size:i], dtype=np.float64)
            window_high = np.array(high_data[i-window_size:i], dtype=np.float64)
            window_low = np.array(low_data[i-window_size:i], dtype=np.float64)
            window_close = np.array(close_data[i-window_size:i], dtype=np.float64)
            
            # 检测当前窗口中的形态 - 模拟策略中的操作，只获取最后一个值
            pattern_results = {
                '锤子线': talib.CDLHAMMER(window_open, window_high, window_low, window_close)[-1],
                '吞没形态': talib.CDLENGULFING(window_open, window_high, window_low, window_close)[-1],
                '启明星': talib.CDLMORNINGSTAR(window_open, window_high, window_low, window_close)[-1],
                '三白兵': talib.CDL3WHITESOLDIERS(window_open, window_high, window_low, window_close)[-1],
                '上吊线': talib.CDLHANGINGMAN(window_open, window_high, window_low, window_close)[-1],
                '黄昏星': talib.CDLEVENINGSTAR(window_open, window_high, window_low, window_close)[-1],
                '三黑鸦': talib.CDL3BLACKCROWS(window_open, window_high, window_low, window_close)[-1]
            }
            
            # 看看这个窗口是否检测到任何形态
            bullish_patterns = {k: v for k, v in pattern_results.items() if v > 0}
            bearish_patterns = {k: v for k, v in pattern_results.items() if v < 0}
            
            # 如果检测到形态，输出详细信息
            if bullish_patterns or bearish_patterns:
                date_str = df['date'].iloc[i] if 'date' in df.columns else i
                if bullish_patterns:
                    patterns_str = ", ".join(f"{k}: {v}" for k, v in bullish_patterns.items())
                    print(f"位置 {i} ({date_str}) - 检测到看涨形态: {patterns_str}")
                if bearish_patterns:
                    patterns_str = ", ".join(f"{k}: {v}" for k, v in bearish_patterns.items())
                    print(f"位置 {i} ({date_str}) - 检测到看跌形态: {patterns_str}")
            
        except Exception as e:
            print(f"位置 {i} 形态检测出错: {str(e)}")
    
    return result_df

def find_data_file():
    """查找可能的数据文件"""
    possible_dirs = ['data', '.', 'stock_data']
    
    for dir_path in possible_dirs:
        if os.path.exists(dir_path):
            csv_files = [f for f in os.listdir(dir_path) if f.endswith('.csv')]
            if csv_files:
                return os.path.join(dir_path, csv_files[0])
    
    return None

if __name__ == "__main__":
    # 获取命令行参数
    if len(sys.argv) > 1:
        data_file = sys.argv[1]
    else:
        # 自动查找数据文件
        data_file = find_data_file()
        
    if not data_file:
        print("未找到数据文件，请指定数据文件路径")
        sys.exit(1)
        
    print(f"使用数据文件: {data_file}")
    
    # 加载数据
    df = load_stock_data(data_file)
    if df is None:
        sys.exit(1)
        
    # 分析数据
    df = analyze_data(df)
    if df is None:
        sys.exit(1)
        
    # 测试形态识别
    result_df = test_pattern_detection(df)
    
    # 保存结果
    result_df.to_csv('pattern_detection_debug.csv', index=False)
    print("\n结果已保存到 pattern_detection_debug.csv") 