"""
天梯入选日侧车导出（方案 A）

与 bin/candidate_temp/candidate_stocks.txt 配套，写入 JSON，供策略扫描 HTML 等后续流程读取。
每只股票可有多段入选：全部日期导出，按日历从新到旧排序（最晚在最前）；作图时通常只取第一个。
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

# 与 main.generate_ladder_chart / 扫描默认候选目录一致
DEFAULT_LADDER_ENTRY_JSON = "bin/candidate_temp/candidate_ladder_entry.json"


def _first_significant_date_to_yyyymmdd(val: Any) -> Optional[str]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y%m%d")
    if isinstance(val, pd.Timestamp):
        return val.strftime("%Y%m%d")
    if hasattr(val, "strftime"):
        try:
            return val.strftime("%Y%m%d")
        except Exception:
            return None
    s = str(val).strip().replace("-", "")
    if len(s) >= 8 and s[:8].isdigit():
        return s[:8]
    return None


def collect_ladder_entry_dates_map(
    result_df: pd.DataFrame,
    momo_df: Optional[pd.DataFrame],
    start_date: str,
    end_date: str,
    enable_momo_shangzhang: bool,
    pure_code_fn,
) -> Dict[str, List[str]]:
    """
    从显著连板 result_df（及可选【默默上涨】）汇总每只股票的所有 first_significant_date。

    Args:
        result_df: identify_significant_boards 结果
        momo_df: 原始默默上涨数据（与 build_ladder_chart 一致）
        start_date / end_date: YYYYMMDD
        enable_momo_shangzhang: 是否合并默默上涨行
        pure_code_fn: 与梯队一致的纯代码函数，如 extract_pure_stock_code
    """
    code_to_dates: Dict[str, set] = defaultdict(set)

    if result_df is not None and not result_df.empty:
        for _, row in result_df.iterrows():
            code = pure_code_fn(row.get("stock_code", ""))
            if not code:
                continue
            d = _first_significant_date_to_yyyymmdd(row.get("first_significant_date"))
            if d:
                code_to_dates[code].add(d)

    if enable_momo_shangzhang and momo_df is not None and not momo_df.empty:
        try:
            from analysis.momo_shangzhang_processor import identify_momo_shangzhang_stocks

            momo_result_df = identify_momo_shangzhang_stocks(momo_df, start_date, end_date)
            if momo_result_df is not None and not momo_result_df.empty:
                for _, row in momo_result_df.iterrows():
                    code = pure_code_fn(row.get("stock_code", ""))
                    if not code:
                        continue
                    d = _first_significant_date_to_yyyymmdd(row.get("first_significant_date"))
                    if d:
                        code_to_dates[code].add(d)
        except Exception:
            pass

    out: Dict[str, List[str]] = {}
    for code, dates in code_to_dates.items():
        out[code] = sorted(dates, reverse=True)
    return out


def write_ladder_entry_json(
    entry_map: Dict[str, List[str]],
    output_path: str = DEFAULT_LADDER_ENTRY_JSON,
) -> bool:
    """写入 JSON；目录不存在则创建。"""
    try:
        out_dir = os.path.dirname(output_path)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir)

        payload = {
            "version": 1,
            "description": "天梯入选日：每键为6位代码，值为YYYYMMDD列表，从新到旧",
            "codes": entry_map,
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"已写入天梯入选日侧车: {output_path}（共 {len(entry_map)} 只股票）")
        return True
    except Exception as e:
        print(f"写入天梯入选日侧车失败: {e}")
        return False


def load_ladder_entry_dates(path: str = DEFAULT_LADDER_ENTRY_JSON) -> Dict[str, List[str]]:
    """
    读取侧车文件。缺失或损坏时返回空 dict。
    返回值为 {6位代码: [YYYYMMDD, ...]}，日期列表从新到旧。
    """
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw = None
        if isinstance(data, dict) and "codes" in data and isinstance(data["codes"], dict):
            raw = data["codes"]
        elif isinstance(data, dict):
            raw = {k: v for k, v in data.items() if k != "version" and k != "description"}
        if not isinstance(raw, dict):
            return {}
        out: Dict[str, List[str]] = {}
        for k, v in raw.items():
            if not isinstance(v, list):
                continue
            dates = []
            for x in v:
                s = str(x).strip().replace("-", "")
                if len(s) >= 8 and s[:8].isdigit():
                    dates.append(s[:8])
            if dates:
                uniq = sorted(set(dates), reverse=True)
                out[str(k).zfill(6)] = uniq
        return out
    except Exception:
        return {}
