"""
龙头单股形态筛选（条件1 趋势龙 / 条件2 二波龙）。

仅负责 md 文档中「形态条件（二选一）」部分；连板门槛、超短涨幅上限等由调用方处理。

形态模式通过 mode 参数切换；各模式条件1 阈值独立配置，互不影响：
- head_tail：窗口首尾收盘涨幅下限
- bottom_to_high：窗口内低点→高点收盘涨幅区间
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from analysis.helper.ladder_chart_helpers import (
    _resolve_df_end_iloc_pos,
    get_stock_data_df,
    is_leader_second_wave_long_ok,
    is_ma_trend_rising,
)
from utils.date_util import get_n_trading_days_before

# (主板, 非主板)
MarketPair = Tuple[float, float]
# ((主板 min, max), (非主板 min, max))
BottomToHighRangePair = Tuple[Tuple[float, float], Tuple[float, float]]

# ---------------------------------------------------------------------------
# 形态模式
# ---------------------------------------------------------------------------
LEADER_MORPHOLOGY_MODE_HEAD_TAIL = "head_tail"
LEADER_MORPHOLOGY_MODE_BOTTOM_TO_HIGH = "bottom_to_high"

SUPPORTED_LEADER_MORPHOLOGY_MODES = (
    LEADER_MORPHOLOGY_MODE_HEAD_TAIL,
    LEADER_MORPHOLOGY_MODE_BOTTOM_TO_HIGH,
)

_WINDOW_MAX_SCAN_BACK_ROWS = 200


@dataclass(frozen=True)
class LeaderMorphologyConfig:
    """形态筛选阈值（由 ladder_chart 全局常量注入，避免循环依赖）。"""

    period_days_long: int
    period_days_very_long: int
    head_tail_min_change: MarketPair
    bottom_to_high_change_range: BottomToHighRangePair
    second_wave_min_range: MarketPair
    # bottom_to_high 专用：普通龙头高危过滤（period_days=0 或 max_change=None 表示关闭）
    bottom_to_high_high_risk_period_days: int = 0
    bottom_to_high_high_risk_max_change: Optional[float] = None


def build_leader_morphology_config(
    *,
    period_days_long: int,
    period_days_very_long: int,
    head_tail_min_change: MarketPair,
    bottom_to_high_change_range: BottomToHighRangePair,
    second_wave_min_range: MarketPair,
    bottom_to_high_high_risk_period_days: int = 0,
    bottom_to_high_high_risk_max_change: Optional[float] = None,
) -> LeaderMorphologyConfig:
    return LeaderMorphologyConfig(
        period_days_long=period_days_long,
        period_days_very_long=period_days_very_long,
        head_tail_min_change=head_tail_min_change,
        bottom_to_high_change_range=bottom_to_high_change_range,
        second_wave_min_range=second_wave_min_range,
        bottom_to_high_high_risk_period_days=bottom_to_high_high_risk_period_days,
        bottom_to_high_high_risk_max_change=bottom_to_high_high_risk_max_change,
    )


def clear_leader_morphology_cache() -> None:
    """清理本模块 lru_cache（每日复盘开始时调用）。"""
    calc_window_bottom_to_high_change.cache_clear()


def _market_pair_index(market_type: str) -> int:
    return 0 if market_type == "main" else 1


def _head_tail_min_change_threshold(market_type: str, config: LeaderMorphologyConfig) -> float:
    return config.head_tail_min_change[_market_pair_index(market_type)]


def _bottom_to_high_change_range(
    market_type: str, config: LeaderMorphologyConfig
) -> Tuple[float, float]:
    return config.bottom_to_high_change_range[_market_pair_index(market_type)]


def _second_wave_min_range(market_type: str, config: LeaderMorphologyConfig) -> float:
    return config.second_wave_min_range[_market_pair_index(market_type)]


def _change_in_closed_range(value: Optional[float], lo: float, hi: float) -> bool:
    if value is None:
        return False
    return lo <= value <= hi


def _calc_head_tail_period_change(
    stock_code: str, start_yyyymmdd: str, end_yyyymmdd: str
) -> Optional[float]:
    """延迟导入，避免与 ladder_chart 循环依赖。"""
    from analysis.ladder_chart import calculate_stock_period_change

    return calculate_stock_period_change(stock_code, start_yyyymmdd, end_yyyymmdd)


def is_bottom_to_high_high_risk_leader(
    stock_code: str,
    end_date_yyyymmdd: Optional[str],
    config: LeaderMorphologyConfig,
) -> bool:
    """
    bottom_to_high 专用：近 N 日首尾涨幅 > 阈值 → 高危，不可作普通龙头。

    仅用于普通龙头名额池；大龙股从完整候选池识别，不调用本函数。
    """
    if (
        not stock_code
        or not end_date_yyyymmdd
        or config.bottom_to_high_high_risk_period_days <= 0
        or config.bottom_to_high_high_risk_max_change is None
    ):
        return False

    start_date = get_n_trading_days_before(
        end_date_yyyymmdd, config.bottom_to_high_high_risk_period_days
    )
    if not start_date:
        return False
    start_yyyymmdd = start_date.replace("-", "")
    change = _calc_head_tail_period_change(stock_code, start_yyyymmdd, end_date_yyyymmdd)
    if change is None:
        return False
    return change > config.bottom_to_high_high_risk_max_change


def pool_excluding_bottom_to_high_high_risk(qualified_df, end_date_yyyymmdd, config):
    """从候选 DataFrame 中剔除 bottom_to_high 高危股（须含 stock_code 列）。"""
    if qualified_df.empty or "stock_code" not in qualified_df.columns:
        return qualified_df
    mask = ~qualified_df["stock_code"].apply(
        lambda code: is_bottom_to_high_high_risk_leader(code, end_date_yyyymmdd, config)
    )
    return qualified_df.loc[mask].copy()


def _row_valid_close(row) -> bool:
    """有效收盘：有限正数（停牌/缺省视为无效）。"""
    try:
        v = row["收盘"]
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return False
        fv = float(v)
        return fv > 0 and np.isfinite(fv)
    except (KeyError, TypeError, ValueError):
        return False


def _collect_window_closes(
    df,
    end_iloc: int,
    window_days: int,
) -> List[Tuple[int, float]]:
    """从截止日向前收集 window_days 根有效收盘，返回 [(iloc, close), ...]，索引 0 为最新。"""
    entries: List[Tuple[int, float]] = []
    p = end_iloc
    scanned = 0
    while (
        p >= 0
        and len(entries) < int(window_days)
        and scanned < int(window_days) + _WINDOW_MAX_SCAN_BACK_ROWS
    ):
        row = df.iloc[p]
        if _row_valid_close(row):
            entries.append((p, float(row["收盘"])))
        p -= 1
        scanned += 1
    return entries


@lru_cache(maxsize=8000)
def calc_window_bottom_to_high_change(
    stock_code: str,
    end_date_yyyymmdd: str,
    window_days: int,
) -> Optional[float]:
    """
    窗口内「低点→其后高点」收盘涨幅（%）。

    - 窗口：截止 end_date 向前 window_days 根有效 K 的收盘
    - 低点：窗口内最低收盘；同价取 iloc 最小（时间最早）
    - 高点：低点日之后（不含低点当日）窗口内最高收盘
    - 涨幅：(high - low) / low * 100
    """
    if not stock_code or not end_date_yyyymmdd or len(str(end_date_yyyymmdd)) != 8:
        return None
    if window_days <= 0:
        return None

    df = get_stock_data_df(stock_code)
    if df is None or df.empty:
        return None

    end_iloc = _resolve_df_end_iloc_pos(df, end_date_yyyymmdd)
    if end_iloc is None:
        return None

    window = _collect_window_closes(df, end_iloc, window_days)
    if len(window) < window_days:
        return None

    low_iloc, low_close = min(window, key=lambda x: (x[1], x[0]))
    after_low = [(iloc, close) for iloc, close in window if iloc > low_iloc]
    if not after_low:
        return None

    max_close = max(close for _, close in after_low)
    if low_close <= 0:
        return None

    return (max_close - low_close) / low_close * 100.0


def _check_condition1_head_tail(
    *,
    stock_code: str,
    market_type: str,
    long_period_change: float,
    end_date_yyyymmdd: str,
    config: LeaderMorphologyConfig,
) -> bool:
    """条件1 — 趋势龙：窗口首尾涨幅达下限 + 均线上升趋势。"""
    threshold = _head_tail_min_change_threshold(market_type, config)
    if long_period_change < threshold:
        return False
    return is_ma_trend_rising(stock_code, end_date_yyyymmdd)


def _check_condition1_bottom_to_high(
    *,
    stock_code: str,
    market_type: str,
    end_date_yyyymmdd: str,
    config: LeaderMorphologyConfig,
) -> bool:
    """条件1 — 趋势龙：低点→高点涨幅落在区间内 + 均线上升趋势。"""
    swing_change = calc_window_bottom_to_high_change(
        stock_code,
        end_date_yyyymmdd,
        config.period_days_long,
    )
    lo, hi = _bottom_to_high_change_range(market_type, config)
    if not _change_in_closed_range(swing_change, lo, hi):
        return False
    return is_ma_trend_rising(stock_code, end_date_yyyymmdd)


def _check_condition2_second_wave(
    *,
    stock_code: str,
    market_type: str,
    end_date_yyyymmdd: str,
    config: LeaderMorphologyConfig,
) -> bool:
    """条件2 — 二波/老牌（两种形态模式共用）。"""
    sw_min_range = _second_wave_min_range(market_type, config)
    return is_leader_second_wave_long_ok(
        stock_code,
        end_date_yyyymmdd,
        config.period_days_very_long,
        sw_min_range,
    )


def check_morphology_head_tail(
    *,
    stock_code: str,
    market_type: str,
    long_period_change: float,
    end_date_yyyymmdd: Optional[str],
    config: LeaderMorphologyConfig,
) -> bool:
    """head_tail 模式：条件1（首尾涨幅）| 条件2（二波）。"""
    if end_date_yyyymmdd is None:
        return False

    condition1 = _check_condition1_head_tail(
        stock_code=stock_code,
        market_type=market_type,
        long_period_change=long_period_change,
        end_date_yyyymmdd=end_date_yyyymmdd,
        config=config,
    )
    condition2 = _check_condition2_second_wave(
        stock_code=stock_code,
        market_type=market_type,
        end_date_yyyymmdd=end_date_yyyymmdd,
        config=config,
    )
    return condition1 or condition2


def check_morphology_bottom_to_high(
    *,
    stock_code: str,
    market_type: str,
    long_period_change: float,
    end_date_yyyymmdd: Optional[str],
    config: LeaderMorphologyConfig,
) -> bool:
    """bottom_to_high 模式：条件1（低点→高点涨幅区间）| 条件2（二波）。"""
    if end_date_yyyymmdd is None:
        return False

    condition1 = _check_condition1_bottom_to_high(
        stock_code=stock_code,
        market_type=market_type,
        end_date_yyyymmdd=end_date_yyyymmdd,
        config=config,
    )
    condition2 = _check_condition2_second_wave(
        stock_code=stock_code,
        market_type=market_type,
        end_date_yyyymmdd=end_date_yyyymmdd,
        config=config,
    )
    return condition1 or condition2


MorphologyChecker = Callable[..., bool]

_MORPHOLOGY_CHECKERS: Dict[str, MorphologyChecker] = {
    LEADER_MORPHOLOGY_MODE_HEAD_TAIL: check_morphology_head_tail,
    LEADER_MORPHOLOGY_MODE_BOTTOM_TO_HIGH: check_morphology_bottom_to_high,
}


def check_leader_morphology(
    *,
    stock_code: str,
    market_type: str,
    long_period_change: float,
    end_date_yyyymmdd: Optional[str],
    config: LeaderMorphologyConfig,
    mode: str = LEADER_MORPHOLOGY_MODE_HEAD_TAIL,
) -> bool:
    """
    统一入口：按 mode 调用对应形态策略。

    Args:
        stock_code: 股票代码
        market_type: 'main' 或 非主板
        long_period_change: 预计算的窗口首尾涨幅（%）；bottom_to_high 条件1 不使用
        end_date_yyyymmdd: 复盘截止日 YYYYMMDD
        config: 阈值配置（各模式独立字段）
        mode: head_tail | bottom_to_high
    """
    checker = _MORPHOLOGY_CHECKERS.get(mode)
    if checker is None:
        supported = ", ".join(sorted(_MORPHOLOGY_CHECKERS))
        raise ValueError(f"Unsupported leader morphology mode: {mode!r} (supported: {supported})")
    return checker(
        stock_code=stock_code,
        market_type=market_type,
        long_period_change=long_period_change,
        end_date_yyyymmdd=end_date_yyyymmdd,
        config=config,
    )
