"""QMT 交易通道：真实 XtQuant + DryRun 纸面模拟。"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from .trade_config import QmtTradeConfig

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    ok: bool
    order_id: int = -1
    message: str = ""
    dry_run: bool = False


@dataclass
class TradeFill:
    ts: Any
    qmt_code: str
    side: str
    volume: int
    price: float
    cash_after: float
    remark: str = ""


class BaseBroker:
    def connect(self) -> bool:
        raise NotImplementedError

    def query_cash(self) -> Optional[float]:
        return None

    def query_position_volume(self, qmt_code: str) -> int:
        return 0

    def order_limit(
        self,
        qmt_code: str,
        side: str,
        volume: int,
        price: float,
        strategy: str,
        remark: str,
        trade_date: Optional[date] = None,
    ) -> OrderResult:
        raise NotImplementedError

    def close(self) -> None:
        pass


class DryRunBroker(BaseBroker):
    """
    无 QMT 时的纸面记账通道。

    - 支持自定义本金、成交日志、简易 T+1（当日买入次日才可卖）
    - 不连券商，不依赖 xtquant
    """

    def __init__(self, initial_cash: float = 100_000.0, enforce_t1: bool = True):
        self.initial_cash = float(initial_cash)
        self._cash = float(initial_cash)
        self._pos_total: Dict[str, int] = {}
        self._pos_available: Dict[str, int] = {}
        self._pending: Dict[str, List[Tuple[date, int]]] = {}
        self._seq = 900000
        self.enforce_t1 = enforce_t1
        self.trades: List[TradeFill] = []
        self._current_date: Optional[date] = None

    def connect(self) -> bool:
        logger.info(
            "[DryRunBroker] 已连接（纸面） initial_cash=%.2f T+1=%s",
            self.initial_cash,
            self.enforce_t1,
        )
        return True

    def query_cash(self) -> Optional[float]:
        return self._cash

    def query_position_volume(self, qmt_code: str) -> int:
        """可卖数量（T+1 下不含当日买入）。"""
        return int(self._pos_available.get(qmt_code, 0))

    def query_position_total(self, qmt_code: str) -> int:
        return int(self._pos_total.get(qmt_code, 0))

    def _as_date(self, trade_date: Optional[date]) -> date:
        if trade_date is None:
            return datetime.now().date()
        if isinstance(trade_date, datetime):
            return trade_date.date()
        return trade_date

    def _roll_to(self, d: date) -> None:
        if self._current_date is None:
            self._current_date = d
            return
        if d <= self._current_date:
            return
        self._current_date = d
        if not self.enforce_t1:
            return
        for code, pending in list(self._pending.items()):
            keep: List[Tuple[date, int]] = []
            unlocked = 0
            for buy_d, vol in pending:
                if buy_d < d:
                    unlocked += vol
                else:
                    keep.append((buy_d, vol))
            if unlocked:
                self._pos_available[code] = self._pos_available.get(code, 0) + unlocked
            self._pending[code] = keep

    def order_limit(
        self,
        qmt_code: str,
        side: str,
        volume: int,
        price: float,
        strategy: str,
        remark: str,
        trade_date: Optional[date] = None,
    ) -> OrderResult:
        d = self._as_date(trade_date)
        self._roll_to(d)
        self._seq += 1
        side_u = side.upper()
        vol = int(volume)
        px = float(price)

        if side_u == "BUY":
            cost = px * vol
            if cost > self._cash + 1e-6:
                return OrderResult(
                    False, -1, f"模拟资金不足 cash={self._cash:.2f} need={cost:.2f}", True
                )
            self._cash -= cost
            self._pos_total[qmt_code] = self._pos_total.get(qmt_code, 0) + vol
            if self.enforce_t1:
                self._pending.setdefault(qmt_code, []).append((d, vol))
            else:
                self._pos_available[qmt_code] = self._pos_available.get(qmt_code, 0) + vol
        else:
            avail = self._pos_available.get(qmt_code, 0)
            if vol > avail:
                return OrderResult(
                    False,
                    -1,
                    f"模拟可卖不足 avail={avail} total={self._pos_total.get(qmt_code, 0)}",
                    True,
                )
            self._pos_available[qmt_code] = avail - vol
            self._pos_total[qmt_code] = self._pos_total.get(qmt_code, 0) - vol
            self._cash += px * vol

        fill = TradeFill(
            ts=d,
            qmt_code=qmt_code,
            side=side_u,
            volume=vol,
            price=px,
            cash_after=self._cash,
            remark=remark or "",
        )
        self.trades.append(fill)
        msg = (
            f"[PAPER] {side_u} {qmt_code} vol={vol} px={px:.3f} "
            f"cash={self._cash:.2f} total={self._pos_total.get(qmt_code, 0)} "
            f"avail={self._pos_available.get(qmt_code, 0)} | {remark}"
        )
        logger.warning(msg)
        return OrderResult(True, self._seq, msg, True)

    def equity(self, last_prices: Optional[Dict[str, float]] = None) -> float:
        mv = 0.0
        prices = last_prices or {}
        for code, vol in self._pos_total.items():
            if vol <= 0:
                continue
            px = prices.get(code)
            if px is None:
                for t in reversed(self.trades):
                    if t.qmt_code == code:
                        px = t.price
                        break
            if px is None:
                continue
            mv += vol * float(px)
        return self._cash + mv

    def summary(self, last_prices: Optional[Dict[str, float]] = None) -> dict:
        eq = self.equity(last_prices)
        ret = (eq / self.initial_cash - 1.0) * 100.0 if self.initial_cash else 0.0
        buys = sum(1 for t in self.trades if t.side == "BUY")
        sells = sum(1 for t in self.trades if t.side == "SELL")
        return {
            "initial_cash": self.initial_cash,
            "cash": self._cash,
            "equity": eq,
            "return_pct": ret,
            "trades": len(self.trades),
            "buys": buys,
            "sells": sells,
            "positions": {k: v for k, v in self._pos_total.items() if v > 0},
        }


class QmtBroker(BaseBroker):
    """真实 MiniQMT / XtQuantTrader 封装。"""

    def __init__(self, cfg: QmtTradeConfig):
        self.cfg = cfg
        self._xt = None
        self._acc = None
        self._xtconstant = None

    def _ensure_xtquant_path(self) -> None:
        site = (self.cfg.xtquant_site_packages or "").strip()
        if site and site not in sys.path:
            sys.path.insert(0, site)

    def connect(self) -> bool:
        self._ensure_xtquant_path()
        try:
            from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
            from xtquant.xttype import StockAccount
            from xtquant import xtconstant
        except ImportError as e:
            logger.error(
                "无法导入 xtquant：%s。请安装/把 QMT 自带 site-packages 配到 "
                "xtquant_site_packages，或先用 dry_run=True。",
                e,
            )
            return False

        self._xtconstant = xtconstant

        class _Cb(XtQuantTraderCallback):
            def on_disconnected(self):
                logger.error("[QMT] disconnected")

            def on_stock_order(self, order):
                logger.info(
                    "[QMT] order %s %s status=%s id=%s",
                    order.account_id,
                    order.stock_code,
                    order.order_status,
                    order.order_id,
                )

            def on_stock_trade(self, trade):
                logger.info(
                    "[QMT] trade %s %s vol=%s px=%s",
                    trade.account_id,
                    trade.stock_code,
                    trade.traded_volume,
                    trade.traded_price,
                )

            def on_order_error(self, err):
                logger.error("[QMT] order_err id=%s %s %s", err.order_id, err.error_id, err.error_msg)

            def on_cancel_error(self, err):
                logger.error("[QMT] cancel_err id=%s %s %s", err.order_id, err.error_id, err.error_msg)

        xt = XtQuantTrader(self.cfg.userdata_path, self.cfg.session_id)
        xt.register_callback(_Cb())
        xt.start()
        ret = xt.connect()
        if ret != 0:
            logger.error("[QMT] connect failed ret=%s path=%s", ret, self.cfg.userdata_path)
            return False

        acc = StockAccount(self.cfg.account_id)
        sub = xt.subscribe(acc)
        if sub != 0:
            logger.error("[QMT] subscribe failed ret=%s account=%s", sub, self.cfg.account_id)
            return False

        self._xt = xt
        self._acc = acc
        logger.info("[QMT] 连接成功 account=%s", self.cfg.account_id)
        return True

    def query_cash(self) -> Optional[float]:
        if not self._xt:
            return None
        asset = self._xt.query_stock_asset(self._acc)
        return None if asset is None else float(getattr(asset, "cash", 0) or 0)

    def query_position_volume(self, qmt_code: str) -> int:
        if not self._xt:
            return 0
        pos = self._xt.query_stock_position(self._acc, qmt_code)
        if pos is None:
            return 0
        vol = getattr(pos, "can_use_volume", None)
        if vol is None:
            vol = getattr(pos, "volume", 0)
        return int(vol or 0)

    def order_limit(
        self,
        qmt_code: str,
        side: str,
        volume: int,
        price: float,
        strategy: str,
        remark: str,
        trade_date: Optional[date] = None,
    ) -> OrderResult:
        if not self._xt:
            return OrderResult(False, -1, "QMT 未连接")

        side_const = (
            self._xtconstant.STOCK_BUY
            if side.upper() == "BUY"
            else self._xtconstant.STOCK_SELL
        )
        order_id = self._xt.order_stock(
            self._acc,
            qmt_code,
            side_const,
            int(volume),
            self._xtconstant.FIX_PRICE,
            float(price),
            strategy,
            remark[:24] if remark else "",
        )
        if isinstance(order_id, int) and order_id > 0:
            return OrderResult(True, order_id, "submitted")
        return OrderResult(False, int(order_id) if order_id is not None else -1, "order_stock failed")

    def close(self) -> None:
        self._xt = None


def create_broker(cfg: QmtTradeConfig) -> BaseBroker:
    if cfg.dry_run:
        return DryRunBroker(
            initial_cash=cfg.initial_cash,
            enforce_t1=cfg.paper_enforce_t1,
        )
    return QmtBroker(cfg)
