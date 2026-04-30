"""
1分钟K线趋势检测器。

用途：
- 给不同版本的做T监控器提供通用趋势状态判断。
- 只使用截至当前K线的历史数据，不引入未来视角。
- 当前阶段仅输出趋势拐点，暂不参与买卖信号决策。
"""

from dataclasses import dataclass
from enum import Enum
import math

import pandas as pd


class TrendDirection(Enum):
    """趋势方向。"""

    UP = "UP"
    DOWN = "DOWN"
    RANGE = "RANGE"
    UNKNOWN = "UNKNOWN"


@dataclass
class TrendSnapshot:
    """某一分钟结束后的趋势快照。"""

    direction: TrendDirection
    score: float
    confidence: float
    reason: str
    metrics: dict


@dataclass
class TrendTurnPoint:
    """趋势状态发生切换时输出的事件。"""

    previous: TrendDirection
    current: TrendDirection
    timestamp: object
    price: float
    score: float
    confidence: float
    reason: str
    metrics: dict


class OneMinuteTrendDetector:
    """
    面向短线做T的1分钟趋势检测器。

    设计取向：
    - 线性回归斜率判断方向，R²判断趋势是否顺滑。
    - EMA20/EMA60结构判断短线强弱。
    - 日内VWAP位置只作为轻量确认，不主导跨日趋势。
    """

    SHORT_WINDOW = 60       # 约1小时
    MID_WINDOW = 180        # 约3小时
    LONG_WINDOW = 480       # 约2个交易日
    MIN_BARS = 80

    # 窗口累计涨跌幅达到这些阈值，才认为该窗口有明确方向。
    SHORT_TREND_THRESHOLD = 0.012
    MID_TREND_THRESHOLD = 0.025
    LONG_TREND_THRESHOLD = 0.045

    UP_SCORE_THRESHOLD = 0.38
    DOWN_SCORE_THRESHOLD = -0.38
    MIN_TREND_CONFIDENCE = 0.52
    MIN_TURN_BARS = 10

    def __init__(self):
        self.last_snapshot = None
        self.last_turn_index = None
        self.last_evaluated_ts = None

    def update(self, df_1m):
        """
        更新趋势状态；若状态发生有效切换，返回TrendTurnPoint，否则返回None。
        """
        snapshot = self.detect(df_1m)
        if snapshot.direction == TrendDirection.UNKNOWN:
            return None

        latest = df_1m.iloc[-1]
        ts = latest["datetime"]
        if self.last_evaluated_ts == ts:
            return None
        self.last_evaluated_ts = ts

        current_index = len(df_1m) - 1
        previous_snapshot = self.last_snapshot

        if previous_snapshot is None:
            self.last_snapshot = snapshot
            return None

        previous_direction = previous_snapshot.direction
        current_direction = snapshot.direction
        if current_direction == previous_direction:
            self.last_snapshot = snapshot
            return None

        if current_direction in (TrendDirection.UP, TrendDirection.DOWN):
            if snapshot.confidence < self.MIN_TREND_CONFIDENCE:
                return None

        if self.last_turn_index is not None:
            if current_index - self.last_turn_index < self.MIN_TURN_BARS:
                return None

        self.last_turn_index = current_index
        self.last_snapshot = snapshot
        return TrendTurnPoint(
            previous=previous_direction,
            current=current_direction,
            timestamp=ts,
            price=float(latest["close"]),
            score=snapshot.score,
            confidence=snapshot.confidence,
            reason=snapshot.reason,
            metrics=snapshot.metrics,
        )

    def detect(self, df_1m):
        """根据当前可见的1分钟K线判断趋势状态。"""
        if df_1m is None or len(df_1m) < self.MIN_BARS:
            return TrendSnapshot(
                direction=TrendDirection.UNKNOWN,
                score=0.0,
                confidence=0.0,
                reason="数据不足",
                metrics={},
            )

        df = df_1m.copy()
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        if "vol" in df.columns:
            df["vol"] = pd.to_numeric(df["vol"], errors="coerce").fillna(0)
        else:
            df["vol"] = 0
        df = df.dropna(subset=["close"])
        if len(df) < self.MIN_BARS:
            return TrendSnapshot(
                direction=TrendDirection.UNKNOWN,
                score=0.0,
                confidence=0.0,
                reason="有效价格数据不足",
                metrics={},
            )

        close = df["close"]
        current_price = float(close.iloc[-1])

        short_reg = self._regression_metrics(close, self.SHORT_WINDOW)
        mid_reg = self._regression_metrics(close, self.MID_WINDOW)
        long_reg = self._regression_metrics(close, self.LONG_WINDOW)
        ema_metrics = self._ema_metrics(close)
        vwap_metrics = self._vwap_metrics(df)

        score = 0.0
        total_weight = 0.0

        score += self._window_score(short_reg, self.SHORT_TREND_THRESHOLD) * 0.30
        total_weight += 0.30

        if mid_reg:
            score += self._window_score(mid_reg, self.MID_TREND_THRESHOLD) * 0.35
            total_weight += 0.35

        if long_reg:
            score += self._window_score(long_reg, self.LONG_TREND_THRESHOLD) * 0.20
            total_weight += 0.20

        ema_score = self._ema_score(ema_metrics)
        score += ema_score * 0.25
        total_weight += 0.25

        vwap_score = self._vwap_score(vwap_metrics)
        score += vwap_score * 0.10
        total_weight += 0.10

        normalized_score = score / total_weight if total_weight else 0.0
        confidence = self._confidence(normalized_score, short_reg, mid_reg, long_reg, ema_score)
        direction = self._direction(normalized_score, confidence)

        metrics = {
            "price": round(current_price, 3),
            "score": round(normalized_score, 3),
            "confidence": round(confidence, 3),
            "short_ret": self._safe_round(short_reg.get("ret") if short_reg else None),
            "short_r2": self._safe_round(short_reg.get("r2") if short_reg else None),
            "mid_ret": self._safe_round(mid_reg.get("ret") if mid_reg else None),
            "mid_r2": self._safe_round(mid_reg.get("r2") if mid_reg else None),
            "long_ret": self._safe_round(long_reg.get("ret") if long_reg else None),
            "long_r2": self._safe_round(long_reg.get("r2") if long_reg else None),
            "ema20": self._safe_round(ema_metrics.get("ema20")),
            "ema60": self._safe_round(ema_metrics.get("ema60")),
            "ema60_slope": self._safe_round(ema_metrics.get("ema60_slope")),
            "vwap": self._safe_round(vwap_metrics.get("vwap")),
        }

        return TrendSnapshot(
            direction=direction,
            score=round(normalized_score, 3),
            confidence=round(confidence, 3),
            reason=self._reason(direction, metrics),
            metrics=metrics,
        )

    @classmethod
    def _regression_metrics(cls, close, window):
        if len(close) < window:
            return None

        values = close.iloc[-window:].astype(float).tolist()
        if len(values) < 2 or min(values) <= 0:
            return None

        y = [math.log(v) for v in values]
        n = len(y)
        x_mean = (n - 1) / 2
        y_mean = sum(y) / n

        denominator = sum((idx - x_mean) ** 2 for idx in range(n))
        if denominator == 0:
            return None

        slope = sum((idx - x_mean) * (val - y_mean) for idx, val in enumerate(y)) / denominator
        intercept = y_mean - slope * x_mean
        fitted = [intercept + slope * idx for idx in range(n)]

        ss_tot = sum((val - y_mean) ** 2 for val in y)
        ss_res = sum((val - fit) ** 2 for val, fit in zip(y, fitted))
        r2 = 0.0 if ss_tot == 0 else max(0.0, min(1.0, 1 - ss_res / ss_tot))

        total_return = math.exp(slope * (n - 1)) - 1
        actual_return = values[-1] / values[0] - 1
        return {
            "slope": slope,
            "ret": total_return,
            "actual_ret": actual_return,
            "r2": r2,
        }

    @staticmethod
    def _ema_metrics(close):
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema60 = close.ewm(span=60, adjust=False).mean()
        slope_window = min(30, len(ema60) - 1)
        if slope_window <= 0:
            ema60_slope = 0.0
        else:
            ema60_slope = float(ema60.iloc[-1] / ema60.iloc[-1 - slope_window] - 1)

        return {
            "close": float(close.iloc[-1]),
            "ema20": float(ema20.iloc[-1]),
            "ema60": float(ema60.iloc[-1]),
            "ema60_slope": ema60_slope,
        }

    @staticmethod
    def _vwap_metrics(df):
        latest_ts = df["datetime"].iloc[-1]
        latest_date = latest_ts.date() if hasattr(latest_ts, "date") else latest_ts
        today_df = df[df["datetime"].apply(lambda x: (x.date() if hasattr(x, "date") else x) == latest_date)]
        if today_df.empty:
            return {"vwap": None, "close": float(df["close"].iloc[-1])}

        volume = today_df["vol"].clip(lower=0)
        volume_sum = float(volume.sum())
        if volume_sum <= 0:
            return {"vwap": None, "close": float(today_df["close"].iloc[-1])}

        vwap = float((today_df["close"] * volume).sum() / volume_sum)
        return {
            "vwap": vwap,
            "close": float(today_df["close"].iloc[-1]),
        }

    @staticmethod
    def _window_score(regression_metrics, threshold):
        if not regression_metrics:
            return 0.0

        ret = regression_metrics["ret"]
        r2 = regression_metrics["r2"]
        raw = max(-1.0, min(1.0, ret / threshold))
        quality = 0.35 + 0.65 * r2
        return raw * quality

    @staticmethod
    def _ema_score(metrics):
        close = metrics["close"]
        ema20 = metrics["ema20"]
        ema60 = metrics["ema60"]
        ema60_slope = metrics["ema60_slope"]

        if close > ema20 > ema60 and ema60_slope > 0:
            return 1.0
        if close < ema20 < ema60 and ema60_slope < 0:
            return -1.0
        if close > ema60 and ema60_slope >= 0:
            return 0.45
        if close < ema60 and ema60_slope <= 0:
            return -0.45
        return 0.0

    @staticmethod
    def _vwap_score(metrics):
        vwap = metrics.get("vwap")
        close = metrics.get("close")
        if not vwap or not close:
            return 0.0

        distance = close / vwap - 1
        if distance > 0.004:
            return 0.5
        if distance < -0.004:
            return -0.5
        return 0.0

    @classmethod
    def _confidence(cls, score, short_reg, mid_reg, long_reg, ema_score):
        r2_values = []
        for reg in (short_reg, mid_reg, long_reg):
            if reg:
                r2_values.append(reg["r2"])

        avg_r2 = sum(r2_values) / len(r2_values) if r2_values else 0.0
        score_strength = min(1.0, abs(score) / 0.75)
        ema_alignment = min(1.0, abs(ema_score))
        confidence = 0.45 * score_strength + 0.35 * avg_r2 + 0.20 * ema_alignment
        return max(0.0, min(1.0, confidence))

    @classmethod
    def _direction(cls, score, confidence):
        if score >= cls.UP_SCORE_THRESHOLD and confidence >= cls.MIN_TREND_CONFIDENCE:
            return TrendDirection.UP
        if score <= cls.DOWN_SCORE_THRESHOLD and confidence >= cls.MIN_TREND_CONFIDENCE:
            return TrendDirection.DOWN
        return TrendDirection.RANGE

    @staticmethod
    def _reason(direction, metrics):
        direction_text = {
            TrendDirection.UP: "上涨趋势",
            TrendDirection.DOWN: "下跌趋势",
            TrendDirection.RANGE: "震荡/趋势不明",
            TrendDirection.UNKNOWN: "未知",
        }[direction]

        return (
            f"{direction_text} | "
            f"score:{metrics.get('score')} conf:{metrics.get('confidence')} "
            f"60m:{metrics.get('short_ret')} r2:{metrics.get('short_r2')} "
            f"180m:{metrics.get('mid_ret')} r2:{metrics.get('mid_r2')} "
            f"EMA60斜率:{metrics.get('ema60_slope')}"
        )

    @staticmethod
    def _safe_round(value, digits=4):
        if value is None:
            return None
        try:
            return round(float(value), digits)
        except Exception:
            return None
