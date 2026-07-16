"""
纸面回测：用 V5 历史信号驱动 DryRun 账户，看 10 万本金最终收益。

PyCharm：可直接 Run 本文件。
命令行：
  conda activate trading
  python -m execution.t_trade_qmt.demo_paper_backtest
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
_ROOT = _PKG_DIR.parents[1]
sys.path[:] = [p for p in sys.path if Path(p).resolve() != _PKG_DIR]
if str(_ROOT) in sys.path:
    sys.path.remove(str(_ROOT))
sys.path.insert(0, str(_ROOT))

from alerting.t_trade_alert_v5 import MonitorManagerV5, TMonitorConfigV5
from execution.t_trade_qmt.broker import DryRunBroker
from execution.t_trade_qmt.trade_config import QmtTradeConfig
from execution.t_trade_qmt.executor import SignalExecutor, TradeSignal
from execution.t_trade_qmt.symbols import to_qmt_code

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def _signal_ts_key(ts):
    return ts


def run_paper_backtest(
    symbols: list[str],
    backtest_start: str,
    backtest_end: str,
    initial_cash: float = 100_000.0,
    order_volume: int = 100,
):
    manager = MonitorManagerV5(
        symbols=symbols,
        is_backtest=True,
        backtest_start=backtest_start,
        backtest_end=backtest_end,
        enable_visualization=False,
    )
    manager.start()

    events = []
    last_prices = {}
    signal_count = 0
    for symbol, mon in manager._monitors.items():
        signal_count += len(mon.triggered_signals)
        qmt_code = to_qmt_code(symbol)
        df = getattr(mon, "backtest_kline_data", None)
        if df is not None and len(df) > 0:
            last_prices[qmt_code] = float(df["close"].iloc[-1])
        for s in mon.triggered_signals:
            events.append(
                {
                    "symbol": symbol,
                    "stock_name": getattr(mon, "stock_name", symbol),
                    "side": s["type"],
                    "price": float(s["price"]),
                    "ts": s["time"],
                    "reason": s.get("reason", ""),
                    "strength": s.get("strength"),
                }
            )

    events.sort(key=lambda e: _signal_ts_key(e["ts"]))
    logging.info("V5 触发信号合计 %s 条，按时间回放纸面成交...", signal_count)

    cfg = QmtTradeConfig(
        dry_run=True,
        initial_cash=initial_cash,
        paper_enforce_t1=True,
        order_volume=order_volume,
        skip_suspicious=False,
        min_same_side_interval_sec=0,
        max_orders_per_day=10_000,
        max_orders_per_symbol_per_day=10_000,
        buy_slippage_pct=0.0,
        sell_slippage_pct=0.0,
    )
    broker = DryRunBroker(initial_cash=initial_cash, enforce_t1=True)
    ex = SignalExecutor(cfg, broker=broker)
    assert ex.start()

    accepted = 0
    rejected = 0
    for e in events:
        result = ex.handle_signal(
            TradeSignal(
                symbol=e["symbol"],
                stock_name=e["stock_name"],
                side=e["side"],
                price=e["price"],
                ts=e["ts"],
                reason=e["reason"],
                strength=e["strength"],
                suspicious=False,
            )
        )
        if result.ok:
            accepted += 1
        else:
            rejected += 1
            logging.info(
                "跳过 %s %s %s @%.2f: %s",
                e["ts"],
                e["symbol"],
                e["side"],
                e["price"],
                result.message,
            )

    summary = broker.summary(last_prices)
    ex.close()

    print("\n" + "=" * 64)
    print("V5 信号纸面回测结果（不依赖 QMT）")
    print("=" * 64)
    print(f"区间: {backtest_start} ~ {backtest_end}")
    print(f"标的: {symbols}")
    print(f"V5信号: {signal_count} | 成交: {accepted} | 拒绝: {rejected}")
    print(f"本金: {summary['initial_cash']:.2f}")
    print(f"期末现金: {summary['cash']:.2f}")
    print(f"期末权益: {summary['equity']:.2f}")
    print(f"收益率: {summary['return_pct']:.2f}%")
    print(f"买/卖笔数: {summary['buys']}/{summary['sells']}")
    print(f"残留持仓: {summary['positions'] or '{}'}")
    print("=" * 64)
    print("说明: 空仓时遇到 SELL 会被拒绝；A股 T+1 当日买入不可卖。")
    print("这是历史回测纸面模拟，不是实时监控，也不是 QMT 仿真盘。")
    return summary


def main():
    symbols = ["603178"]
    backtest_start = "2026-07-08 09:30"
    backtest_end = "2026-07-15 15:00"
    TMonitorConfigV5.BACKTEST_DATA_SOURCE = "akshare"
    run_paper_backtest(
        symbols=symbols,
        backtest_start=backtest_start,
        backtest_end=backtest_end,
        initial_cash=100_000.0,
        order_volume=100,
    )


if __name__ == "__main__":
    main()
