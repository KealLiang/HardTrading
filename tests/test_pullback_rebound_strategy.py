"""
测试止跌反弹策略的参数和基本功能
"""
import sys
sys.path.append('..')

from strategy.pullback_rebound_strategy import PullbackReboundStrategy
from strategy.scannable_pullback_rebound_strategy import ScannablePullbackReboundStrategy


def test_strategy_params():
    """测试策略参数是否正确"""
    print("=" * 60)
    print("测试止跌反弹策略参数")
    print("=" * 60)
    
    # 获取策略的默认参数（backtrader的params是一个元组的元组）
    # 需要直接访问_getpairsbase()或通过实例化来获取
    import backtrader as bt
    
    # 创建一个临时的cerebro来获取参数
    cerebro = bt.Cerebro()
    
    # 获取策略类的params
    params_tuple = PullbackReboundStrategy.params._getpairsbase()
    
    print("\n当前策略参数:")
    for param_name, param_value in params_tuple:
        print(f"  {param_name:25s} = {param_value}")
    
    # 检查是否还有未使用的参数
    removed_params = ['volume_dry_ratio', 'stabilization_days', 'divergence_days']
    print("\n检查已删除的未使用参数:")
    for param_name in removed_params:
        exists = any(p[0] == param_name for p in params_tuple)
        status = "❌ 仍存在" if exists else "✓ 已删除"
        print(f"  {param_name:25s} : {status}")
    
    # 检查关键参数是否存在
    key_params = [
        'uptrend_period',
        'uptrend_min_gain',
        'volume_ma_period',
        'volume_surge_ratio',
        'pullback_max_ratio',
        'pullback_max_days',
        'pullback_min_days',
        'initial_stake_pct',
        'profit_target',
        'stop_loss',
        'max_hold_days',
        'debug'
    ]
    
    print("\n检查关键参数:")
    for param_name in key_params:
        exists = any(p[0] == param_name for p in params_tuple)
        status = "✓" if exists else "❌ 缺失"
        print(f"  {param_name:25s} : {status}")
    
    print("\n" + "=" * 60)
    print("参数检查完成！")
    print("=" * 60)


def test_scannable_strategy():
    """测试可扫描策略是否正常"""
    print("\n" + "=" * 60)
    print("测试可扫描策略")
    print("=" * 60)
    
    params = ScannablePullbackReboundStrategy.params
    
    # 检查是否包含扫描相关参数
    scan_params = ['signal_callback', 'silent']
    print("\n检查扫描相关参数:")
    for param_name in scan_params:
        exists = any(p[0] == param_name for p in params)
        status = "✓" if exists else "❌ 缺失"
        print(f"  {param_name:25s} : {status}")
    
    print("\n" + "=" * 60)
    print("可扫描策略检查完成！")
    print("=" * 60)


if __name__ == '__main__':
    test_strategy_params()
    test_scannable_strategy()
    print("\n✅ 所有测试完成！") 