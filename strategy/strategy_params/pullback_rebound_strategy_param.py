#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
止跌反弹策略参数配置文件
包含不同市场环境下的参数组合
"""

# 默认参数配置
DEFAULT_PARAMS = {
    # 主升浪识别参数
    'uptrend_period': 20,          # 主升浪判断周期
    'uptrend_min_gain': 0.30,      # 主升浪最小涨幅30%
    'volume_ma_period': 20,        # 成交量均线周期
    'volume_surge_ratio': 1.5,     # 主升浪期间放量倍数
    
    # 回调识别参数
    'pullback_max_ratio': 0.15,    # 最大回调幅度15%
    'pullback_max_days': 15,       # 最大回调天数（调整为15天）
    'pullback_min_days': 3,        # 最小回调天数
    
    # 企稳信号参数
    'volume_dry_ratio': 0.6,       # 量窒息阈值（相对均量）
    'stabilization_days': 4,       # 企稳信号观察期
    'divergence_days': 3,          # 量价背离观察期
    
    # 交易参数
    'initial_stake_pct': 0.8,      # 初始仓位比例
    'profit_target': 0.12,         # 止盈目标12%
    'stop_loss': 0.05,             # 止损比例5%
    'max_hold_days': 10,           # 最大持有天数
    
    # 调试参数
    'debug': False,                # 是否开启详细日志
}

# 激进型参数配置（适合强势市场）
AGGRESSIVE_PARAMS = {
    **DEFAULT_PARAMS,
    'uptrend_min_gain': 0.25,      # 降低主升浪要求
    'pullback_max_ratio': 0.20,    # 增加回调容忍度
    'volume_dry_ratio': 0.7,       # 放宽量窒息要求
    'profit_target': 0.15,         # 提高止盈目标
    'stop_loss': 0.06,             # 稍微放宽止损
    'max_hold_days': 12,           # 延长持有时间
}

# 保守型参数配置（适合震荡市场）
CONSERVATIVE_PARAMS = {
    **DEFAULT_PARAMS,
    'uptrend_min_gain': 0.35,      # 提高主升浪要求
    'pullback_max_ratio': 0.12,    # 减少回调容忍度
    'volume_dry_ratio': 0.5,       # 严格量窒息要求
    'profit_target': 0.08,         # 降低止盈目标
    'stop_loss': 0.04,             # 严格止损
    'max_hold_days': 8,            # 缩短持有时间
}

# 短线型参数配置（适合快进快出）
SHORT_TERM_PARAMS = {
    **DEFAULT_PARAMS,
    'uptrend_period': 15,          # 缩短主升浪判断周期
    'uptrend_min_gain': 0.20,      # 降低主升浪要求
    'pullback_max_days': 8,        # 缩短回调观察期
    'pullback_min_days': 2,        # 缩短最小回调天数
    'stabilization_days': 3,       # 缩短企稳观察期
    'profit_target': 0.08,         # 降低止盈目标
    'stop_loss': 0.04,             # 严格止损
    'max_hold_days': 6,            # 缩短持有时间
}

# 中长线型参数配置（适合趋势跟踪）
LONG_TERM_PARAMS = {
    **DEFAULT_PARAMS,
    'uptrend_period': 30,          # 延长主升浪判断周期
    'uptrend_min_gain': 0.40,      # 提高主升浪要求
    'pullback_max_ratio': 0.18,    # 增加回调容忍度
    'pullback_max_days': 15,       # 延长回调观察期
    'stabilization_days': 5,       # 延长企稳观察期
    'profit_target': 0.20,         # 提高止盈目标
    'stop_loss': 0.08,             # 放宽止损
    'max_hold_days': 15,           # 延长持有时间
}

# 测试型参数配置（用于策略验证）
TEST_PARAMS = {
    **DEFAULT_PARAMS,
    'uptrend_min_gain': 0.15,      # 大幅降低主升浪要求
    'pullback_max_ratio': 0.25,    # 大幅增加回调容忍度
    'volume_dry_ratio': 0.8,       # 放宽量窒息要求
    'profit_target': 0.06,         # 降低止盈目标
    'stop_loss': 0.08,             # 放宽止损
    'debug': True,                 # 开启详细日志
}

# 参数组合字典
PARAM_COMBINATIONS = {
    'default': DEFAULT_PARAMS,
    'aggressive': AGGRESSIVE_PARAMS,
    'conservative': CONSERVATIVE_PARAMS,
    'short_term': SHORT_TERM_PARAMS,
    'long_term': LONG_TERM_PARAMS,
    'test': TEST_PARAMS,
}


def get_params(param_type='default'):
    """
    获取指定类型的参数配置
    
    Args:
        param_type (str): 参数类型，可选值：
            - 'default': 默认参数
            - 'aggressive': 激进型参数
            - 'conservative': 保守型参数
            - 'short_term': 短线型参数
            - 'long_term': 中长线型参数
            - 'test': 测试型参数
    
    Returns:
        dict: 参数配置字典
    """
    return PARAM_COMBINATIONS.get(param_type, DEFAULT_PARAMS).copy()


def print_params_comparison():
    """打印所有参数配置的对比"""
    print("止跌反弹策略参数配置对比:")
    print("=" * 80)
    
    # 获取所有参数键
    all_keys = set()
    for params in PARAM_COMBINATIONS.values():
        all_keys.update(params.keys())
    
    # 打印表头
    print(f"{'参数名':<20}", end="")
    for param_type in PARAM_COMBINATIONS.keys():
        print(f"{param_type:<12}", end="")
    print()
    print("-" * 80)
    
    # 打印每个参数的值
    for key in sorted(all_keys):
        print(f"{key:<20}", end="")
        for param_type in PARAM_COMBINATIONS.keys():
            value = PARAM_COMBINATIONS[param_type].get(key, 'N/A')
            print(f"{str(value):<12}", end="")
        print()


if __name__ == '__main__':
    # 打印参数对比
    print_params_comparison()
    
    # 示例：获取激进型参数
    aggressive_params = get_params('aggressive')
    print(f"\n激进型参数配置:")
    for key, value in aggressive_params.items():
        print(f"  {key}: {value}")
