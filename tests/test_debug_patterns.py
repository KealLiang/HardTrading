import numpy as np
import talib
import pandas as pd

# 设置用于测试的数据
def setup_test_data():
    # 生成样本数据 (20天的数据)
    dates = pd.date_range(start='2023-01-01', periods=20)
    np.random.seed(42)
    
    close = np.random.normal(100, 5, 20)
    open_price = close + np.random.normal(0, 2, 20)
    high = np.maximum(close, open_price) + np.random.normal(1, 0.5, 20)
    low = np.minimum(close, open_price) - np.random.normal(1, 0.5, 20)
    
    # 确保合理性
    for i in range(len(close)):
        high[i] = max(high[i], open_price[i], close[i])
        low[i] = min(low[i], open_price[i], close[i])
    
    # 创建一些特定形态
    # 1. 吞没形态 - 在索引5
    open_price[4] = 105.0
    close[4] = 102.0  # 阴线
    open_price[5] = 101.0
    close[5] = 106.0  # 阳线，吞没前一天
    
    # 2. 锤子线 - 在索引8
    open_price[8] = 95.0
    close[8] = 95.2
    high[8] = 95.5
    low[8] = 92.0  # 长下影线
    
    # 3. 启明星 - 在索引11-13
    open_price[11] = 100.0
    close[11] = 97.0  # 阴线
    open_price[12] = 96.0
    close[12] = 96.2  # 小实体
    open_price[13] = 96.5
    close[13] = 99.0  # 阳线
    
    # 4. 三白兵 - 在索引15-17
    for i in range(15, 18):
        open_price[i] = 100 + (i-15)*2
        close[i] = open_price[i] + 2  # 三根连续上涨的阳线
    
    return open_price, high, low, close, dates

def test_all_strategy_patterns():
    """测试策略中使用的所有K线形态函数"""
    open_price, high, low, close, dates = setup_test_data()
    
    # 为了更好展示，创建DataFrame
    df = pd.DataFrame({
        'date': dates,
        'open': open_price,
        'high': high,
        'low': low,
        'close': close
    })
    
    # 定义要测试的形态
    patterns = {
        'CDLHAMMER': '锤子线',
        'CDLENGULFING': '吞没形态',
        'CDLMORNINGSTAR': '启明星',
        'CDL3WHITESOLDIERS': '三白兵',
        'CDLHANGINGMAN': '上吊线',
        'CDLEVENINGSTAR': '黄昏星',
        'CDL3BLACKCROWS': '三黑鸦'
    }
    
    print(f"TA-Lib版本: {talib.__version__}")
    print("\n原始价格数据:")
    print(df[['date', 'open', 'high', 'low', 'close']].to_string(index=False))
    
    print("\n\n=== 各种形态识别结果 ===")
    for func_name, pattern_name in patterns.items():
        pattern_func = getattr(talib, func_name)
        result = pattern_func(open_price, high, low, close)
        
        # 添加结果列
        col_name = pattern_name
        df[col_name] = result
        
        # 找出非零值（识别出的形态）的位置
        indices = np.where(result != 0)[0]
        
        if len(indices) > 0:
            print(f"\n{pattern_name} ({func_name}) 识别结果:")
            for idx in indices:
                # 获取信号前后的数据
                start_idx = max(0, idx-2)
                end_idx = min(len(df), idx+3)
                context = df.iloc[start_idx:end_idx].copy()
                
                # 添加标记
                context['标记'] = ' '
                context.loc[context.index[context.index.get_loc(idx)], '标记'] = '>>>'
                
                print(f"  在 {df.iloc[idx]['date'].strftime('%Y-%m-%d')} 检测到，信号值: {result[idx]}")
                print(context[['标记', 'date', 'open', 'high', 'low', 'close', col_name]].to_string(index=False))
                print()
        else:
            print(f"\n{pattern_name} ({func_name}): 未检测到形态")
    
    # 保存结果到CSV文件，便于查看
    df.to_csv('pattern_recognition_results.csv', index=False)
    print("\n所有结果已保存到 pattern_recognition_results.csv")

if __name__ == "__main__":
    test_all_strategy_patterns() 