#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性修复 + 验证：
1) 统一成交额CSV日期格式为 YYYY-MM-DD（此前混入 YYYY-MM-DD HH:MM:SS 导致解析失败）
2) 东财增量补齐缺失交易日
3) 重新生成市场强弱分布图
"""

import sys

sys.path.insert(0, '.')

import pandas as pd
import matplotlib.pyplot as plt

from analysis.fupan_statistics_plot import plot_market_strength, filter_data_by_date
from fetch.indexes_data import AMOUNT_INDICES, INDEX_FILES, fetch_and_save_index_data_em

plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False

# 1. 格式归一化
for symbol in AMOUNT_INDICES:
    path = f'./data/indexes/{symbol}_amount.csv'
    df = pd.read_csv(path, dtype={'date': str})
    df['date'] = pd.to_datetime(df['date'], format='mixed', errors='coerce')
    df = df.dropna(subset=['date']).drop_duplicates(subset='date', keep='last')
    df = df.sort_values('date')
    df['date'] = df['date'].dt.strftime('%Y-%m-%d')
    df.to_csv(path, index=False)
    print(f'{symbol}_amount.csv 归一化完成，{len(df)} 行，最后一日 {df["date"].iloc[-1]}')

# 2. 增量补齐
for symbol, secid in AMOUNT_INDICES.items():
    fetch_and_save_index_data_em(
        symbol, secid,
        f'./data/indexes/{INDEX_FILES[symbol]}',
        f'./data/indexes/{symbol}_amount.csv')

# 3. 重新绘图
df = pd.read_excel('./excel/market_analysis.xlsx')
df.set_index('日期', inplace=True)
df = filter_data_by_date(df)
plot_market_strength(df, './images/market_analysis')

for symbol in AMOUNT_INDICES:
    path = f'./data/indexes/{symbol}_amount.csv'
    print(f'--- {symbol}_amount.csv 尾部 ---')
    print(pd.read_csv(path).tail(4).to_string())
print('修复完成，图已重新生成')
