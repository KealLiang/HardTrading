"""自动交易配置（与 V5 监控配置解耦）。

注意：不要命名为 config.py，否则 PyCharm 直接运行本目录脚本时会
遮蔽项目根目录的 config/ 包（config.holder）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class QmtTradeConfig:
    # --- QMT 连接 ---
    userdata_path: str = r"D:\迅投极速交易终端 睿智融科版\userdata_mini"
    session_id: int = 12051
    account_id: str = "1000000365"
    # 将 QMT 自带的 site-packages 加入 sys.path（若已 pip 安装 xtquant 可留空）
    xtquant_site_packages: str = ""

    # --- 安全开关 ---
    dry_run: bool = True  # True：只记账不下真单
    enable_buy: bool = True
    enable_sell: bool = True
    skip_suspicious: bool = True  # 跳过文案带「疑似」的信号

    # --- 纸面账户（仅 dry_run）---
    initial_cash: float = 100_000.0
    paper_enforce_t1: bool = True  # 当日买入次日才可卖

    # --- 下单默认 ---
    order_volume: int = 100  # A 股最小申报单位常见为 100
    strategy_name: str = "t_trade_v5_auto"
    # 限价相对信号价的滑点（买入上浮 / 卖出下浮），提高成交概率
    buy_slippage_pct: float = 0.002
    sell_slippage_pct: float = 0.002

    # --- 简易风控 ---
    max_orders_per_symbol_per_day: int = 4
    max_orders_per_day: int = 20
    # 同向信号最短间隔（秒），防抖
    min_same_side_interval_sec: int = 120
    # 单票最大持仓（股）；0 表示不限制
    max_position_per_symbol: int = 0

    # 可选：按代码覆盖下单量，如 {"600000": 200}
    volume_overrides: Dict[str, int] = field(default_factory=dict)

    def volume_for(self, symbol6: str) -> int:
        return int(self.volume_overrides.get(symbol6, self.order_volume))
