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
SIG_FAST_TRACK = '快速通道'  # 三速档位：信号日当天直接买入
SIG_PULLBACK_WAIT = '回踩等待'  # 三速档位：等待回调到MA5附近
SIG_PULLBACK_CONFIRM = '回踩确认'  # 三速档位：回调出现，执行买入
SIG_BUY_EXECUTED = '买入成交'  # 实际买入成交日（用于图表标注）
SIG_STOP_LOSS_CORRECTION = '止损纠错'  # 止损后快速纠错买入
SIG_PULLBACK_REBOUND = '止跌反弹'  # 止跌反弹信号
SIG_UNKNOWN = 'Unknown'

# --- 日志解析规则 ---
# 定义了从策略日志文本中提取标准信号名称的规则。
# 键(key)是日志中的唯一文本片段，值(value)是对应的标准信号名称。
# 解析时会按顺序匹配，因此应将最具体、最独特的规则放在前面。
LOG_FRAGMENT_TO_SIGNAL_MAP = {
    '买入成交': SIG_BUY_EXECUTED,  # 最具体的，放在最前面（捕获实际成交日）
    '买入信号: 止损纠错': SIG_STOP_LOSS_CORRECTION,  # 纠错买入信号
    '快速通道': SIG_FAST_TRACK,
    '回踩确认': SIG_PULLBACK_CONFIRM,
    '*** 回踩等待期内出现回调': SIG_PULLBACK_CONFIRM,  # 备用匹配规则
    '进入【回踩等待】模式': SIG_PULLBACK_WAIT,
    '【口袋支点】': SIG_POCKET_PIVOT,
    '【蓄势待发】': SIG_COILED_SPRING,
    '*** 二次确认信号': SIG_CONFIRMATION,
    '卖出信号': SIG_SELL,
    '*** 触发【突破观察哨】': SIG_SENTRY,
    '突破信号:': SIG_BREAKOUT,
    '止跌反弹买入信号触发': SIG_PULLBACK_REBOUND,
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

    # --- 三速档位系统信号样式 ---
    # 在K线上方显示向右三角，不同颜色区分通道类型
    SIG_FAST_TRACK: {'marker': '>', 'color': 'gold', 'size': 120},  # 向右三角，金色
    SIG_PULLBACK_WAIT: {'marker': '>', 'color': 'lightskyblue', 'size': 100},  # 向右三角，浅蓝色
    SIG_PULLBACK_CONFIRM: {'marker': '>', 'color': 'limegreen', 'size': 120},  # 向右三角，绿色

    # --- 回测模式下的信号样式 ---
    SIG_SOURCE: {'marker': 'o', 'color': 'cyan', 'size': 100},

    # --- 买入成交和纠错信号 ---
    SIG_BUY_EXECUTED: {'marker': '^', 'color': 'lime', 'size': 150},  # 绿色上三角
    SIG_STOP_LOSS_CORRECTION: {'marker': 'D', 'color': 'orange', 'size': 110},  # 橙色菱形，显示在信号日

    # --- 止跌反弹信号 ---
    SIG_PULLBACK_REBOUND: {'marker': '+', 'color': 'dodgerblue', 'size': 120},  # 亮蓝加号

    # --- 未知或默认信号 ---
    SIG_UNKNOWN: {'marker': 'o', 'color': 'yellow', 'size': 80},
}
