import os
import sys
import pandas as pd
import numpy as np

# 添加项目路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

def calc_ema(series, period):
    """计算EMA"""
    return series.ewm(span=period, adjust=False).mean()

def calc_rsi(series, period=14):
    """计算RSI"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calc_bollinger(series, period=20, std_dev=2):
    """计算布林带"""
    mid = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return upper, mid, lower

# 模拟数据：构造一个明显的震荡市场景
np.random.seed(42)
dates = pd.date_range('2025-10-20 09:30', periods=150, freq='5min')

# 基础价格：震荡在10元附近
base_price = 10.0
prices = []
current_price = base_price

for i in range(150):
    # 模拟震荡：在9.5-10.5之间
    if i < 50:
        # 前50根：下跌到下轨
        target = 9.6
    elif i < 100:
        # 中间50根：反弹到上轨
        target = 10.4
    else:
        # 后50根：再次下跌
        target = 9.7
    
    # 缓慢移动到目标价格
    current_price += (target - current_price) * 0.1 + np.random.normal(0, 0.02)
    prices.append(current_price)

df = pd.DataFrame({
    'datetime': dates,
    'open': prices,
    'high': [p * 1.002 for p in prices],
    'low': [p * 0.998 for p in prices],
    'close': prices,
    'vol': np.random.randint(1000, 5000, 150)
})

# 计算指标
df['ema21'] = calc_ema(df['close'], 21)
df['rsi14'] = calc_rsi(df['close'], 14)
df['bb_upper'], df['bb_mid'], df['bb_lower'] = calc_bollinger(df['close'], 20, 2)

print("=" * 80)
print("模拟震荡市数据分析")
print("=" * 80)

print(f"\n数据概况:")
print(f"K线数: {len(df)}")
print(f"价格范围: {df['close'].min():.2f} ~ {df['close'].max():.2f}")

# 检查买入条件
df['buy_cond_bb'] = df['close'] <= df['bb_lower']
df['buy_cond_rsi'] = df['rsi14'] < 30
df['buy_signal'] = df['buy_cond_bb'] & df['buy_cond_rsi']

buy_count = df['buy_signal'].sum()
print(f"\n买入信号候选数: {buy_count}")

if buy_count > 0:
    print("\n买入信号详情:")
    buy_signals = df[df['buy_signal']][['datetime', 'close', 'bb_lower', 'rsi14']]
    print(buy_signals)

# 检查卖出条件
df['sell_cond_bb'] = df['close'] >= df['bb_upper']
df['sell_cond_rsi'] = df['rsi14'] > 70
df['sell_signal'] = df['sell_cond_bb'] & df['sell_cond_rsi']

sell_count = df['sell_signal'].sum()
print(f"\n卖出信号候选数: {sell_count}")

if sell_count > 0:
    print("\n卖出信号详情:")
    sell_signals = df[df['sell_signal']][['datetime', 'close', 'bb_upper', 'rsi14']]
    print(sell_signals)

# 统计
print(f"\n指标统计:")
print(f"RSI范围: {df['rsi14'].min():.1f} ~ {df['rsi14'].max():.1f}")
print(f"RSI平均: {df['rsi14'].mean():.1f}")
print(f"触及下轨次数: {df['buy_cond_bb'].sum()}")
print(f"触及上轨次数: {df['sell_cond_bb'].sum()}")
print(f"RSI<30次数: {df['buy_cond_rsi'].sum()}")
print(f"RSI>70次数: {df['sell_cond_rsi'].sum()}")

print("\n" + "=" * 80)
print("结论：如果模拟数据都没有信号，说明策略参数太严格")
print("=" * 80) 