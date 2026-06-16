"""实盘监控波段状态本地持久化（进程重启后恢复冷却/波段记忆）。"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

STATE_VERSION = 1


def default_state_dir() -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "state")


def state_file_path(symbol: str, state_dir: Optional[str] = None) -> str:
    directory = state_dir or default_state_dir()
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, f"{symbol}.json")


def _ts_to_str(ts) -> Optional[str]:
    if ts is None:
        return None
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


def _str_to_ts(value) -> Optional[pd.Timestamp]:
    if not value:
        return None
    return pd.to_datetime(value)


def _is_stale(ts, retention_days: int, now: Optional[datetime] = None) -> bool:
    if ts is None:
        return True
    ref = now or datetime.now()
    dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else pd.to_datetime(ts).to_pydatetime()
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt < ref - timedelta(days=retention_days)


def build_payload(
    symbol: str,
    last_signal_time: dict,
    last_signal_price: dict,
    rsi_wave_active: dict,
    wave_extreme: Optional[dict] = None,
) -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "symbol": symbol,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "last_signal_time": {k: _ts_to_str(v) for k, v in last_signal_time.items()},
        "last_signal_price": {k: (None if v is None else float(v)) for k, v in last_signal_price.items()},
        "rsi_wave_active": dict(rsi_wave_active),
        "wave_extreme": (
            None
            if wave_extreme is None
            else {k: (None if v is None else float(v)) for k, v in wave_extreme.items()}
        ),
    }


def save_live_state(path: str, payload: dict) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_live_state(path: str, retention_days: int) -> Optional[dict[str, Any]]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logging.warning(f"读取监控状态失败 {path}: {e}")
        return None

    if not isinstance(data, dict):
        return None

    for side in ("BUY", "SELL"):
        ts = _str_to_ts(data.get("last_signal_time", {}).get(side))
        if _is_stale(ts, retention_days):
            data.setdefault("last_signal_time", {})[side] = None
            data.setdefault("last_signal_price", {})[side] = None
            data.setdefault("rsi_wave_active", {})[side] = False
            if isinstance(data.get("wave_extreme"), dict):
                data["wave_extreme"][side] = None

    return data


def format_state_summary(monitor) -> list[str]:
    """根据 monitor 当前内存状态生成摘要行。"""
    summaries = []
    for side in ("BUY", "SELL"):
        ts = monitor.last_signal_time.get(side)
        price = monitor.last_signal_price.get(side)
        if ts is not None and price is not None:
            ttxt = ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts)
            summaries.append(f"{side}@{price:.2f}({ttxt})")
        elif monitor.rsi_wave_active.get(side):
            summaries.append(f"{side}波段活跃")
    return summaries


def apply_loaded_state(monitor, data: dict) -> list[str]:
    """将磁盘状态写入 monitor 实例，返回可展示摘要行。"""
    summaries = []
    for side in ("BUY", "SELL"):
        ts = _str_to_ts(data.get("last_signal_time", {}).get(side))
        price = data.get("last_signal_price", {}).get(side)
        monitor.last_signal_time[side] = ts
        monitor.last_signal_price[side] = price
        monitor.rsi_wave_active[side] = bool(
            data.get("rsi_wave_active", {}).get(side, False)
        )
        if ts is not None and price is not None:
            ttxt = ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts)
            summaries.append(f"{side}@{price:.2f}({ttxt})")
        elif monitor.rsi_wave_active[side]:
            summaries.append(f"{side}波段活跃")

    wave_extreme = data.get("wave_extreme")
    if wave_extreme is not None and hasattr(monitor, "_wave_extreme"):
        for side in ("BUY", "SELL"):
            val = wave_extreme.get(side)
            monitor._wave_extreme[side] = None if val is None else float(val)

    return summaries
