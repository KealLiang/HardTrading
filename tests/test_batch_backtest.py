"""
批量回测功能测试

用少量股票快速验证批量回测功能是否正常工作
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime
from strategy.breakout_strategy_v2 import BreakoutStrategyV2
from bin.batch_backtester import batch_backtest_from_list


def test_batch_backtest_small():
    """
    小批量测试 - 用3只股票快速验证功能
    
    预计耗时：1-2分钟
    """
    print("=" * 60)
    print("开始小批量回测测试（3只股票）")
    print("=" * 60)
    
    # 使用少量股票进行测试
    test_stocks = ['300033', '300059', '600610']
    
    report_path = batch_backtest_from_list(
        stock_codes=test_stocks,
        strategy_class=BreakoutStrategyV2,
        strategy_params={'debug': False},
        startdate=datetime(2024, 1, 1),  # 只回测1年，加快速度
        enddate=datetime(2025, 1, 1),
        amount=100000,
        data_dir='./data/astocks',
        output_dir='tests/test_batch_results',
        max_workers=2  # 只用2个进程，避免CPU占用过高
    )
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print(f"报告路径: {report_path}")
    print("=" * 60)
    
    # 验证报告是否生成
    if os.path.exists(report_path):
        print("✅ 批量回测功能正常！")
        print(f"📊 请查看报告: {report_path}")
        return True
    else:
        print("❌ 报告生成失败！")
        return False


def test_batch_backtest_medium():
    """
    中等批量测试 - 用10只股票测试性能
    
    预计耗时：3-5分钟
    """
    print("=" * 60)
    print("开始中等批量回测测试（10只股票）")
    print("=" * 60)
    
    # 使用10只股票测试
    test_stocks = [
        '300033', '300059', '000062', '300204', '600610',
        '002693', '301357', '600744', '002173', '002640'
    ]
    
    report_path = batch_backtest_from_list(
        stock_codes=test_stocks,
        strategy_class=BreakoutStrategyV2,
        strategy_params={'debug': False},
        startdate=datetime(2023, 1, 1),  # 回测2年
        enddate=datetime(2025, 1, 1),
        amount=100000,
        data_dir='./data/astocks',
        output_dir='tests/test_batch_results',
        max_workers=4  # 使用4个进程
    )
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print(f"报告路径: {report_path}")
    print("=" * 60)
    
    if os.path.exists(report_path):
        print("✅ 批量回测功能正常！")
        print(f"📊 请查看报告: {report_path}")
        return True
    else:
        print("❌ 报告生成失败！")
        return False


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='批量回测功能测试')
    parser.add_argument('--mode', choices=['small', 'medium'], default='small',
                       help='测试模式：small=3只股票（快速），medium=10只股票（较慢）')
    
    args = parser.parse_args()
    
    if args.mode == 'small':
        success = test_batch_backtest_small()
    else:
        success = test_batch_backtest_medium()
    
    sys.exit(0 if success else 1)
