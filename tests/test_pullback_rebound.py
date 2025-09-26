#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
止跌反弹策略测试脚本
用于验证策略的基本功能
"""

import sys
import os
from datetime import datetime

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from bin import simulator
from strategy.pullback_rebound_strategy import PullbackReboundStrategy


def test_pullback_rebound_strategy():
    """测试止跌反弹策略"""
    print("开始测试止跌反弹策略...")
    
    # 测试股票代码（选择一些有明显主升浪和回调的股票）
    test_stocks = [
        '300059',  # 东方财富
        '002415',  # 海康威视
        '000858',  # 五粮液
    ]
    
    for stock_code in test_stocks:
        print(f"\n{'='*50}")
        print(f"测试股票: {stock_code}")
        print(f"{'='*50}")
        
        try:
            # 运行回测
            result = simulator.go_trade(
                code=stock_code,
                amount=100000,
                startdate=datetime(2023, 1, 1),
                enddate=datetime(2025, 8, 22),
                strategy=PullbackReboundStrategy,
                strategy_params={
                    'debug': True,  # 开启详细日志
                    'uptrend_min_gain': 0.25,  # 降低主升浪要求便于测试
                    'pullback_max_ratio': 0.20,  # 增加回调容忍度
                },
                log_trades=True,
                visualize=False,  # 测试时不生成图表
                interactive_plot=False,
            )
            
            print(f"股票 {stock_code} 测试完成")
            
        except Exception as e:
            print(f"股票 {stock_code} 测试失败: {e}")
        
        print("-" * 50)
    
    print("\n止跌反弹策略测试完成！")


def test_single_stock():
    """测试单个股票的详细情况"""
    stock_code = '300059'  # 东方财富
    
    print(f"详细测试股票: {stock_code}")
    
    try:
        result = simulator.go_trade(
            code=stock_code,
            amount=100000,
            startdate=datetime(2023, 1, 1),
            enddate=datetime(2025, 8, 22),
            strategy=PullbackReboundStrategy,
            strategy_params={
                'debug': True,  # 开启详细日志
                'uptrend_period': 15,  # 缩短主升浪判断周期
                'uptrend_min_gain': 0.20,  # 降低主升浪要求
                'pullback_max_ratio': 0.18,  # 增加回调容忍度
                'volume_dry_ratio': 0.7,  # 放宽量窒息要求
                'profit_target': 0.10,  # 降低止盈目标
                'stop_loss': 0.08,  # 放宽止损
            },
            log_trades=True,
            visualize=True,  # 生成图表
            interactive_plot=False,
        )
        
        print(f"详细测试完成")
        
    except Exception as e:
        print(f"详细测试失败: {e}")


if __name__ == '__main__':
    # 选择测试模式
    test_mode = input("选择测试模式 (1: 多股票测试, 2: 单股票详细测试): ").strip()
    
    if test_mode == '1':
        test_pullback_rebound_strategy()
    elif test_mode == '2':
        test_single_stock()
    else:
        print("无效选择，运行单股票详细测试...")
        test_single_stock()
