"""回测行情数据源（与信号逻辑、绘图解耦，仅负责产出标准 OHLCV DataFrame）。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

import akshare as ak
import pandas as pd

BACKTEST_SOURCE_TDX = "tdx"
BACKTEST_SOURCE_AKSHARE = "akshare"

OHLCV_COLUMNS = ["datetime", "open", "high", "low", "close", "vol"]


class BacktestDataUnavailable(Exception):
    """通达信等数据源无法覆盖请求的回测区间。"""


@dataclass
class FetchMeta:
    source: str
    oldest: pd.Timestamp
    newest: pd.Timestamp
    total_bars: int
    warmup_bars: int
    active_bars: int
    active_start: pd.Timestamp
    fetched_oldest: Optional[pd.Timestamp] = None
    fetched_newest: Optional[pd.Timestamp] = None
    fetched_bars: Optional[int] = None
    replay_dates: Optional[list[date]] = field(default_factory=list)


def slice_backtest_range(
    df: pd.DataFrame,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
    warmup_bars: int,
) -> pd.DataFrame:
    """截取 warmup + 回测活跃区间，列与顺序固定。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    out = df.sort_values("datetime").reset_index(drop=True)
    warmup_df = out[out["datetime"] < start_dt].tail(warmup_bars)
    active_df = out[(out["datetime"] >= start_dt) & (out["datetime"] <= end_dt)]
    merged = pd.concat([warmup_df, active_df], ignore_index=True)
    return merged[OHLCV_COLUMNS]


def resolve_active_start_from_data(
    df: pd.DataFrame,
    end_dt: pd.Timestamp,
    retention_days: int,
) -> tuple[Optional[pd.Timestamp], list[date]]:
    """
    从通达信数据中识别最近 N 个有 K 线的交易日，返回回放起点。
    有 K 线即视为交易日，不依赖外部日历。
    """
    if df is None or df.empty:
        return None, []

    out = df.sort_values("datetime").reset_index(drop=True)
    out = out[out["datetime"] <= end_dt]
    if out.empty:
        return None, []

    trade_dates = sorted(out["datetime"].dt.date.unique())
    selected = (
        trade_dates[-retention_days:]
        if len(trade_dates) >= retention_days
        else trade_dates
    )
    if not selected:
        return None, []

    replay_start = out.loc[out["datetime"].dt.date == selected[0], "datetime"].iloc[0]
    return pd.Timestamp(replay_start), selected


def fetch_akshare_minute(
    full_symbol: str,
    start_time,
    end_time,
    warmup_bars: int,
    period: str = "1",
) -> tuple[pd.DataFrame, FetchMeta]:
    start_dt = pd.to_datetime(start_time)
    end_dt = pd.to_datetime(end_time)
    df = ak.stock_zh_a_minute(symbol=full_symbol, period=period, adjust="qfq")
    df["datetime"] = pd.to_datetime(df["day"])
    df = df.sort_values(by="datetime").reset_index(drop=True)
    df.rename(columns={"volume": "vol"}, inplace=True)
    sliced = slice_backtest_range(df, start_dt, end_dt, warmup_bars)
    active_bars = int((sliced["datetime"] >= start_dt).sum())
    meta = FetchMeta(
        source=BACKTEST_SOURCE_AKSHARE,
        oldest=pd.Timestamp(sliced["datetime"].iloc[0]) if len(sliced) else start_dt,
        newest=pd.Timestamp(sliced["datetime"].iloc[-1]) if len(sliced) else end_dt,
        total_bars=len(sliced),
        warmup_bars=int((sliced["datetime"] < start_dt).sum()),
        active_bars=active_bars,
        active_start=start_dt,
        fetched_oldest=pd.Timestamp(df["datetime"].iloc[0]) if len(df) else None,
        fetched_newest=pd.Timestamp(df["datetime"].iloc[-1]) if len(df) else None,
        fetched_bars=len(df),
    )
    return sliced, meta


