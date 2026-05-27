"""回测行情数据源（与信号逻辑、绘图解耦，仅负责产出标准 OHLCV DataFrame）。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
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
    start_time,
    end_time,
    warmup_bars: int,
    category: int,
    process_raw: Callable,
    *,
    chunk_size: int = 800,
    max_chunks: int = 50,
) -> tuple[pd.DataFrame, FetchMeta]:
    start_dt = pd.to_datetime(start_time)
    end_dt = pd.to_datetime(end_time)
    # 预热按分钟根数估算，并留交易日缓冲
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
    newest = pd.Timestamp(full["datetime"].iloc[-1])

    if oldest > start_dt:
        raise BacktestDataUnavailable(
            f"{code} 通达信 1 分钟数据最早仅到 {oldest}，无法覆盖回测起点 {start_dt}。"
            f"请缩短 backtest_start/backtest_end，或设置 BACKTEST_DATA_SOURCE='akshare'。"
        )

    if newest < end_dt:
        logging.warning(
            f"{code} 通达信数据最新仅到 {newest}，早于回测终点 {end_dt}，"
            "将使用已有数据继续回测"
        )

    sliced = slice_backtest_range(full, start_dt, end_dt, warmup_bars)
    if sliced.empty or (sliced["datetime"] >= start_dt).sum() == 0:
        raise BacktestDataUnavailable(
            f"{code} 在 {start_dt} ~ {end_dt} 内无 1 分钟 K 线（通达信可用: {oldest} ~ {newest}）"
        )

    warmup_count = int((sliced["datetime"] < start_dt).sum())
    if warmup_count < warmup_bars:
        logging.warning(
            f"{code} 回测起点前仅 {warmup_count} 根预热 K 线（期望 {warmup_bars}），"
            "指标初期可能不稳定"
        )

    meta = FetchMeta(
        source=BACKTEST_SOURCE_TDX,
        oldest=oldest,
        newest=newest,
        total_bars=len(full),
        warmup_bars=warmup_count,
        active_bars=int((sliced["datetime"] >= start_dt).sum()),
    )
    return sliced, meta
