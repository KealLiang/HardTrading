"""
通过继承接入 V5：零改动 alerting/t_trade_alert_v5.py。

插拔方式：
  原入口继续用 MonitorManagerV5 → 仅飞书
  本入口用 QmtAutoManagerV5 → 飞书 +（可选）QMT 自动下单
"""
from __future__ import annotations

import logging
from typing import Optional

from alerting.t_trade_alert_v5 import MonitorManagerV5, TMonitorV5

from .trade_config import QmtTradeConfig
from .executor import SignalExecutor, TradeSignal

logger = logging.getLogger(__name__)


class QmtAutoMonitorV5(TMonitorV5):
    """在父类飞书通知之后，把结构化信号交给执行器。"""

    # 由 Manager 在启动前注入（多股票共享同一执行器）
    trade_executor: Optional[SignalExecutor] = None

    def _trigger_signal(self, signal_type, price, ts, reason, strength=None):
        super()._trigger_signal(signal_type, price, ts, reason, strength)

        executor = self.trade_executor
        if executor is None or self.is_backtest:
            return

        suspicious = bool(getattr(self, "_last_signal_suspicious", False))
        # 父类传入的 signal_type 始终为 BUY/SELL；「疑似」只在文案与 _last_signal_suspicious
        side = "SELL" if str(signal_type).upper() == "SELL" else "BUY"

        sig = TradeSignal(
            symbol=self.symbol,
            stock_name=getattr(self, "stock_name", self.symbol),
            side=side,
            price=float(price),
            ts=ts,
            reason=str(reason or ""),
            strength=strength,
            suspicious=suspicious,
        )
        try:
            executor.handle_signal(sig)
        except Exception:
            logger.exception("[%s] 自动交易执行异常（不影响监控主循环）", self.symbol)


class QmtAutoManagerV5(MonitorManagerV5):
    """V5 监控管理器 + QMT 执行器。"""

    monitor_class = QmtAutoMonitorV5
    monitor_label = "V5+QMT自动交易"

    def __init__(
        self,
        symbols,
        trade_config: Optional[QmtTradeConfig] = None,
        trade_executor: Optional[SignalExecutor] = None,
        **kwargs,
    ):
        self.trade_config = trade_config or QmtTradeConfig()
        self.trade_executor = trade_executor or SignalExecutor(self.trade_config)
        # 注入到 monitor 类，供各实例共享
        QmtAutoMonitorV5.trade_executor = self.trade_executor
        super().__init__(symbols, **kwargs)

    def start(self):
        mode = "DRY_RUN" if self.trade_config.dry_run else "LIVE"
        logging.info("=" * 60)
        logging.info("启动 %s | 模式=%s | account=%s", self.monitor_label, mode, self.trade_config.account_id)
        logging.info("=" * 60)
        if not self.trade_executor.start():
            logging.error("交易通道连接失败；监控仍可运行，但不会下单")
        try:
            super().start()
        finally:
            self.trade_executor.close()
