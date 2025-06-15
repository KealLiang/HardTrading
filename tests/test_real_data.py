import numpy as np
import pandas as pd
import talib
import matplotlib.pyplot as plt
import os
import glob

def find_stock_data_files():
    """查找工作目录中的股票数据文件"""
    # 尝试查找数据目录下的CSV文件
    possible_dirs = ['data', 'stock_data', '.']
    for dir_path in possible_dirs:
        if os.path.exists(dir_path):
            csv_files = glob.glob(os.path.join(dir_path, "*.csv"))
            if csv_files:
                print(f"找到 {len(csv_files)} 个CSV文件在 {dir_path} 目录")
                return csv_files[0]  # 返回第一个找到的文件作为示例
    
    print("未找到股票数据文件，将创建模拟数据")
    return None

def generate_sample_data(num_days=250):
    """生成模拟股票数据"""
    np.random.seed(42)
    dates = pd.date_range(start='2020-01-01', periods=num_days)
    
    # 创建趋势
    trend = np.cumsum(np.random.normal(0.0005, 0.01, num_days))
    
    # 初始价格
    base_price = 100
    
    # 生成OHLC数据
    high = base_price * (1 + trend + np.abs(np.random.normal(0, 0.02, num_days)))
    low = base_price * (1 + trend - np.abs(np.random.normal(0, 0.02, num_days)))
    close = base_price * (1 + trend + np.random.normal(0, 0.01, num_days))
    open_price = np.roll(close, 1)  # 当前开盘价等于前一天收盘价，加一些波动
    open_price[0] = base_price
    
    # 加入一些波动
    for i in range(num_days):
        high[i] = max(high[i], open_price[i], close[i])
        low[i] = min(low[i], open_price[i], close[i])
    
    # 创建DataFrame
    df = pd.DataFrame({
        'date': dates,
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': np.random.randint(1000, 10000, num_days)
    })
    
    print("已生成模拟股票数据")
    return df

def load_stock_data(file_path=None):
    """加载股票数据"""
    if file_path and os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path)
            print(f"成功加载数据文件: {file_path}")
            # 检查必要的列
            required_cols = ['open', 'high', 'low', 'close']
            # 将列名转为小写以便匹配
            df.columns = [col.lower() for col in df.columns]
            
            if all(col in df.columns for col in required_cols):
                return df
            else:
                print(f"数据文件缺少必要的列: {required_cols}")
        except Exception as e:
            print(f"加载数据文件时出错: {str(e)}")
    
    # 如果没有找到文件或者加载失败，生成模拟数据
    return generate_sample_data()

def test_all_candlestick_patterns(df):
    """测试所有的K线形态识别函数"""
    # 确保数据类型正确
    open_prices = np.array(df['open'].values, dtype=np.float64)
    high_prices = np.array(df['high'].values, dtype=np.float64)
    low_prices = np.array(df['low'].values, dtype=np.float64)
    close_prices = np.array(df['close'].values, dtype=np.float64)
    
    # 获取所有的K线形态函数
    pattern_functions = [func for func in dir(talib) if func.startswith('CDL')]
    
    # 创建一个字典来存储结果
    pattern_results = {}
    
    print("\n测试所有K线形态识别函数:")
    print(f"数据点数: {len(df)}")
    print("-" * 50)
    
    # 对每个形态函数进行测试
    total_detected = 0
    detected_patterns = {}
    
    for func_name in pattern_functions:
        try:
            # 获取函数对象
            pattern_func = getattr(talib, func_name)
            
            # 执行形态识别
            result = pattern_func(open_prices, high_prices, low_prices, close_prices)
            
            # 找出非零值，即识别出的形态
            nonzero_indices = np.where(result != 0)[0]
            num_detected = len(nonzero_indices)
            
            pattern_results[func_name] = result
            if num_detected > 0:
                detected_patterns[func_name] = num_detected
                total_detected += num_detected
                print(f"{func_name}: 检测到 {num_detected} 个形态信号")
                # 打印一些检测到的形态的详细信息
                if num_detected <= 5:  # 限制显示的信号数
                    for idx in nonzero_indices:
                        if idx > 1 and idx < len(df) - 1:  # 确保有前后数据
                            date = df['date'].iloc[idx] if 'date' in df.columns else idx
                            print(f"  在 {date} 检测到信号值: {result[idx]}")
                            print(f"  相关数据: O={open_prices[idx]:.2f}, H={high_prices[idx]:.2f}, L={low_prices[idx]:.2f}, C={close_prices[idx]:.2f}")
                else:
                    print(f"  检测到太多信号，仅显示5个")
                    for idx in nonzero_indices[:5]:
                        if idx > 1 and idx < len(df) - 1:
                            date = df['date'].iloc[idx] if 'date' in df.columns else idx
                            print(f"  在 {date} 检测到信号值: {result[idx]}")
                            print(f"  相关数据: O={open_prices[idx]:.2f}, H={high_prices[idx]:.2f}, L={low_prices[idx]:.2f}, C={close_prices[idx]:.2f}")
            
        except Exception as e:
            print(f"{func_name}: 执行出错 - {str(e)}")
    
    # 打印汇总结果
    print("\n测试结果汇总:")
    print(f"总共测试了 {len(pattern_functions)} 种K线形态")
    print(f"检测到 {len(detected_patterns)} 种有信号的形态，总共 {total_detected} 个形态信号")
    
    # 按检测到的信号数量排序
    sorted_patterns = sorted(detected_patterns.items(), key=lambda x: x[1], reverse=True)
    print("\n检测到最多信号的前10种形态:")
    for pattern, count in sorted_patterns[:10]:
        print(f"{pattern}: {count} 个信号")
    
    # 特别检查我们关注的7种形态
    print("\n特别关注的K线形态检测结果:")
    focused_patterns = {
        'CDLHAMMER': '锤子线',
        'CDLENGULFING': '吞没形态',
        'CDLMORNINGSTAR': '启明星',
        'CDL3WHITESOLDIERS': '三白兵',
        'CDLHANGINGMAN': '上吊线',
        'CDLEVENINGSTAR': '黄昏星',
        'CDL3BLACKCROWS': '三黑鸦'
    }
    
    for func_name, chinese_name in focused_patterns.items():
        if func_name in pattern_results:
            result = pattern_results[func_name]
            num_detected = np.sum(result != 0)
            print(f"{chinese_name} ({func_name}): 检测到 {num_detected} 个形态信号")
    
    # 保存结果到CSV文件
    result_df = pd.DataFrame(index=df.index)
    for func_name, result in pattern_results.items():
        result_df[func_name] = result
    
    result_df.to_csv('pattern_detection_results.csv', index=False)
    print("\n所有形态检测结果已保存到 pattern_detection_results.csv")
    
    return pattern_results

if __name__ == "__main__":
    # 尝试查找股票数据文件
    file_path = find_stock_data_files()
    
    # 加载数据
    df = load_stock_data(file_path)
    
    # 显示数据前几行
    print("\n数据预览:")
    print(df.head())
    
    # 测试所有K线形态
    pattern_results = test_all_candlestick_patterns(df) 