"""
V5 做T信号 → QMT 自动交易（独立可插拔执行层）。

不修改 alerting/t_trade_alert_v5.py；通过子类覆盖 _trigger_signal 接入。
默认 dry_run=True，未装 xtquant / 未开 QMT 时也能跑通闭环。
"""

from .trade_config import QmtTradeConfig
from .executor import SignalExecutor
from .auto_monitor import QmtAutoMonitorV5, QmtAutoManagerV5

__all__ = [
    "QmtTradeConfig",
    "SignalExecutor",
    "QmtAutoMonitorV5",
    "QmtAutoManagerV5",
]
