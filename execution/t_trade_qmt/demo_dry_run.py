"""
独立 Demo：不启动完整监控，只验证「信号 → 风控 → DryRun/QMT」闭环。

PyCharm：可直接 Run 本文件。
命令行：
  conda activate trading
  python -m execution.t_trade_qmt.demo_dry_run
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
_ROOT = _PKG_DIR.parents[1]
sys.path[:] = [p for p in sys.path if Path(p).resolve() != _PKG_DIR]
if str(_ROOT) in sys.path:
    sys.path.remove(str(_ROOT))
sys.path.insert(0, str(_ROOT))

from execution.t_trade_qmt.trade_config import QmtTradeConfig
from execution.t_trade_qmt.executor import SignalExecutor, TradeSignal

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main():
    cfg = QmtTradeConfig(
        dry_run=True,  # 默认模拟；改 False 才走真实 QMT
        initial_cash=100_000.0,
        order_volume=100,
        max_orders_per_day=10,
        skip_suspicious=True,
        min_same_side_interval_sec=120,
    )
    ex = SignalExecutor(cfg)
    assert ex.start(), "交易通道连接失败"

    now = datetime.now()
    samples = [
        TradeSignal("600000", "浦发银行", "BUY", 10.50, now, "demo急杀衰竭", 80, False),
        TradeSignal("600000", "浦发银行", "SELL", 10.62, now, "demo高潮衰竭", 78, False),
        TradeSignal("600000", "浦发银行", "BUY", 10.55, now, "疑似信号应被跳过", 70, True),
        TradeSignal("600000", "浦发银行", "BUY", 10.56, now, "同向防抖应被拒绝", 72, False),
    ]

    print("-" * 60)
    for i, sig in enumerate(samples, 1):
        result = ex.handle_signal(sig)
        print(
            f"[{i}] {sig.side:4s} suspicious={sig.suspicious} "
            f"-> ok={result.ok} order_id={result.order_id} | {result.message}"
        )
    print("-" * 60)
    print(f"模拟资金余额: {ex.broker.query_cash()}")
    print(f"模拟持仓 600000.SH: {ex.broker.query_position_volume('600000.SH')}")
    if hasattr(ex.broker, "summary"):
        print(f"账户摘要: {ex.broker.summary()}")
    ex.close()
    print("demo 完成（这是链路冒烟，不是收益回测）。")
    print("收益回测请跑: python -m execution.t_trade_qmt.demo_paper_backtest")
    print("文档: docs/t_trade_qmt_auto_trade.md")


if __name__ == "__main__":
    main()
