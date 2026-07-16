"""V5 信号 → 风控 → QMT/DryRun 下单。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from .broker import BaseBroker, OrderResult, create_broker
from .trade_config import QmtTradeConfig
from .risk import RiskGate
from .symbols import to_qmt_code, to_symbol6

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    symbol: str
    stock_name: str
    side: str  # BUY / SELL
    price: float
    ts: Any
    reason: str = ""
    strength: Optional[float] = None
    suspicious: bool = False


class SignalExecutor:
    def __init__(self, cfg: Optional[QmtTradeConfig] = None, broker: Optional[BaseBroker] = None):
        self.cfg = cfg or QmtTradeConfig()
        self.broker = broker or create_broker(self.cfg)
        self.risk = RiskGate(self.cfg)
        self._connected = False

    def start(self) -> bool:
        self._connected = bool(self.broker.connect())
        return self._connected

    def handle_signal(self, sig: TradeSignal) -> OrderResult:
        if not self._connected:
            return OrderResult(False, -1, "executor 未 start/连接失败")

        symbol6 = to_symbol6(sig.symbol)
        try:
            qmt_code = to_qmt_code(symbol6)
        except ValueError as e:
            return OrderResult(False, -1, str(e))

        side = sig.side.upper()
        volume = self.cfg.volume_for(symbol6)
        price = self._limit_price(side, float(sig.price))

        ok, msg = self.risk.check(
            symbol6=symbol6,
            side=side,
            volume=volume,
            price=price,
            suspicious=bool(sig.suspicious),
        )
        if not ok:
            logger.info("[Executor] 风控拒绝 %s %s: %s", symbol6, side, msg)
            return OrderResult(False, -1, msg, dry_run=self.cfg.dry_run)

        if side == "SELL":
            hold = self.broker.query_position_volume(qmt_code)
            if hold < volume:
                # 可卖不足时降到可卖整数手；不足一手则拒
                volume = (hold // 100) * 100
                if volume <= 0:
                    return OrderResult(False, -1, f"可卖不足 hold={hold}", dry_run=self.cfg.dry_run)

        if side == "BUY" and self.cfg.max_position_per_symbol > 0:
            total_fn = getattr(self.broker, "query_position_total", None)
            hold = int(total_fn(qmt_code)) if callable(total_fn) else self.broker.query_position_volume(qmt_code)
            if hold + volume > self.cfg.max_position_per_symbol:
                return OrderResult(
                    False,
                    -1,
                    f"超单票仓位上限 hold={hold} +{volume} > {self.cfg.max_position_per_symbol}",
                    dry_run=self.cfg.dry_run,
                )

        trade_date = None
        if hasattr(sig.ts, "date"):
            trade_date = sig.ts.date()
        elif isinstance(sig.ts, datetime):
            trade_date = sig.ts.date()

        remark = f"v5:{side}:{symbol6}"
        result = self.broker.order_limit(
            qmt_code=qmt_code,
            side=side,
            volume=volume,
            price=price,
            strategy=self.cfg.strategy_name,
            remark=remark,
            trade_date=trade_date,
        )
        if result.ok:
            self.risk.record(symbol6, side)
            logger.warning(
                "[Executor] 已下单 %s %s %s vol=%s px=%.3f order_id=%s dry_run=%s",
                sig.stock_name,
                qmt_code,
                side,
                volume,
                price,
                result.order_id,
                result.dry_run or self.cfg.dry_run,
            )
        else:
            logger.error("[Executor] 下单失败 %s %s: %s", qmt_code, side, result.message)
        return result

    def _limit_price(self, side: str, signal_price: float) -> float:
        if side == "BUY":
            px = signal_price * (1.0 + self.cfg.buy_slippage_pct)
        else:
            px = signal_price * (1.0 - self.cfg.sell_slippage_pct)
        return round(px, 2)

    def close(self) -> None:
        self.broker.close()
        self._connected = False