def paginate_tdx_1m(
    api,
    market: int,
    code: str,
    category: int,
    process_raw: Callable,
    *,
    min_datetime: Optional[pd.Timestamp] = None,
    chunk_size: int = 800,
    max_chunks: int = 50,
) -> pd.DataFrame:
    """
    分页拉取通达信 1 分钟 K 线（start 为距最新 bar 的偏移，越大越旧）。
    返回按时间升序、去重后的 DataFrame。
    """
    parts = []
    for chunk_idx in range(max_chunks):
        start_offset = chunk_idx * chunk_size
        raw = api.get_security_bars(
            category=category,
            market=market,
            code=code,
            start=start_offset,
            count=chunk_size,
        )
        if not raw:
            break

        df_chunk = process_raw(raw)
        if df_chunk is None or df_chunk.empty:
            break

        parts.append(df_chunk)
        oldest = df_chunk["datetime"].min()
        if min_datetime is not None and oldest <= min_datetime:
            break
        if len(raw) < chunk_size:
            break

    if not parts:
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    full = pd.concat(parts, ignore_index=True)
    full = full.drop_duplicates(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
    return full[OHLCV_COLUMNS]


def fetch_tdx_minute(
    api,
    market: int,
    code: str,
    end_time,
    warmup_bars: int,
    category: int,
    process_raw: Callable,
    start_time=None,
    retention_days: Optional[int] = None,
    *,
    chunk_size: int = 800,
    max_chunks: int = 50,
) -> tuple[pd.DataFrame, FetchMeta]:
    """
    通达信 1 分钟线取数 + 统一切片（回测与实盘预热共用）。

    - 回测：传 start_time，按 [start_time, end_time] 活跃区间 + 前 warmup 根切片。
    - 实盘预热：传 retention_days，从拉取数据中识别最近 N 个有 K 线的交易日，
      再以该起点走同一套 slice_backtest_range。
    """
    end_dt = pd.to_datetime(end_time)
    replay_dates: list[date] = []

    if retention_days is not None:
        # 按 K 线根数从最新向前拉，不用日历定界
        fetch_bars = retention_days * 240 + warmup_bars + 60
        raw = api.get_security_bars(
            category=category,
            market=market,
            code=code,
            start=0,
            count=fetch_bars,
        )
        full = process_raw(raw) if raw else pd.DataFrame(columns=OHLCV_COLUMNS)
        if full is None or full.empty:
            raise BacktestDataUnavailable(f"{code} 未从通达信获取到任何 1 分钟 K 线")
        full = (
            full.drop_duplicates(subset=["datetime"])
            .sort_values("datetime")
            .reset_index(drop=True)
        )
        full = full[OHLCV_COLUMNS]

        start_dt, replay_dates = resolve_active_start_from_data(
            full, end_dt, retention_days
        )
        if start_dt is None:
            fetched_oldest = pd.Timestamp(full["datetime"].iloc[0])
            fetched_newest = pd.Timestamp(full["datetime"].iloc[-1])
            raise BacktestDataUnavailable(
                f"{code} 通达信拉取 {len(full)} 根 ({fetched_oldest} ~ {fetched_newest})，"
                f"截止 {end_dt} 无有效分钟线可供近 {retention_days} 日回放"
            )
        if len(replay_dates) < retention_days:
            logging.warning(
                f"{code} 通达信仅含 {len(replay_dates)} 个交易日（期望 {retention_days}），"
                f"已用现有数据回放: {replay_dates[0]} ~ {replay_dates[-1]}"
            )
    else:
        if start_time is None:
            raise ValueError("回测模式必须指定 start_time")
        start_dt = pd.to_datetime(start_time)
        min_need = start_dt - pd.Timedelta(minutes=warmup_bars + 120)
        full = paginate_tdx_1m(
            api,
            market,
            code,
            category,
            process_raw,
            min_datetime=min_need,
            chunk_size=chunk_size,
            max_chunks=max_chunks,
        )
        if full.empty:
            raise BacktestDataUnavailable(f"{code} 未从通达信获取到任何 1 分钟 K 线")

        oldest = pd.Timestamp(full["datetime"].iloc[0])
        if oldest > start_dt:
            raise BacktestDataUnavailable(
                f"{code} 通达信 1 分钟数据最早仅到 {oldest}，无法覆盖回测起点 {start_dt}。"
                f"请缩短 backtest_start/backtest_end，或设置 BACKTEST_DATA_SOURCE='akshare'。"
            )

    fetched_oldest = pd.Timestamp(full["datetime"].iloc[0])
    fetched_newest = pd.Timestamp(full["datetime"].iloc[-1])
    fetched_bars = len(full)

    if fetched_newest < end_dt:
        logging.warning(
            f"{code} 通达信数据最新仅到 {fetched_newest}，早于终点 {end_dt}，"
            "将使用已有数据继续"
        )

    sliced = slice_backtest_range(full, start_dt, end_dt, warmup_bars)
    if sliced.empty or (sliced["datetime"] >= start_dt).sum() == 0:
        raise BacktestDataUnavailable(
            f"{code} 在 {start_dt} ~ {end_dt} 内无 1 分钟 K 线"
            f"（通达信拉取: {fetched_oldest} ~ {fetched_newest}）"
        )

    warmup_count = int((sliced["datetime"] < start_dt).sum())
    if warmup_count < warmup_bars:
        logging.warning(
            f"{code} 回放起点前仅 {warmup_count} 根预热 K 线（期望 {warmup_bars}），"
            "指标初期可能不稳定"
        )

    meta = FetchMeta(
        source=BACKTEST_SOURCE_TDX,
        oldest=pd.Timestamp(sliced["datetime"].iloc[0]),
        newest=pd.Timestamp(sliced["datetime"].iloc[-1]),
        total_bars=len(sliced),
        warmup_bars=warmup_count,
        active_bars=int((sliced["datetime"] >= start_dt).sum()),
        active_start=start_dt,
        fetched_oldest=fetched_oldest,
        fetched_newest=fetched_newest,
        fetched_bars=fetched_bars,
        replay_dates=replay_dates or None,
    )
    return sliced, meta
