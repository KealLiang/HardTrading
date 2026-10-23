#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证：成交额数据落地 + 只重新生成市场强弱分布图（含成交额折线）"""

import sys
sys.path.insert(0, '.')

import pandas as pd
import matplotlib.pyplot as plt
from fetch.indexes_data import fetch_and_save_index_amount
from analysis.fupan_statistics_plot import plot_market_strength, filter_data_by_date

plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False

# 1. 首次落地成交额CSV（日常由 main.get_index_data 增量更新）
for symbol in ('sh000001', 'sz399001'):
    fetch_and_save_index_amount(symbol, f'./data/indexes/{symbol}_amount.csv')

# 2. 重新生成强弱分布图
df = pd.read_excel('./excel/market_analysis.xlsx')
df.set_index('日期', inplace=True)
df = filter_data_by_date(df)

plot_market_strength(df, './images/market_analysis')
print('验证完成: ./images/market_analysis_strength.png 已重新生成')
