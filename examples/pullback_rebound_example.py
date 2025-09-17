#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
止跌反弹策略使用示例
演示如何使用止跌反弹策略进行回测和扫描
"""

import sys
import os
from datetime import datetime

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bin import simulator
from bin.scanner_analyzer import scan_and_visualize_analyzer
from strategy.pullback_rebound_strategy import PullbackReboundStrategy
from strategy.scannable_pullback_rebound_strategy import ScannablePullbackReboundStrategy
from strategy.strategy_params.pullback_rebound_strategy_param import get_params


def example_single_backtest():
    """示例1：单个股票回测"""
    print("=" * 60)
    print("示例1：单个股票回测")
    print("=" * 60)
    
    stock_code = '300059'  # 东方财富
    
    # 使用默认参数
    print(f"使用默认参数回测股票: {stock_code}")
    
    try:
        simulator.go_trade(
            code=stock_code,
            amount=100000,
            startdate=datetime(2023, 1, 1),
            enddate=datetime(2025, 8, 22),
            strategy=PullbackReboundStrategy,
            strategy_params={'debug': True},  # 开启详细日志
            log_trades=True,
            visualize=True,
            interactive_plot=False,  # 不弹出交互图
        )
        print(f"股票 {stock_code} 回测完成")
    except Exception as e:
        print(f"回测失败: {e}")


def example_custom_params_backtest():
    """示例2：使用自定义参数回测"""
    print("\n" + "=" * 60)
    print("示例2：使用自定义参数回测")
    print("=" * 60)
    
    stock_code = '002415'  # 海康威视
    
    # 使用激进型参数
    aggressive_params = get_params('aggressive')
    aggressive_params['debug'] = True  # 开启调试日志
    
    print(f"使用激进型参数回测股票: {stock_code}")
    print(f"参数配置: {aggressive_params}")
    
    try:
        simulator.go_trade(
            code=stock_code,
            amount=100000,
            startdate=datetime(2023, 1, 1),
            enddate=datetime(2025, 8, 22),
            strategy=PullbackReboundStrategy,
            strategy_params=aggressive_params,
            log_trades=True,
            visualize=True,
            interactive_plot=False,
        )
        print(f"股票 {stock_code} 回测完成")
    except Exception as e:
        print(f"回测失败: {e}")


def example_batch_scan():
    """示例3：批量扫描"""
    print("\n" + "=" * 60)
    print("示例3：批量扫描")
    print("=" * 60)
    
    # 定义扫描参数
    signal_patterns = [
        '*** 止跌反弹买入信号触发',
        '止跌反弹信号',
    ]
    
    start_date = '20250630'
    end_date = None
    details_after_date = '20250820'
    
    print(f"扫描时间范围: {start_date} 到 {end_date or '最新'}")
    print(f"信号模式: {signal_patterns}")
    
    try:
        scan_and_visualize_analyzer(
            scan_strategy=ScannablePullbackReboundStrategy,
            scan_start_date=start_date,
            scan_end_date=end_date,
            stock_pool=None,  # 扫描所有股票
            signal_patterns=signal_patterns,
            details_after_date=details_after_date,
            candidate_model='a'
        )
        print("批量扫描完成")
    except Exception as e:
        print(f"批量扫描失败: {e}")


def example_parameter_comparison():
    """示例4：参数配置对比"""
    print("\n" + "=" * 60)
    print("示例4：参数配置对比")
    print("=" * 60)
    
    from strategy.strategy_params.pullback_rebound_strategy_param import print_params_comparison
    
    # 打印所有参数配置的对比
    print_params_comparison()


def example_multiple_stocks_test():
    """示例5：多股票测试"""
    print("\n" + "=" * 60)
    print("示例5：多股票测试")
    print("=" * 60)
    
    # 测试股票列表
    test_stocks = [
        '300059',  # 东方财富
        '002415',  # 海康威视
        '000858',  # 五粮液
    ]
    
    # 使用测试参数（降低要求便于触发信号）
    test_params = get_params('test')
    
    print(f"测试股票: {test_stocks}")
    print(f"使用参数: test")
    
    for stock_code in test_stocks:
        print(f"\n测试股票: {stock_code}")
        try:
            simulator.go_trade(
                code=stock_code,
                amount=100000,
                startdate=datetime(2023, 1, 1),
                enddate=datetime(2025, 8, 22),
                strategy=PullbackReboundStrategy,
                strategy_params=test_params,
                log_trades=True,
                visualize=False,  # 多股票测试时不生成图表
                interactive_plot=False,
            )
            print(f"股票 {stock_code} 测试完成")
        except Exception as e:
            print(f"股票 {stock_code} 测试失败: {e}")


def main():
    """主函数：运行所有示例"""
    print("止跌反弹策略使用示例")
    print("=" * 60)
    
    # 让用户选择要运行的示例
    examples = {
        '1': ('单个股票回测', example_single_backtest),
        '2': ('自定义参数回测', example_custom_params_backtest),
        '3': ('批量扫描', example_batch_scan),
        '4': ('参数配置对比', example_parameter_comparison),
        '5': ('多股票测试', example_multiple_stocks_test),
        'all': ('运行所有示例', None),
    }
    
    print("可用示例:")
    for key, (desc, _) in examples.items():
        print(f"  {key}: {desc}")
    
    choice = input("\n请选择要运行的示例 (输入数字或'all'): ").strip()
    
    if choice == 'all':
        # 运行所有示例
        for key, (desc, func) in examples.items():
            if func:  # 跳过'all'选项
                print(f"\n正在运行: {desc}")
                func()
    elif choice in examples and examples[choice][1]:
        # 运行选定的示例
        desc, func = examples[choice]
        print(f"\n正在运行: {desc}")
        func()
    else:
        print("无效选择，运行参数配置对比示例...")
        example_parameter_comparison()
    
    print("\n示例运行完成！")


if __name__ == '__main__':
    main()
