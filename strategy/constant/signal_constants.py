# -*- coding: utf-8 -*-
"""
信号常量配置文件
"""

# --- 信号标准名称 (Canonical Names) ---
# 作为系统中信号的唯一标识符
SIG_BREAKOUT = '突破信号'
SIG_COILED_SPRING = '蓄势待发'
SIG_POCKET_PIVOT = '口袋支点'
SIG_SENTRY = '观察哨'
SIG_CONFIRMATION = '二次确认'
SIG_SELL = '卖出信号'
SIG_SOURCE = '源信号'  # 用于独立回测模式中标注买入的源头
SIG_UNKNOWN = 'Unknown'

# --- 日志解析规则 ---
# 定义了从策略日志文本中提取标准信号名称的规则。
# 键(key)是日志中的唯一文本片段，值(value)是对应的标准信号名称。
# 解析时会按顺序匹配，因此应将最具体、最独特的规则放在前面。
LOG_FRAGMENT_TO_SIGNAL_MAP = {
    '【口袋支点】': SIG_POCKET_PIVOT,
    '【蓄势待发】': SIG_COILED_SPRING,
    '*** 二次确认信号': SIG_CONFIRMATION,
    '卖出信号': SIG_SELL,
    '*** 触发【突破观察哨】': SIG_SENTRY,
    '突破信号:': SIG_BREAKOUT,
}

# --- 可视化配置 ---
# 定义了每种信号在 mplfinance 图表上的显示样式。
SIGNAL_MARKER_MAP = {
    # --- 扫描模式下的信号样式 ---
    SIG_BREAKOUT: {'marker': 'P', 'color': 'purple', 'size': 100},
    SIG_COILED_SPRING: {'marker': '*', 'color': 'cyan', 'size': 100},
    SIG_POCKET_PIVOT: {'marker': 'd', 'color': 'royalblue', 'size': 100},
    SIG_SENTRY: {'marker': 's', 'color': 'orange', 'size': 100},
    SIG_CONFIRMATION: {'marker': 'p', 'color': 'crimson', 'size': 120},
    SIG_SELL: {'marker': 'X', 'color': 'green', 'size': 120},

    # --- 回测模式下的信号样式 ---
    SIG_SOURCE: {'marker': 'o', 'color': 'cyan', 'size': 100},

    # --- 未知或默认信号 ---
    SIG_UNKNOWN: {'marker': 'o', 'color': 'yellow', 'size': 80},
}
