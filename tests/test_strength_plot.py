#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试市场强弱分布图的效果
"""

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

def test_market_strength_plot():
    """测试市场强弱分布图"""
    # 读取数据
    df = pd.read_excel('./excel/market_analysis.xlsx')
    
    # 取最近20天的数据
    df = df.tail(20).copy()
    df.reset_index(drop=True, inplace=True)
    
    # 检查必要的列是否存在
    required_cols = ['涨幅超过5%家数', '涨幅超过7%家数', '涨幅超过9%家数',
                     '跌幅超过5%家数', '跌幅超过7%家数', '跌幅超过9%家数']
    
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        print(f"缺少列: {missing_cols}")
        return
    
    # 绘制图表
    plt.figure(figsize=(15, 8))
    x = np.arange(len(df))
    width = 0.35

    # 上半部分（涨幅）- 三个档次的红色深度
    plt.bar(x, df['涨幅超过5%家数'], width, color='#ffcccc', alpha=0.8, label='涨幅>5%')
    plt.bar(x, df['涨幅超过7%家数'], width, color='#ff6666', alpha=0.8, label='涨幅>7%')
    plt.bar(x, df['涨幅超过9%家数'], width, color='#cc0000', alpha=0.8, label='涨幅>9%')

    # 下半部分（跌幅）- 三个档次的绿色深度
    plt.bar(x, -df['跌幅超过5%家数'], width, color='#ccffcc', alpha=0.8, label='跌幅>5%')
    plt.bar(x, -df['跌幅超过7%家数'], width, color='#66ff66', alpha=0.8, label='跌幅>7%')
    plt.bar(x, -df['跌幅超过9%家数'], width, color='#00cc00', alpha=0.8, label='跌幅>9%')

    plt.xlabel('日期')
    plt.ylabel('家数')
    plt.title('市场强弱分布（优化版）', fontsize=14)
    
    # 格式化日期显示
    dates = [str(d) for d in df['日期']]
    plt.xticks(x, dates, rotation=45, ha='right')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    # 保存图片
    os.makedirs('../images/test', exist_ok=True)
    plt.savefig('./images/test/market_strength_optimized.png', dpi=300, bbox_inches='tight')
    plt.close()
    
    print("优化后的市场强弱分布图已保存到: ./images/test/market_strength_optimized.png")
    
    # 打印数据统计
    print("\n数据统计:")
    print(f"日期范围: {dates[0]} 到 {dates[-1]}")
    print(f"涨幅>9%平均: {df['涨幅超过9%家数'].mean():.1f}")
    print(f"跌幅>9%平均: {df['跌幅超过9%家数'].mean():.1f}")

if __name__ == "__main__":
    test_market_strength_plot()
