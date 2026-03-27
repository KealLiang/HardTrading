"""
虚拟K线仿真HTML图表

目标：
- 在真实历史K线后追加多根“虚拟K线”
- 虚拟K线的开盘/收盘由百分比定义（相对前一日收盘价）
- 复用现有策略扫描图表绘制逻辑，自动得到MA5/MA10变化
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple, Union

import pandas as pd

from analysis.html_gen.strategy_scan_html_chart import _create_combined_html, _create_single_chart_figure
from fetch.stock_concept_map import get_stock_concepts, is_map_available
from utils.backtrade.visualizer import read_stock_data
from utils.date_util import get_n_trading_days_before, get_next_trading_day

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')

VirtualBarInput = Union[Dict[str, float], Tuple[float, float], List[float]]


def _normalize_virtual_bars(virtual_bars: Sequence[VirtualBarInput]) -> List[Dict[str, float]]:
    """标准化虚拟K线配置为 [{'open_pct': x, 'close_pct': y}, ...]。"""
    normalized: List[Dict[str, float]] = []
    for idx, bar in enumerate(virtual_bars):
        if isinstance(bar, dict):
            if 'open_pct' not in bar or 'close_pct' not in bar:
                raise ValueError(f"第{idx + 1}根虚拟K线缺少 open_pct/close_pct")
            open_pct = float(bar['open_pct'])
            close_pct = float(bar['close_pct'])
        elif isinstance(bar, (tuple, list)) and len(bar) == 2:
            open_pct = float(bar[0])
            close_pct = float(bar[1])
        else:
            raise ValueError(f"第{idx + 1}根虚拟K线格式无效: {bar}")
        normalized.append({'open_pct': open_pct, 'close_pct': close_pct})
    return normalized


def _append_virtual_bars(
        base_df: pd.DataFrame,
        virtual_bars: Sequence[Dict[str, float]],
        start_from_date: datetime,
) -> pd.DataFrame:
    """
    在 base_df 尾部追加虚拟K线。

    规则：
    - 第N根虚拟K线的开盘/收盘基准 = 前一根K线的收盘价
    - high/low 取 open/close 的 max/min
    - 虚拟K线成交量固定为0（便于与真实K线区分）
    """
    if base_df.empty:
        return base_df

    df = base_df.copy()
    last_close = float(df.iloc[-1]['Close'])
    current_yyyymmdd = start_from_date.strftime('%Y%m%d')
    virtual_rows = []

    for i, bar in enumerate(virtual_bars):
        next_day = get_next_trading_day(current_yyyymmdd)
        if not next_day:
            logging.warning(f"第{i + 1}根虚拟K线未找到下一个交易日，提前结束")
            break

        open_price = round(last_close * (1 + bar['open_pct'] / 100.0), 4)
        close_price = round(last_close * (1 + bar['close_pct'] / 100.0), 4)
        high_price = max(open_price, close_price)
        low_price = min(open_price, close_price)

        row_dt = datetime.strptime(next_day, '%Y%m%d')
        virtual_rows.append((row_dt, open_price, high_price, low_price, close_price, 0.0))

        # 下一根的基准是当前虚拟收盘
        last_close = close_price
        current_yyyymmdd = next_day

    if not virtual_rows:
        return df

    virtual_df = pd.DataFrame(
        [(r[1], r[2], r[3], r[4], r[5]) for r in virtual_rows],
        index=[r[0] for r in virtual_rows],
        columns=['Open', 'High', 'Low', 'Close', 'Volume'],
    )
    return pd.concat([df, virtual_df], axis=0)


def generate_virtual_kline_simulation_html(
        stock_code: str,
        stock_name: str = "",
        base_date: Optional[str] = None,
        virtual_bars: Optional[Sequence[VirtualBarInput]] = None,
        before_days: int = 60,
        columns: int = 1,
        data_dir: str = './data/astocks',
        output_dir: str = './excel/html_charts',
) -> Optional[str]:
    """
    生成单股虚拟K线仿真HTML。

    Args:
        stock_code: 股票代码（6位）
        stock_name: 股票名称（可选，空则尝试从数据推断）
        base_date: 基准日 YYYY-MM-DD / YYYYMMDD，默认为该股最后一个真实交易日
        virtual_bars: 虚拟K线列表，元素可为
            - {'open_pct': 2.0, 'close_pct': 5.0}
            - (2.0, 5.0)
        before_days: 基准日前展示交易日数量
        columns: 页面列数（默认1）
    """
    bars = _normalize_virtual_bars(virtual_bars or [])
    if not bars:
        raise ValueError("virtual_bars 不能为空，请至少提供一根虚拟K线")

    stock_data = read_stock_data(stock_code, data_dir)
    if stock_data is None or stock_data.empty:
        logging.error(f"未找到股票数据: {stock_code}")
        return None

    # 确定基准日
    if base_date:
        if '-' in base_date:
            base_dt = datetime.strptime(base_date, '%Y-%m-%d')
            base_yyyymmdd = base_date.replace('-', '')
        else:
            base_dt = datetime.strptime(base_date, '%Y%m%d')
            base_yyyymmdd = base_date
    else:
        base_dt = stock_data.index.max().to_pydatetime()
        base_yyyymmdd = base_dt.strftime('%Y%m%d')

    # 仅使用基准日及之前的真实K线
    real_df = stock_data.loc[:base_dt].copy()
    real_df = real_df.dropna(subset=['Open', 'High', 'Low', 'Close'])
    if real_df.empty:
        logging.error(f"{stock_code} 在基准日前无有效K线")
        return None

    chart_start = get_n_trading_days_before(base_yyyymmdd, before_days)
    start_dt = datetime.strptime(chart_start.replace('-', ''), '%Y%m%d')
    real_df = real_df.loc[start_dt:].copy()
    if real_df.empty:
        logging.error(f"{stock_code} 截取展示区间后无数据")
        return None

    chart_df = _append_virtual_bars(real_df, bars, real_df.index.max().to_pydatetime())

    if not stock_name:
        stock_name = stock_code

    # 不添加信号标识，保持图面简洁
    signals = []

    concepts: List[str] = []
    try:
        if is_map_available():
            concepts = get_stock_concepts(stock_code) or []
    except Exception:
        concepts = []

    first_virtual_date = chart_df.index[len(real_df)].strftime('%Y-%m-%d') if len(chart_df) > len(real_df) else None

    fig = _create_single_chart_figure(
        stock_code=stock_code,
        stock_name=stock_name,
        chart_df=chart_df,
        signal_dates_info=signals,
        before_days=before_days,
        after_days=len(bars),
        data_dir=data_dir,
        concepts=concepts,
        # 仅虚拟区间叠加浅色，不影响真实K线配色
        overlay_segment_start=first_virtual_date,
        overlay_up_color='#ff8a8a',
        overlay_down_color='#66cc66',
    )
    if fig is None:
        logging.error("生成图表失败")
        return None

    # 卡片标题补充虚拟设定，便于回看参数
    bar_desc = " | ".join([f"#{i + 1}:O{b['open_pct']:+.1f}% C{b['close_pct']:+.1f}%"
                           for i, b in enumerate(bars)])
    title = f"{stock_code} {stock_name} | 基准日: {real_df.index.max().strftime('%Y-%m-%d')} | {bar_desc}"

    html_content = _create_combined_html([fig], [title], columns=columns, rows=1)
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"virtual_kline_{stock_code}.html")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)

    logging.info(f"虚拟K线仿真HTML已生成: {output_file}")
    return output_file

