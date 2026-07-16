"""
可插拔实盘入口：复用 V5 监控，额外挂上 QMT 执行器。

不修改 alerting/t_trade_alert_v5.py。
原飞书告警仍由父类 _trigger_signal 发送；本入口额外自动下单。

PyCharm：可直接 Run 本文件（已处理项目根路径）。
命令行：
  conda activate trading
  python -m execution.t_trade_qmt.run_with_v5

默认 dry_run=True（只模拟下单）。确认 QMT 已登录后再改 False。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# PyCharm 直接运行本文件时，须先把项目根放进 sys.path
_PKG_DIR = Path(__file__).resolve().parent
_ROOT = _PKG_DIR.parents[1]
sys.path[:] = [p for p in sys.path if Path(p).resolve() != _PKG_DIR]
if str(_ROOT) in sys.path:
    sys.path.remove(str(_ROOT))
sys.path.insert(0, str(_ROOT))

from execution.t_trade_qmt.auto_monitor import QmtAutoManagerV5
from execution.t_trade_qmt.trade_config import QmtTradeConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main():
    cfg = QmtTradeConfig(
        dry_run=True,
        order_volume=100,
        enable_buy=True,
        enable_sell=True,
        skip_suspicious=True,
        max_orders_per_symbol_per_day=4,
        max_orders_per_day=20,
        # --- 真机填写 ---
        # userdata_path=r"D:\迅投极速交易终端 睿智融科版\userdata_mini",
        # account_id="1000000365",
        # session_id=12051,
        # xtquant_site_packages=r"",  # 或 QMT 安装目录下 Lib/site-packages
    )

    # 与 v5 __main__ 类似：可用 watchlist，或显式 symbols
    manager = QmtAutoManagerV5(
        symbols=None,
        trade_config=cfg,
        is_backtest=False,
        symbols_file="alerting/watchlist.txt",
        reload_interval_sec=5,
        enable_visualization=False,
    )
    manager.start()


if __name__ == "__main__":
    main()
