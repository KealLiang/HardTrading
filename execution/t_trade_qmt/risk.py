"""下单前简易风控。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, Tuple

from .trade_config import QmtTradeConfig


@dataclass
class RiskState:
    day: date = field(default_factory=lambda: datetime.now().date())
    total_orders: int = 0
    per_symbol: Dict[str, int] = field(default_factory=dict)
    last_side_ts: Dict[Tuple[str, str], float] = field(default_factory=dict)

    def roll_day(self) -> None:
        today = datetime.now().date()
        if today != self.day:
            self.day = today
            self.total_orders = 0
            self.per_symbol.clear()
            self.last_side_ts.clear()


class RiskGate:
    def __init__(self, cfg: QmtTradeConfig):
        self.cfg = cfg
        self.state = RiskState()

    def check(
        self,
        symbol6: str,
        side: str,
        volume: int,
        price: float,
        suspicious: bool,
        now_ts: float | None = None,
    ) -> tuple[bool, str]:
        self.state.roll_day()
        cfg = self.cfg
        side_u = side.upper()
        now = now_ts if now_ts is not None else datetime.now().timestamp()

        if cfg.dry_run is False and volume <= 0:
            return False, "数量无效"
        if volume % 100 != 0:
            return False, f"数量须为100整数倍: {volume}"
        if price <= 0:
            return False, f"价格无效: {price}"

        if side_u == "BUY" and not cfg.enable_buy:
            return False, "买入已禁用"
        if side_u == "SELL" and not cfg.enable_sell:
            return False, "卖出已禁用"
        if suspicious and cfg.skip_suspicious:
            return False, "疑似信号已跳过"

        if self.state.total_orders >= cfg.max_orders_per_day:
            return False, f"日内总下单达上限 {cfg.max_orders_per_day}"
        sym_cnt = self.state.per_symbol.get(symbol6, 0)
        if sym_cnt >= cfg.max_orders_per_symbol_per_day:
            return False, f"{symbol6} 日内下单达上限 {cfg.max_orders_per_symbol_per_day}"

        key = (symbol6, side_u)
        last = self.state.last_side_ts.get(key)
        if last is not None and (now - last) < cfg.min_same_side_interval_sec:
            return False, f"同向防抖 {cfg.min_same_side_interval_sec}s"

        return True, "ok"

    def record(self, symbol6: str, side: str, now_ts: float | None = None) -> None:
        self.state.roll_day()
        now = now_ts if now_ts is not None else datetime.now().timestamp()
        self.state.total_orders += 1
        self.state.per_symbol[symbol6] = self.state.per_symbol.get(symbol6, 0) + 1
        self.state.last_side_ts[(symbol6, side.upper())] = now
