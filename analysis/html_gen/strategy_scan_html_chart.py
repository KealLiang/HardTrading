"""
策略扫描结果HTML交互式图表生成器

根据scan_summary文件生成策略扫描入选股的HTML交互式图表，按股票分组展示。
每只股票一张图，可以显示多个信号日期。

作者：AI Assistant
版本：v2.0
日期：2026-01-15
"""

import logging
import os
import re
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from typing import List, Dict, Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from utils.backtrade.visualizer import read_stock_data
from utils.date_util import get_n_trading_days_before, get_next_trading_day, get_current_or_prev_trading_day
from utils.number_format_cn import format_turnover_amount_cn
from utils.stock_util import calculate_period_change_from_date, stock_limit_ratio, get_stock_market

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')

# 信号类型配置：(匹配模式, 显示名称)
# 与 main.py 中的 signal_patterns 保持对应
SIGNAL_TYPE_CONFIG = [
    ('二次确认信号', '二次确认'),  # 标准通道：观察期内二次确认
    ('买入信号: 快速通道', '快速通道'),  # 快速通道：信号日当天买入
    ('买入信号: 回踩确认', '回踩确认'),  # 缓冲通道：回调后买入
    ('买入信号: 止损纠错', '止损纠错'),  # 止损纠错：价格合适买入
]

# 策略扫描信号：按「类型」固定颜色/形状，避免合并天梯入选等条目后列表下标变化导致样式漂移
# （与原先 idx=0..3 时的轮换顺序一致）
_SCAN_MARKER_STYLE_BY_TYPE = {
    '二次确认': {'color': 'blue', 'symbol': 'triangle-up'},
    '快速通道': {'color': 'purple', 'symbol': 'triangle-up'},
    '回踩确认': {'color': 'orange', 'symbol': 'diamond-tall'},
    '止损纠错': {'color': 'red', 'symbol': 'hourglass'},
}

DEFAULT_BEFORE_DAYS = 60  # 信号日前显示的交易日数
DEFAULT_AFTER_DAYS = 30  # 信号日后显示的交易日数

INDEXES_DIR = './data/indexes'
SH_LEADER_INDEX_FILE = os.path.join(INDEXES_DIR, 'sh000065_上证龙头.csv')
SZ_LEADER_INDEX_FILE = os.path.join(INDEXES_DIR, 'sz399653_深证龙头.csv')
GEM_INDEX_FILE = os.path.join(INDEXES_DIR, 'sz399006_创业板指.csv')
STAR_INDEX_FILE = os.path.join(INDEXES_DIR, 'sh000688_科创50.csv')
BSE_INDEX_FILE = os.path.join(INDEXES_DIR, 'bj899050_北证50.csv')

# 建仓价格区间（基于最新信号日MA5，不区分信号类别）的全局配置，单位为百分比
# 例如：-0.01 表示 -1%，0.03 表示 +3%
ENTRY_RANGE_LOW_PCT = -0.01
ENTRY_RANGE_MID_PCT = 0.05
ENTRY_RANGE_HIGH_PCT = 0.11

# 涨跌幅计算周期（交易日）
PERIOD_DAYS = [30, 60, 120]  # 计算30日、60日、120日涨跌幅

# 右侧百分比轴配置（基于“最早一次信号日”的开盘价）
PCT_AXIS_TICK_COUNT = 6  # 右轴刻度数
PCT_AXIS_DECIMALS = 1  # 百分比小数位
PCT_AXIS_TICK_FONT_SIZE = 8  # 仅右侧涨跌幅数字字号

# 龙头sheet信号：入选/移除统一使用上下三角，图例各只出现一次
_LEADER_ENTRY_COLOR = '#1f77b4'
_LEADER_REMOVAL_COLOR = '#9966FF'

# 天梯入选（侧车 JSON）：与策略扫描信号区分，同日复数时纵向错开绘制
_LADDER_ENTRY_COLOR = '#2ca02c'
_LADDER_SIGNAL_TYPE = '天梯入选'
_MOMO_SIGNAL_TYPE = '默默上涨入选'
_ZABAN_COLOR = '#ff8c00'
_ZABAN_SIGNAL_TYPE = '炸板'
_ATTENTION_COLOR = '#00bcd4'
_ATTENTION_SIGNAL_TYPE = '关注度入榜'

DEFAULT_LADDER_ENTRY_JSON = 'bin/candidate_temp/candidate_ladder_entry.json'


def _resolve_signal_marker_style(signal_type: str, idx: int, signal_date: str) -> Dict:
    """
    龙头入选/龙头移除/天梯入选：固定样式。
    已知策略类型（二次确认、快速通道等）：固定样式，不依赖在 signal_dates_info 中的下标。
    其余：仍按 idx 轮换（兼容未归类信号）。
    """
    st = (signal_type or '').strip()
    if st == '龙头移除':
        return {
            'color': _LEADER_REMOVAL_COLOR,
            'symbol': 'triangle-down',
            'name': '龙头移除',
            'legendgroup': 'leader_removal',
            'unified_legend': True,
        }
    if st == '龙头入选':
        return {
            'color': _LEADER_ENTRY_COLOR,
            'symbol': 'triangle-up',
            'name': '龙头入选',
            'legendgroup': 'leader_entry',
            'unified_legend': True,
        }
    if st == _LADDER_SIGNAL_TYPE:
        return {
            'color': _LADDER_ENTRY_COLOR,
            'symbol': 'triangle-up',
            'name': _LADDER_SIGNAL_TYPE,
            'legendgroup': 'ladder_entry',
            'unified_legend': True,
        }
    if st == _MOMO_SIGNAL_TYPE:
        return {
            'color': '#1e88e5',
            'symbol': 'triangle-up',
            'name': _MOMO_SIGNAL_TYPE,
            'legendgroup': 'momo_entry',
            'unified_legend': True,
        }
    if st == _ZABAN_SIGNAL_TYPE:
        return {
            'color': _ZABAN_COLOR,
            'symbol': 'x',
            'name': _ZABAN_SIGNAL_TYPE,
            'legendgroup': 'zaban',
            'unified_legend': True,
        }
    if st == _ATTENTION_SIGNAL_TYPE:
        return {
            'color': _ATTENTION_COLOR,
            'symbol': 'star-open',
            'name': _ATTENTION_SIGNAL_TYPE,
            'legendgroup': 'attention_rank',
            'unified_legend': True,
        }
    fixed = _SCAN_MARKER_STYLE_BY_TYPE.get(st)
    if fixed:
        return {
            'color': fixed['color'],
            'symbol': fixed['symbol'],
            'name': f'{signal_date} ({st})',
            'legendgroup': None,
            'unified_legend': False,
        }
    signal_colors = ['blue', 'purple', 'orange', 'red', 'green', 'brown']
    signal_symbols = ['triangle-up', 'triangle-down', 'diamond', 'square', 'star', 'circle']
    return {
        'color': signal_colors[idx % len(signal_colors)],
        'symbol': signal_symbols[idx % len(signal_symbols)],
        'name': f'{signal_date} ({st or "Signal"})',
        'legendgroup': None,
        'unified_legend': False,
    }


def _extract_signal_type(details: str) -> str:
    """
    从详情字段中提取简短的信号类型描述
    
    Args:
        details: scan_summary中的详情字段
        
    Returns:
        简短的信号类型，如 "止损纠错"、"回踩确认"、"二次确认" 等
    """
    if not details:
        return "Signal"

    for pattern, signal_type in SIGNAL_TYPE_CONFIG:
        if pattern in details:
            return signal_type

    return "Signal"


def _merge_ladder_entry_into_signals(
        stock_code: str,
        signals_info: List[Dict],
        ladder_map: Dict[str, List[str]],
) -> List[Dict]:
    """
    将侧车中的天梯入选日并入信号列表。JSON 中日期为从新到旧，作图仅使用第一个（最晚一次入选）。
    同日多标记时：先画策略信号（更靠近 K 线），天梯入选画在更下方（y 更低）。
    """
    code = str(stock_code).zfill(6)
    dates = ladder_map.get(code)
    if not dates:
        return list(signals_info)

    ymd = dates[0]
    if not isinstance(ymd, str) or len(ymd) != 8 or not ymd.isdigit():
        return list(signals_info)

    dt_str = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
    merged: List[Dict] = []
    for i, s in enumerate(signals_info):
        d = dict(s)
        d['_merge_order'] = i
        merged.append(d)
    merged.append({
        'signal_date': dt_str,
        'signal_type': _LADDER_SIGNAL_TYPE,
        'price': None,
        '_merge_order': len(signals_info) + 999,
    })
    merged.sort(key=lambda s: (
        s['signal_date'],
        1 if s.get('signal_type') == _LADDER_SIGNAL_TYPE else 0,
        s.get('_merge_order', 0),
    ))
    return merged


def parse_scan_summary(summary_file_path: str) -> Dict[str, List[Dict]]:
    """
    解析scan_summary文件，按股票代码分组
    
    Args:
        summary_file_path: summary文件路径
        
    Returns:
        Dict[股票代码, List[股票信息字典]]
        股票信息字典包含: code, name, signal_date, signal_type, price, score, details
    """
    stock_signals_map = defaultdict(list)

    try:
        with open(summary_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for line in lines:
            if line.strip() and not line.startswith('扫描策略') and not line.startswith(
                    '扫描范围') and not line.startswith('总计发现') and not line.startswith('-'):
                # 解析格式：股票: 300732 设研院, 信号日期: 2025-08-11, 价格: 12.22, 评分: 0，详情: ...
                stock_match = re.search(r'股票:\s*(\d{6})\s*([^,]*)', line)
                date_match = re.search(r'信号日期:\s*(\d{4}-\d{2}-\d{2})', line)
                price_match = re.search(r'价格:\s*([\d.]+)', line)
                score_match = re.search(r'评分:\s*([^,]+)', line)
                details_match = re.search(r'详情:\s*(.+)$', line)

                if stock_match and date_match:
                    code = stock_match.group(1)
                    name = stock_match.group(2).strip()
                    signal_date = date_match.group(1)
                    price = float(price_match.group(1)) if price_match else None
                    score = score_match.group(1).strip() if score_match else None
                    details = details_match.group(1).strip() if details_match else ''
                    signal_type = _extract_signal_type(details)

                    stock_info = {
                        'code': code,
                        'name': name,
                        'signal_date': signal_date,
                        'signal_type': signal_type,
                        'price': price,
                        'score': score,
                        'details': details
                    }
                    stock_signals_map[code].append(stock_info)

        logging.info(f"解析完成，共找到 {len(stock_signals_map)} 只股票")
        for code, signals in list(stock_signals_map.items())[:5]:
            logging.info(f"  {code}: {len(signals)} 个信号")

    except Exception as e:
        logging.error(f"解析scan_summary文件失败: {e}")

    return stock_signals_map


def _calculate_period_changes(stock_code: str, signal_date: str, data_dir: str) -> Dict[int, float]:
    """
    计算股票从信号日期往前数N个交易日到信号日期的各周期涨跌幅
    
    Args:
        stock_code: 股票代码
        signal_date: 信号日期 YYYYMMDD
        data_dir: 数据目录
        
    Returns:
        Dict[周期天数, 涨跌幅百分比]
    """
    period_changes = {}

    # 计算各周期涨跌幅（从信号日期往前数N个交易日）
    for period in PERIOD_DAYS:
        try:
            change = calculate_period_change_from_date(stock_code, signal_date, period, data_dir)
            if change is not None:
                period_changes[period] = change
        except Exception as e:
            logging.debug(f"计算 {stock_code} {period}日涨跌幅失败: {e}")

    return period_changes


def _stock_concept_bracket_inner_html(concepts: List[str]) -> str:
    """股票概念方括号内的 HTML（不含外层 <b>），与历史展示一致。"""
    if not concepts:
        return ''
    n = len(concepts)
    if n <= 4:
        return " + ".join(concepts)
    split_idx = (n + 1) // 2
    first_line = " + ".join(concepts[:split_idx])
    second_line = " + ".join(concepts[split_idx:])
    return f"{first_line}<br>{second_line}"


def _format_stock_concept_bracket_html(concepts: List[str]) -> str:
    """同花顺股票概念：单独一行时的整段 HTML。"""
    inner = _stock_concept_bracket_inner_html(concepts)
    if not inner:
        return ''
    return f"<b>[{inner}]</b>"


def _format_zt_reason_bracket_html(zt_concepts: List[str]) -> str:
    """复盘涨停概念：与 Excel 习惯一致，词条间用紧密的 + 连接。"""
    if not zt_concepts:
        return ''
    inner = "+".join(zt_concepts)
    return f"[{inner}]"


def _format_title(stock_code: str, stock_name: str, signal_dates_info: List[Dict],
                  concepts: Optional[List[str]] = None,
                  zt_limit_up_concepts: Optional[List[str]] = None,
                  chart_df: Optional[pd.DataFrame] = None,
                  data_dir: str = './data/astocks') -> str:
    """
    格式化图表标题
    
    Args:
        stock_code: 股票代码
        stock_name: 股票名称
        signal_dates_info: 信号日期信息列表
        concepts: 同花顺股票概念列表。与 zt_limit_up_concepts 同时存在时，图内标题首行仅代码+名称，
            股票概念单独成行；涨停概念只在页顶灰条展示（由调用方 chart_titles 负责），图内不再重复。
        zt_limit_up_concepts: 复盘涨停概念。仅当没有股票概念时，才在图内首行名称后附加 [a+b+…]。
        chart_df: 当前图窗 K 线数据，用于取最新一日成交额（列名 amount）
        data_dir: 计算周期涨跌幅所用数据目录
        
    Returns:
        格式化的标题HTML字符串
    """
    title_parts: List[str] = []
    zt = [x for x in (zt_limit_up_concepts or []) if x]
    stock_tags = [x for x in (concepts or []) if x]

    if zt and stock_tags:
        title_parts.append(f"<b>{stock_code} {stock_name}</b>")
        title_parts.append(_format_stock_concept_bracket_html(stock_tags))
    elif stock_tags:
        inner = _stock_concept_bracket_inner_html(stock_tags)
        title_parts.append(f"<b>{stock_code} {stock_name} [{inner}]</b>")
    elif zt:
        zt_br = _format_zt_reason_bracket_html(zt)
        title_parts.append(f"<b>{stock_code} {stock_name} {zt_br}</b>")
    else:
        title_parts.append(f"<b>{stock_code} {stock_name}</b>")

    latest_amount_str: Optional[str] = None
    if chart_df is not None and not chart_df.empty and 'amount' in chart_df.columns:
        amt_series = chart_df['amount'].dropna()
        if not amt_series.empty:
            latest_amount_str = format_turnover_amount_cn(amt_series.iloc[-1])

    # 计算最新信号的周期涨跌幅
    if signal_dates_info:
        latest_signal = max(signal_dates_info, key=lambda x: x['signal_date'])
        signal_date_yyyymmdd = latest_signal['signal_date'].replace("-", "")
        period_changes = _calculate_period_changes(stock_code, signal_date_yyyymmdd, data_dir)

        if period_changes:
            change_items = []
            for period in sorted(period_changes.keys()):
                change = period_changes[period]
                # A股习惯：红涨绿跌
                color = 'red' if change > 0 else 'green' if change < 0 else 'gray'
                change_items.append(f"<span style='color:{color}'>{period}日: {change:+.2f}%</span>")

            if change_items:
                line = " | ".join(change_items)
                if latest_amount_str:
                    line += f" | <span style='color:#666'>最新成交额: {latest_amount_str}</span>"
                title_parts.append(line)
        elif latest_amount_str:
            title_parts.append(f"<span style='color:#666'>最新成交额: {latest_amount_str}</span>")
    elif latest_amount_str:
        title_parts.append(f"<span style='color:#666'>最新成交额: {latest_amount_str}</span>")

    return "<br>".join(title_parts)


@lru_cache(maxsize=16)
def _load_index_dataframe(index_file: str) -> pd.DataFrame:
    """读取任意指数日线数据（无表头 CSV）。"""
    if not index_file or not os.path.exists(index_file):
        return pd.DataFrame()

    try:
        df = pd.read_csv(
            index_file,
            header=None,
            names=['date', 'open', 'high', 'low', 'close', 'volume'],
        )
        if df.empty:
            return pd.DataFrame()

        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=['date']).sort_values('date')
        if df.empty:
            return pd.DataFrame()

        df['date'] = df['date'].dt.tz_localize(None)
        df = df.set_index('date')
        df = df[~df.index.duplicated(keep='last')]
        return df
    except Exception as e:
        logging.warning(f"读取指数数据失败 {index_file}: {e}")
        return pd.DataFrame()


def _build_daily_pct_change_series(chart_df: pd.DataFrame) -> pd.Series:
    """优先复用原始 pct_chg，否则基于 Close 计算日涨跌幅。"""
    if chart_df is None or chart_df.empty:
        return pd.Series(dtype='float64')

    if 'pct_chg' in chart_df.columns:
        pct_series = pd.to_numeric(chart_df['pct_chg'], errors='coerce')
        if not pct_series.dropna().empty:
            return pct_series

    if 'Close' not in chart_df.columns:
        return pd.Series(dtype='float64')

    close_series = pd.to_numeric(chart_df['Close'], errors='coerce')
    return close_series.pct_change() * 100.0


def _resolve_benchmark_index_file(stock_code: str, benchmark_index_file: Optional[str] = None) -> Optional[str]:
    """
    根据股票自动选择对比指数。

    优先级：
    1. 显式传入 benchmark_index_file 时直接使用
    2. 自动按市场选择：
       - 沪市主板 -> 上证龙头
       - 深市主板 -> 深证龙头
       - 创业板 -> 创业板指
       - 科创板 -> 科创50
       - 北交所 -> 北证50
       - 新三板 -> 无指数，不绘制
    """
    if benchmark_index_file:
        return benchmark_index_file

    code = str(stock_code).strip()
    try:
        market = get_stock_market(code)
    except Exception:
        return None

    if market == 'main':
        if code.startswith('60'):
            return SH_LEADER_INDEX_FILE
        if code.startswith('00'):
            return SZ_LEADER_INDEX_FILE
        return None
    if market == 'gem':
        return GEM_INDEX_FILE
    if market == 'star':
        return STAR_INDEX_FILE
    if market == 'bse':
        return BSE_INDEX_FILE
    if market == 'neeq':
        return None
    return None


def _build_daily_relative_strength_series(
        stock_code: str,
        chart_df: pd.DataFrame,
        index_file: Optional[str],
) -> Optional[pd.Series]:
    """
    计算每日相对强弱：
    个股当日涨跌幅 - 指数当日涨跌幅
    """
    if chart_df is None or chart_df.empty:
        return None

    if not index_file:
        return None

    index_df = _load_index_dataframe(index_file)
    if index_df.empty or 'close' not in index_df.columns:
        return None

    stock_pct = _build_daily_pct_change_series(chart_df)
    index_close = pd.to_numeric(index_df['close'], errors='coerce')
    index_pct = index_close.pct_change() * 100.0

    aligned = pd.DataFrame({'stock_pct': stock_pct}).join(index_pct.rename('index_pct'), how='left')
    aligned = aligned.dropna(subset=['stock_pct', 'index_pct'])
    if aligned.empty:
        return None

    # 过滤明显异常的日涨跌幅（如新股上市首日、数据异常），避免单点把整条曲线压扁。
    try:
        stock_limit_pct = abs(float(stock_limit_ratio(str(stock_code)))) * 100.0
    except Exception:
        stock_limit_pct = 10.0
    stock_abs_ceiling = max(stock_limit_pct + 5.0, 35.0)

    daily_rs = aligned['stock_pct'] - aligned['index_pct']
    daily_rs_abs_ceiling = max(stock_abs_ceiling * 1.5, 50.0)
    valid_mask = (
        aligned['stock_pct'].abs() <= stock_abs_ceiling
    ) & (
        daily_rs.abs() <= daily_rs_abs_ceiling
    )
    daily_rs = daily_rs.where(valid_mask).round(2)

    out = pd.Series(index=chart_df.index, dtype='float64')
    out.loc[aligned.index] = daily_rs
    return out


def _create_single_chart_figure(
        stock_code: str,
        stock_name: str,
        chart_df: pd.DataFrame,
        signal_dates_info: List[Dict],
        before_days: int = DEFAULT_BEFORE_DAYS,
        after_days: int = DEFAULT_AFTER_DAYS,
        data_dir: str = './data/astocks',
        concepts: Optional[List[str]] = None,
        zt_limit_up_concepts: Optional[List[str]] = None,
        kline_up_color: str = '#ff4444',
        kline_down_color: str = '#00aa00',
        overlay_segment_start: Optional[str] = None,
        overlay_up_color: str = '#ff8a8a',
        overlay_down_color: str = '#66cc66',
        entry_range_anchor_signal_types: Optional[List[str]] = None,
        show_daily_relative_strength: bool = False,
        benchmark_index_file: Optional[str] = None,
        daily_relative_strength_label: str = '每日相对强弱',
) -> Optional[go.Figure]:
    """
    创建单个图表的Figure对象，支持多个信号日期标记
    
    Args:
        stock_code: 股票代码
        stock_name: 股票名称
        chart_df: K线数据DataFrame
        signal_dates_info: 信号日期信息列表
        before_days: 信号日前显示的交易日数
        after_days: 信号日后显示的交易日数
        data_dir: 数据目录
        concepts: 同花顺股票概念（板块）列表
        zt_limit_up_concepts: 复盘涨停原因；无股票概念时写入图内标题，有股票概念时不写入图内（避免与页顶重复）
        
    Returns:
        go.Figure: Plotly图表对象
    """
    try:
        daily_relative_strength_series = None
        if show_daily_relative_strength:
            benchmark_index_file = _resolve_benchmark_index_file(stock_code, benchmark_index_file)
            daily_relative_strength_series = _build_daily_relative_strength_series(
                stock_code, chart_df, benchmark_index_file
            )

        has_daily_relative_strength = (
            daily_relative_strength_series is not None and
            not daily_relative_strength_series.dropna().empty
        )

        total_rows = 3 if has_daily_relative_strength else 2
        volume_row = 2
        rs_row = 3 if has_daily_relative_strength else None

        # 创建子图：主图（K线）+ 成交量图 + 每日相对强弱图（可选）
        fig = make_subplots(
            rows=total_rows, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.60, 0.24, 0.16] if has_daily_relative_strength else [0.7, 0.3],
            specs=(
                [[{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]]
                if has_daily_relative_strength else
                [[{"secondary_y": True}], [{"secondary_y": False}]]
            ),
            subplot_titles=tuple([''] * total_rows)
        )

        # 准备数据：x 使用交易日字符串分类轴（按已有交易日顺序），避免节假日空白
        dates = chart_df.index
        date_labels = [d.strftime('%Y-%m-%d') for d in dates]
        x_plot = date_labels

        # 转换为列表
        opens = chart_df['Open'].values.tolist()
        highs = chart_df['High'].values.tolist()
        lows = chart_df['Low'].values.tolist()
        closes = chart_df['Close'].values.tolist()
        volumes = chart_df['Volume'].values.tolist()

        def _resolve_pct_axis_base_price() -> float:
            """右侧百分比轴基准价：最早信号日开盘价。"""
            if not opens:
                return 1.0

            earliest_signal_dt = None
            for sig in signal_dates_info:
                try:
                    dt = datetime.strptime(sig['signal_date'], '%Y-%m-%d')
                    if earliest_signal_dt is None or dt < earliest_signal_dt:
                        earliest_signal_dt = dt
                except Exception:
                    continue

            if earliest_signal_dt is not None:
                for i, dt in enumerate(dates):
                    if dt.date() == earliest_signal_dt.date():
                        base_open = opens[i]
                        if base_open is not None and base_open > 0:
                            return float(base_open)

            first_open = opens[0]
            return float(first_open) if first_open and first_open > 0 else 1.0

        # 验证数据有效性
        if len(opens) == 0:
            return None

        # 先解析信号：合并进当日 K 线 hover，避免 x unified 把单点 Scatter 误挂到相邻 K 线上
        signals_by_idx = defaultdict(list)
        for idx, sig_info in enumerate(signal_dates_info):
            signal_date = sig_info['signal_date']
            signal_type = sig_info.get('signal_type', 'Signal')
            price = sig_info.get('price')
            try:
                signal_date_dt = datetime.strptime(signal_date, '%Y-%m-%d')
                signal_idx = None
                for i, date in enumerate(dates):
                    if date.date() == signal_date_dt.date():
                        signal_idx = i
                        break
                if signal_idx is None or not (0 <= signal_idx < len(chart_df)):
                    continue
                display_price = price if price is not None else chart_df.iloc[signal_idx]['Close']
                signals_by_idx[signal_idx].append(
                    f"信号日: {signal_date}<br>类型: {signal_type}<br>价格: {display_price:.2f}"
                )
            except Exception as e:
                logging.debug(f"解析信号用于hover失败 {signal_date}: {e}")

        kline_hover = []
        for i in range(len(chart_df)):
            base = (
                f"{date_labels[i]}<br>open: {opens[i]}<br>high: {highs[i]}<br>"
                f"low: {lows[i]}<br>close: {closes[i]}"
            )
            if i in signals_by_idx:
                base += "<br>" + "<br>".join(signals_by_idx[i])
            kline_hover.append(base)

        # 1. 绘制K线图
        candlestick = go.Candlestick(
            x=x_plot,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            name='K线',
            increasing_line_color=kline_up_color,
            decreasing_line_color=kline_down_color,
            increasing_fillcolor=kline_up_color,
            decreasing_fillcolor=kline_down_color,
            hovertext=kline_hover,
            hoverinfo='text',
        )
        fig.add_trace(candlestick, row=1, col=1)

        # 可选：对某个日期起的区间叠加另一套K线配色（用于只淡化虚拟K线）
        if overlay_segment_start:
            try:
                overlay_start_dt = datetime.strptime(overlay_segment_start, '%Y-%m-%d')
                overlay_mask = [d.date() >= overlay_start_dt.date() for d in dates]
                if any(overlay_mask):
                    x_overlay = [x_plot[i] for i, m in enumerate(overlay_mask) if m]
                    open_overlay = [opens[i] for i, m in enumerate(overlay_mask) if m]
                    high_overlay = [highs[i] for i, m in enumerate(overlay_mask) if m]
                    low_overlay = [lows[i] for i, m in enumerate(overlay_mask) if m]
                    close_overlay = [closes[i] for i, m in enumerate(overlay_mask) if m]

                    overlay_trace = go.Candlestick(
                        x=x_overlay,
                        open=open_overlay,
                        high=high_overlay,
                        low=low_overlay,
                        close=close_overlay,
                        name='K线',
                        increasing_line_color=overlay_up_color,
                        decreasing_line_color=overlay_down_color,
                        increasing_fillcolor=overlay_up_color,
                        decreasing_fillcolor=overlay_down_color,
                        showlegend=False,
                        hoverinfo='skip',
                    )
                    fig.add_trace(overlay_trace, row=1, col=1)
            except Exception as e:
                logging.debug(f"叠加区间配色失败: {e}")

        # 1.1 计算并添加5日均线
        ma5 = pd.Series(closes).rolling(window=5, min_periods=1).mean()
        ma5_line = go.Scatter(
            x=x_plot,
            y=ma5.tolist(),
            mode='lines',
            name='MA5',
            line=dict(color='#FFA500', width=1.5),
            customdata=date_labels,
            hovertemplate='%{customdata}<br>MA5: %{y:.2f}<extra></extra>',
        )
        fig.add_trace(ma5_line, row=1, col=1)

        # 1.2 计算并添加10日均线
        ma10 = pd.Series(closes).rolling(window=10, min_periods=1).mean()
        ma10_line = go.Scatter(
            x=x_plot,
            y=ma10.tolist(),
            mode='lines',
            name='MA10',
            line=dict(color='#0000FF', width=1.5),
            customdata=date_labels,
            hovertemplate='%{customdata}<br>MA10: %{y:.2f}<extra></extra>',
        )
        fig.add_trace(ma10_line, row=1, col=1)

        # 2. 信号标记（仅图形；hover 已并入 K 线，此处关闭避免 unified 误匹配）
        leader_entry_seen = False
        leader_removal_seen = False
        ladder_entry_seen = False
        zaban_seen = False
        attention_seen = False
        momo_seen = False

        def _signal_idx_for_date(signal_date: str):
            try:
                signal_date_dt = datetime.strptime(signal_date, '%Y-%m-%d')
                for i, date in enumerate(dates):
                    if date.date() == signal_date_dt.date():
                        return i
            except Exception:
                pass
            return None

        marker_plan = []
        for idx, sig_info in enumerate(signal_dates_info):
            signal_date = sig_info['signal_date']
            si = _signal_idx_for_date(signal_date)
            if si is not None and 0 <= si < len(chart_df):
                marker_plan.append((si, sig_info, idx))

        by_signal_idx = defaultdict(list)
        for item in marker_plan:
            by_signal_idx[item[0]].append(item)

        for signal_idx in sorted(by_signal_idx.keys()):
            items = by_signal_idx[signal_idx]
            # 同日：先策略类（更靠上），后附加标记（更靠下）；同类按原顺序
            items.sort(key=lambda t: (
                1 if t[1].get('signal_type') in (
                    _LADDER_SIGNAL_TYPE, _ZABAN_SIGNAL_TYPE, _ATTENTION_SIGNAL_TYPE
                ) else 0,
                t[2],
            ))
            low_v = float(chart_df.iloc[signal_idx]['Low'])

            for k, (_si, sig_info, orig_idx) in enumerate(items):
                signal_date = sig_info['signal_date']
                signal_type = sig_info.get('signal_type', 'Signal')
                price = sig_info.get('price')
                try:
                    offset = 0.95 - k * 0.05
                    signal_price = low_v * max(offset, 0.55)

                    style = _resolve_signal_marker_style(signal_type, orig_idx, signal_date)
                    color = style['color']
                    symbol = style['symbol']
                    trace_name = style['name']
                    if style.get('unified_legend'):
                        if signal_type == '龙头入选':
                            showlegend = not leader_entry_seen
                            leader_entry_seen = True
                        elif signal_type == '龙头移除':
                            showlegend = not leader_removal_seen
                            leader_removal_seen = True
                        elif signal_type == _LADDER_SIGNAL_TYPE:
                            showlegend = not ladder_entry_seen
                            ladder_entry_seen = True
                        elif signal_type == _MOMO_SIGNAL_TYPE:
                            showlegend = not momo_seen
                            momo_seen = True
                        elif signal_type == _ZABAN_SIGNAL_TYPE:
                            showlegend = not zaban_seen
                            zaban_seen = True
                        elif signal_type == _ATTENTION_SIGNAL_TYPE:
                            showlegend = not attention_seen
                            attention_seen = True
                        else:
                            showlegend = True
                        legendgroup = style.get('legendgroup')
                    else:
                        showlegend = True
                        legendgroup = None

                    x_at = x_plot[signal_idx]

                    signal_marker = go.Scatter(
                        x=[x_at],
                        y=[signal_price],
                        mode='markers',
                        marker=dict(
                            symbol=symbol,
                            size=15,
                            color=color,
                            line=dict(width=1, color='darkblue')
                        ),
                        name=trace_name,
                        legendgroup=legendgroup,
                        showlegend=showlegend,
                        hoverinfo='skip',
                    )
                    fig.add_trace(signal_marker, row=1, col=1)
                except Exception as e:
                    logging.debug(f"添加信号标记失败 {signal_date}: {e}")

        # 2.5 计算并显示建仓价格区间（默认基于最新信号日MA5；可按信号类型锚定）
        try:
            non_ladder = [
                s for s in signal_dates_info
                if s.get('signal_type') not in (
                    _LADDER_SIGNAL_TYPE, _ZABAN_SIGNAL_TYPE, _ATTENTION_SIGNAL_TYPE
                )
            ]
            anchor_signals = non_ladder if non_ladder else signal_dates_info
            if entry_range_anchor_signal_types:
                allowed = {s.strip() for s in entry_range_anchor_signal_types if s and str(s).strip()}
                filtered = [s for s in anchor_signals if str(s.get('signal_type', '')).strip() in allowed]
                if filtered:
                    anchor_signals = filtered

            latest_signal = max(anchor_signals, key=lambda x: x['signal_date'])
            latest_signal_dt = datetime.strptime(latest_signal['signal_date'], '%Y-%m-%d')
            latest_signal_idx = None
            for i, date in enumerate(dates):
                if date.date() == latest_signal_dt.date():
                    latest_signal_idx = i
                    break

            if latest_signal_idx is not None:
                ma5_at_signal = ma5.iloc[latest_signal_idx]
                entry_low = round(ma5_at_signal * (1 + ENTRY_RANGE_LOW_PCT), 2)
                entry_mid = round(ma5_at_signal * (1 + ENTRY_RANGE_MID_PCT), 2)
                entry_high = round(ma5_at_signal * (1 + ENTRY_RANGE_HIGH_PCT), 2)

                low_pct_str = f"{ENTRY_RANGE_LOW_PCT * 100:+.0f}%"
                mid_pct_str = f"{ENTRY_RANGE_MID_PCT * 100:+.0f}%"
                high_pct_str = f"{ENTRY_RANGE_HIGH_PCT * 100:+.0f}%"

                annotation_text = (
                    f"<b>建仓区间</b><br>"
                    f"MA5({latest_signal['signal_date']}): {ma5_at_signal:.2f}<br>"
                    f"低: {entry_low:.2f}（{low_pct_str}）<br>"
                    f"中: {entry_mid:.2f}（{mid_pct_str}）<br>"
                    f"高: {entry_high:.2f}（{high_pct_str}）"
                )
                fig.add_annotation(
                    text=annotation_text,
                    xref='paper', yref='paper',
                    # 左上角，避免遮挡右侧最新K线
                    x=0.01, y=0.97,
                    xanchor='left', yanchor='top',
                    showarrow=False,
                    bordercolor='#1a6fcd',
                    borderwidth=2,
                    borderpad=6,
                    bgcolor='white',
                    opacity=0.92,
                    font=dict(size=11, color='#1a1a1a'),
                    align='left',
                )

                # 在主图Y轴上绘制建仓区间水平虚线（浅色，不干扰阅读）
                for price_val in (entry_low, entry_mid, entry_high):
                    fig.add_hline(
                        y=price_val, row=1, col=1,
                        line=dict(color='rgba(100,149,237,0.35)', width=1, dash='dash'),
                    )
        except Exception as e:
            logging.debug(f"计算建仓区间失败: {e}")

        # 3. 绘制成交量柱状图
        colors = ['#ff4444' if closes[i] >= opens[i] else '#00aa00'
                  for i in range(len(chart_df))]

        volume_bar = go.Bar(
            x=x_plot,
            y=volumes,
            name='成交量',
            marker_color=colors,
            opacity=0.6,
            hovertext=date_labels,
            hovertemplate='%{hovertext}<br>成交量: %{y}<extra></extra>',
        )
        fig.add_trace(volume_bar, row=2, col=1)

        if has_daily_relative_strength and rs_row is not None:
            rs_line = go.Scatter(
                x=x_plot,
                y=daily_relative_strength_series.tolist(),
                mode='lines',
                name=daily_relative_strength_label,
                line=dict(color='#8e44ad', width=1.8),
                customdata=date_labels,
                hovertemplate='%{customdata}<br>每日相对强弱: %{y:.2f}%<extra></extra>',
            )
            fig.add_trace(rs_line, row=rs_row, col=1)
            fig.add_hline(
                y=0,
                row=rs_row,
                col=1,
                line=dict(color='rgba(142,68,173,0.35)', width=1, dash='dash'),
            )

        # 4. 生成标题
        title = _format_title(
            stock_code, stock_name, signal_dates_info, concepts=concepts,
            zt_limit_up_concepts=zt_limit_up_concepts,
            chart_df=chart_df, data_dir=data_dir,
        )

        # 5. 更新布局
        fig.update_layout(
            title=dict(
                text=title,
                x=0.05,
                xanchor='left',
                font=dict(size=11, color='black')
            ),
            height=660 if has_daily_relative_strength else 600,
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
                font=dict(size=9)
            ),
            hovermode='x unified',
            template='plotly_white',
            xaxis_rangeslider_visible=False,
            margin=dict(l=50, r=30, t=120, b=50)
        )

        # 6. 更新坐标轴
        fig.update_xaxes(title_text="", row=volume_row, col=1)
        fig.update_yaxes(title_text="价格", row=1, col=1, secondary_y=False, title_font=dict(size=10))
        fig.update_yaxes(title_text="成交量", row=volume_row, col=1, title_font=dict(size=10))
        if has_daily_relative_strength and rs_row is not None:
            fig.update_yaxes(title_text=daily_relative_strength_label, row=rs_row, col=1, title_font=dict(size=10))

        # 6.1 主图右侧增加百分比轴（与左侧价格轴同刻度位置）
        try:
            base_price = _resolve_pct_axis_base_price()
            # 主图里信号标记会画在 low*0.95 位置，为避免左/右轴映射不一致，
            # 这里统一按同一价格范围设置左右轴。
            y_min = float(min(lows)) * 0.95
            y_max = float(max(highs))
            tick_count = max(2, int(PCT_AXIS_TICK_COUNT))

            if y_max <= y_min:
                span = max(1e-6, abs(y_min) * 0.001)
                y_min -= span
                y_max += span

            step = (y_max - y_min) / (tick_count - 1)
            tick_vals = [y_min + i * step for i in range(tick_count)]
            tick_pct_vals = [(v / base_price - 1.0) * 100.0 for v in tick_vals]
            tick_text = []
            for pct in tick_pct_vals:
                pct_abs_text = f"{abs(pct):.{PCT_AXIS_DECIMALS}f}%"
                # 去掉正负号，改为颜色区分：红涨绿跌
                if pct > 0:
                    tick_text.append(f"<span style='color:#d62728'>{pct_abs_text}</span>")
                elif pct < 0:
                    tick_text.append(f"<span style='color:#2ca02c'>{pct_abs_text}</span>")
                else:
                    tick_text.append(pct_abs_text)

            # 先固定左轴范围，确保与右侧百分比轴一一对应
            fig.update_yaxes(
                row=1,
                col=1,
                secondary_y=False,
                range=[y_min, y_max],
                autorange=False,
            )

            # 使用 secondary_y 官方机制：右侧百分比轴（与左轴价格同刻度位置）
            fig.update_yaxes(
                row=1,
                col=1,
                secondary_y=True,
                title_text='涨跌幅(%)',
                tickmode='array',
                tickvals=tick_vals,
                ticktext=tick_text,
                range=[y_min, y_max],
                showticklabels=True,
                showline=True,
                ticks='',
                tickfont=dict(size=PCT_AXIS_TICK_FONT_SIZE),
                showgrid=False,
                zeroline=False,
                title_font=dict(size=10),
            )

            # 绑定一个不可见trace到 secondary_y，确保右轴始终被Plotly渲染
            fig.add_trace(
                go.Scatter(
                    x=[x_plot[0], x_plot[-1]],
                    y=[tick_vals[0], tick_vals[-1]],
                    mode='lines',
                    line=dict(width=0),
                    opacity=0,
                    showlegend=False,
                    hoverinfo='skip',
                ),
                row=1,
                col=1,
                secondary_y=True,
            )
        except Exception as e:
            logging.debug(f"右侧百分比轴绘制失败: {e}")

        # 7. x 轴为分类轴：按交易日顺序显示，无节假日空白；刻度约 10 个
        tick_step = max(1, len(chart_df) // 10)
        tick_indices = list(range(0, len(chart_df), tick_step))
        if len(chart_df) - 1 not in tick_indices:
            tick_indices.append(len(chart_df) - 1)
        tick_vals = [x_plot[i] for i in tick_indices]

        for row_idx in range(1, total_rows + 1):
            fig.update_xaxes(
                type='category',
                tickmode='array',
                tickvals=tick_vals,
                ticktext=[date_labels[i] for i in tick_indices],
                tickangle=-45,
                showspikes=True,
                spikemode='across',
                spikesnap='cursor',
                spikethickness=1,
                spikedash='dot',
                spikecolor='rgba(80,80,80,0.6)',
                row=row_idx, col=1,
            )

        # 开启 Y 轴 spike，可在 hover 时显示横向定位虚线
        fig.update_yaxes(
            showspikes=True,
            spikemode='across',
            spikesnap='cursor',
            spikethickness=1,
            spikedash='dot',
            spikecolor='rgba(80,80,80,0.6)',
            row=1, col=1, secondary_y=False
        )
        fig.update_yaxes(
            showspikes=True,
            spikemode='across',
            spikesnap='cursor',
            spikethickness=1,
            spikedash='dot',
            spikecolor='rgba(80,80,80,0.6)',
            row=1, col=1, secondary_y=True
        )
        if has_daily_relative_strength and rs_row is not None:
            fig.update_yaxes(
                showspikes=True,
                spikemode='across',
                spikesnap='cursor',
                spikethickness=1,
                spikedash='dot',
                spikecolor='rgba(80,80,80,0.6)',
                row=rs_row, col=1
            )

        return fig

    except Exception as e:
        logging.error(f"创建图表失败 {stock_code} {stock_name}: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return None


def _create_combined_html(figures: List[go.Figure], titles: List[str],
                          columns: int, rows: int, page_title: str = "策略扫描结果",
                          chart_keys: Optional[List[str]] = None,
                          enable_favorites: bool = False,
                          favorite_storage_key: str = "trading.chart.favorites.v1") -> str:
    """创建包含所有图表的单个HTML文件，使用多个Plotly CDN备用源"""
    import json

    chart_keys = chart_keys or ["" for _ in figures]
    favorite_enabled = enable_favorites and len(chart_keys) == len(figures)
    favorite_storage_key_json = json.dumps(favorite_storage_key, ensure_ascii=False)
    favorites_css = """
        .chart-title {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
        }
        .chart-title-text {
            flex: 1;
            min-width: 0;
        }
        .favorite-btn {
            border: 1px solid #ddd;
            border-radius: 4px;
            background: #fff;
            color: #999;
            cursor: pointer;
            font-size: 18px;
            line-height: 1;
            padding: 3px 7px;
        }
        .favorite-btn:hover {
            border-color: #f0b400;
            color: #f0b400;
        }
        .favorite-btn.is-favorite {
            border-color: #f0b400;
            color: #f0b400;
            background: #fff8d8;
        }
        .chart-container.is-favorite {
            box-shadow: 0 2px 8px rgba(240, 180, 0, 0.35);
        }
""" if favorite_enabled else ""

    # 生成每个图表的JSON数据和div
    chart_data_list = []
    chart_divs = []

    for i, fig in enumerate(figures):
        fig_json_str = fig.to_json()
        fig_dict = json.loads(fig_json_str)
        chart_data_list.append(fig_dict)

        chart_height = int(getattr(fig.layout, 'height', 600) or 600)
        chart_div = (
            f'<div class="chart-plot-wrap">'
            f'<div id="chart_{i}" style="width:100%;height:{chart_height}px;"></div>'
            f'<div id="chart_{i}_hover_line" class="chart-hover-line"></div>'
            f'</div>'
        )
        chart_divs.append(chart_div)

    # 构建完整的HTML，使用多个Plotly CDN备用源
    html_template = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{page_title}</title>
    <!-- 多个Plotly CDN备用源 -->
    <script src="https://cdn.plot.ly/plotly-2.26.0.min.js" 
            onerror="this.onerror=null;this.src='https://cdnjs.cloudflare.com/ajax/libs/plotly.js/2.26.0/plotly.min.js';"></script>
    <script>
        // 如果第一个CDN失败，尝试第二个
        if (typeof Plotly === 'undefined') {{
            var script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/plotly.js/2.26.0/plotly.min.js';
            script.onerror = function() {{
                // 如果第二个也失败，尝试第三个
                script.src = 'https://unpkg.com/plotly.js@2.26.0/dist/plotly.min.js';
            }};
            document.head.appendChild(script);
        }}
    </script>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
            padding: 20px;
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .header h1 {{
            margin: 0;
            color: #333;
        }}
        .header p {{
            margin: 10px 0 0 0;
            color: #666;
        }}
        .header-controls {{
            position: fixed;
            right: 18px;
            top: 12px;
            z-index: 9999;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            color: #444;
            user-select: none;
            background: rgba(255, 255, 255, 0.92);
            border: 1px solid #ddd;
            border-radius: 6px;
            padding: 6px 10px;
        }}
        .header-controls input[type="checkbox"] {{
            width: 14px;
            height: 14px;
            cursor: pointer;
        }}
        .chart-container {{
            background-color: white;
            margin-bottom: 20px;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .chart-title {{
            font-size: 14px;
            font-weight: bold;
            margin-bottom: 10px;
            color: #333;
            padding: 10px;
            background-color: #f9f9f9;
            border-radius: 4px;
        }}
{favorites_css}
        .chart-plot-wrap {{
            position: relative;
        }}
        .chart-hover-line {{
            position: absolute;
            top: 0;
            bottom: 0;
            width: 1px;
            display: none;
            pointer-events: none;
            background: transparent;
            border-left: 1px dashed rgba(120, 120, 120, 0.5);
            z-index: 15;
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="header-controls">
            <label for="toggle-attention-marker">
                <input type="checkbox" id="toggle-attention-marker" checked />
                关注度入榜
            </label>
        </div>
        <h1>{page_title}</h1>
        <p>共 {len(figures)} 只股票</p>
    </div>
    
    <div id="chart-grid" style="display: grid; grid-template-columns: repeat({columns}, 1fr); gap: 20px;">
"""

    # 添加每个图表
    for i, title in enumerate(titles):
        chart_key = chart_keys[i] if i < len(chart_keys) else ""
        favorite_button = (
            f'<button type="button" class="favorite-btn" data-favorite-key="{chart_key}" '
            f'title="收藏并置顶">☆</button>'
        ) if favorite_enabled and chart_key else ""
        title_html = (
            f'<div class="chart-title"><span class="chart-title-text">{title}</span>{favorite_button}</div>'
            if favorite_enabled else
            f'<div class="chart-title">{title}</div>'
        )
        html_template += f"""
        <div class="chart-container" data-chart-key="{chart_key}">
            {title_html}
            {chart_divs[i]}
        </div>
"""

    html_template += """
    </div>
    
    <script>
        const ATTENTION_LEGEND_GROUP = 'attention_rank';
        const FAVORITES_ENABLED = """ + json.dumps(favorite_enabled) + """;
        const FAVORITE_STORAGE_KEY = """ + favorite_storage_key_json + """;

        function bindVerticalHoverGuide(chartEl, guideEl) {
            if (!chartEl || !guideEl || chartEl.__verticalGuideBound) return;
            chartEl.__verticalGuideBound = true;

            const showGuide = (eventData) => {
                if (!eventData || !eventData.event) return;
                const rect = chartEl.getBoundingClientRect();
                const clientX = eventData.event.clientX;
                if (clientX == null) return;

                const left = Math.max(0, Math.min(clientX - rect.left, rect.width));
                guideEl.style.left = `${left}px`;
                guideEl.style.display = 'block';
            };

            const hideGuide = () => {
                guideEl.style.display = 'none';
            };

            chartEl.on('plotly_hover', showGuide);
            chartEl.on('plotly_unhover', hideGuide);
            chartEl.addEventListener('mouseleave', hideGuide);
        }

        function setAttentionMarkerVisible(visible) {
            const chartData = window.__chartDataCache || [];
            chartData.forEach((_, index) => {
                const chartEl = document.getElementById(`chart_${index}`);
                if (!chartEl || !chartEl.data) return;
                const indices = [];
                chartEl.data.forEach((trace, i) => {
                    if (trace && trace.legendgroup === ATTENTION_LEGEND_GROUP) {
                        indices.push(i);
                    }
                });
                if (indices.length > 0) {
                    Plotly.restyle(chartEl, { visible: visible ? true : false }, indices);
                }
            });
        }

        function loadFavoriteKeys() {
            if (!FAVORITES_ENABLED) return [];
            try {
                const raw = localStorage.getItem(FAVORITE_STORAGE_KEY);
                const parsed = raw ? JSON.parse(raw) : [];
                return Array.isArray(parsed) ? parsed.map(String) : [];
            } catch (e) {
                return [];
            }
        }

        function saveFavoriteKeys(keys) {
            if (!FAVORITES_ENABLED) return;
            localStorage.setItem(FAVORITE_STORAGE_KEY, JSON.stringify(keys));
        }

        function applyFavoriteState() {
            if (!FAVORITES_ENABLED) return;
            const favoriteKeys = loadFavoriteKeys();
            const favoriteSet = new Set(favoriteKeys);
            document.querySelectorAll('.chart-container[data-chart-key]').forEach((container) => {
                const key = container.dataset.chartKey;
                const isFavorite = favoriteSet.has(key);
                container.classList.toggle('is-favorite', isFavorite);
                const btn = container.querySelector('.favorite-btn');
                if (btn) {
                    btn.classList.toggle('is-favorite', isFavorite);
                    btn.textContent = isFavorite ? '★' : '☆';
                    btn.setAttribute('aria-pressed', isFavorite ? 'true' : 'false');
                }
            });
        }

        function reorderFavoriteCharts() {
            if (!FAVORITES_ENABLED) return;
            const grid = document.getElementById('chart-grid');
            if (!grid) return;
            const favoriteKeys = loadFavoriteKeys();
            const order = new Map(favoriteKeys.map((key, index) => [key, index]));
            const containers = Array.from(grid.querySelectorAll('.chart-container[data-chart-key]'));
            const favorites = containers
                .filter((container) => order.has(container.dataset.chartKey))
                .sort((a, b) => order.get(a.dataset.chartKey) - order.get(b.dataset.chartKey));
            favorites.forEach((container) => grid.appendChild(container));
            favorites.reverse().forEach((container) => grid.insertBefore(container, grid.firstChild));
        }

        function bindFavoriteControls() {
            if (!FAVORITES_ENABLED) return;
            document.querySelectorAll('.favorite-btn[data-favorite-key]').forEach((button) => {
                button.addEventListener('click', (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    const key = String(button.dataset.favoriteKey || '');
                    if (!key) return;
                    const keys = loadFavoriteKeys();
                    const existingIndex = keys.indexOf(key);
                    if (existingIndex >= 0) {
                        keys.splice(existingIndex, 1);
                    } else {
                        keys.unshift(key);
                    }
                    saveFavoriteKeys(keys);
                    reorderFavoriteCharts();
                    applyFavoriteState();
                });
            });
            reorderFavoriteCharts();
            applyFavoriteState();
        }

        function bindHeaderControls() {
            const checkbox = document.getElementById('toggle-attention-marker');
            if (!checkbox) return;
            checkbox.addEventListener('change', (e) => {
                setAttentionMarkerVisible(!!e.target.checked);
            });
        }

        // 等待Plotly加载完成
        function initCharts() {
            if (typeof Plotly === 'undefined') {
                setTimeout(initCharts, 100);
                return;
            }
            
            const chartData = """ + json.dumps(chart_data_list, ensure_ascii=False) + """;
            window.__chartDataCache = chartData;
            
            chartData.forEach((data, index) => {
                Plotly.newPlot(`chart_${index}`, data.data, data.layout, {
                    responsive: true,
                    displayModeBar: true
                });
                const chartEl = document.getElementById(`chart_${index}`);
                const guideEl = document.getElementById(`chart_${index}_hover_line`);
                bindVerticalHoverGuide(chartEl, guideEl);
            });
            bindHeaderControls();
            bindFavoriteControls();
        }
        
        // 页面加载完成后初始化图表
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initCharts);
        } else {
            initCharts();
        }
    </script>
</body>
</html>"""

    return html_template


def _create_stock_favorite_combined_html(
        figures: List[go.Figure],
        titles: List[str],
        stock_codes: List[str],
        columns: int,
        rows: int,
        page_title: str,
        favorite_scope: str,
) -> str:
    """创建支持按股票代码收藏置顶的组合HTML。"""
    return _create_combined_html(
        figures,
        titles,
        columns,
        rows,
        page_title=page_title,
        chart_keys=stock_codes,
        enable_favorites=True,
        favorite_storage_key=f"trading.{favorite_scope}.favorites.v1",
    )


def generate_strategy_scan_html_charts(
        base_dir: str,
        recent_days: int = 10,
        columns: int = 2,
        before_days: int = DEFAULT_BEFORE_DAYS,
        after_days: int = DEFAULT_AFTER_DAYS,
        output_dir: Optional[str] = None,
        data_dir: str = './data/astocks'
) -> Optional[str]:
    """
    生成策略扫描结果的HTML交互式图表
    
    按股票分组，每只股票一张图，可以显示多个信号日期。
    一次执行只生成一个HTML文件。
    
    Args:
        base_dir: 扫描结果基础目录（如 'bin/candidate_stocks_breakout_a'）
        recent_days: 只处理最近几天的信号，默认10天
        columns: 横向并排显示的列数（1、2或3），默认2
        before_days: 信号日前显示的交易日数，默认60
        after_days: 信号日后显示的交易日数，默认30
        output_dir: 输出目录，如果为None则使用 base_dir/html_charts
        data_dir: 股票数据目录
        
    Returns:
        str: 生成的HTML文件路径，失败返回None
    """
    if columns not in [1, 2, 3]:
        logging.warning(f"列数 {columns} 无效，使用默认值2")
        columns = 2

    # 查找最新的summary文件
    summary_files = [f for f in os.listdir(base_dir) if
                     f.startswith('scan_summary_') and f.endswith('.txt')]

    if not summary_files:
        logging.error(f"在目录 {base_dir} 中没有找到scan_summary文件")
        return None

    # 选择最新的summary文件
    latest_summary = sorted(summary_files)[-1]
    summary_path = os.path.join(base_dir, latest_summary)

    logging.info(f"使用summary文件: {summary_path}")

    # 解析summary文件，按股票分组
    stock_signals_map = parse_scan_summary(summary_path)

    if not stock_signals_map:
        logging.error("没有找到有效的股票信号数据")
        return None

    # 过滤：只保留最近recent_days天的信号
    current_date = get_current_or_prev_trading_day(datetime.now().strftime("%Y%m%d"))
    if current_date and "-" in current_date:
        current_date = current_date.replace("-", "")

    filtered_stocks = {}
    for code, signals in stock_signals_map.items():
        # 只保留最近recent_days天的信号
        recent_signals = []
        for sig in signals:
            signal_date_yyyymmdd = sig['signal_date'].replace("-", "")
            if current_date and signal_date_yyyymmdd >= current_date:
                # 如果是今天或未来的日期，保留
                recent_signals.append(sig)
            else:
                # 计算日期差（简化处理，假设每天都是交易日）
                try:
                    sig_dt = datetime.strptime(signal_date_yyyymmdd, '%Y%m%d')
                    curr_dt = datetime.strptime(current_date, '%Y%m%d') if current_date else datetime.now()
                    days_diff = (curr_dt - sig_dt).days
                    if days_diff <= recent_days * 2:  # 粗略估算，包含非交易日
                        recent_signals.append(sig)
                except:
                    recent_signals.append(sig)

        if recent_signals:
            filtered_stocks[code] = recent_signals

    if not filtered_stocks:
        logging.warning("过滤后没有找到符合条件的股票")
        return None

    logging.info(f"处理 {len(filtered_stocks)} 只股票")

    from utils.export_ladder_entry import load_ladder_entry_dates

    ladder_map = load_ladder_entry_dates(DEFAULT_LADDER_ENTRY_JSON)
    if ladder_map:
        logging.info(f"已加载天梯入选侧车: {len(ladder_map)} 只股票（作图使用每只股票列表中的首个日期）")

    # 设置输出目录
    if output_dir is None:
        output_dir = os.path.join(base_dir, 'html_charts')
    os.makedirs(output_dir, exist_ok=True)

    # 加载概念映射（可选，失败不影响主流程）
    _concept_lookup = {}
    try:
        from fetch.stock_concept_map import get_stock_concepts, is_map_available
        if is_map_available():
            _concept_lookup = {code: get_stock_concepts(code) for code in filtered_stocks}
            logging.info(f"概念映射已加载，覆盖 {sum(1 for v in _concept_lookup.values() if v)} 只股票")
        else:
            logging.info("概念映射文件不存在，跳过概念标签（可运行 fetch_stock_concept_map() 生成）")
    except Exception as _e:
        logging.warning(f"加载概念映射失败，跳过概念标签: {_e}")

    chart_figures = []
    chart_titles = []

    # 为每只股票生成图表
    for stock_code, signals_info in filtered_stocks.items():
        try:
            stock_name = signals_info[0]['name']  # 使用第一个信号的名称
            signals_for_chart = _merge_ladder_entry_into_signals(stock_code, signals_info, ladder_map)

            # 找到所有信号日期的最早和最晚日期（含天梯入选）
            signal_dates = [sig['signal_date'] for sig in signals_for_chart]
            earliest_date = min(signal_dates)
            latest_date = max(signal_dates)

            # 计算绘图范围：从最早信号前before_days天到最晚信号后after_days天
            earliest_date_yyyymmdd = earliest_date.replace("-", "")
            latest_date_yyyymmdd = latest_date.replace("-", "")

            chart_start = get_n_trading_days_before(earliest_date_yyyymmdd, before_days)
            chart_end_str = latest_date_yyyymmdd

            for _ in range(after_days):
                next_day = get_next_trading_day(chart_end_str)
                if next_day:
                    chart_end_str = next_day
                else:
                    break

            # 读取股票数据
            stock_data = read_stock_data(stock_code, data_dir)
            if stock_data is None or stock_data.empty:
                logging.warning(f"未找到股票 {stock_code} {stock_name} 的数据文件")
                continue

            # 截取数据范围
            chart_start_dt = datetime.strptime(chart_start.replace('-', ''), '%Y%m%d')
            chart_end_dt = datetime.strptime(chart_end_str, '%Y%m%d')

            chart_df = stock_data.loc[chart_start_dt:chart_end_dt].copy()

            if chart_df.empty:
                logging.warning(f"股票 {stock_code} {stock_name} 在指定日期范围内无数据")
                continue

            # 清理停牌数据
            chart_df = chart_df.dropna(subset=['Open', 'High', 'Low', 'Close'])

            if chart_df.empty:
                logging.warning(f"股票 {stock_code} {stock_name} 清理停牌数据后无有效数据")
                continue

            # 查询所属概念
            concepts = _concept_lookup.get(stock_code) or []

            # 创建图表figure（包含所有信号日期）
            fig = _create_single_chart_figure(
                stock_code=stock_code,
                stock_name=stock_name,
                chart_df=chart_df,
                signal_dates_info=signals_for_chart,
                before_days=before_days,
                after_days=after_days,
                data_dir=data_dir,
                concepts=concepts,
            )

            if fig is not None:
                chart_figures.append(fig)
                # 生成卡片标题（概念标签已在图表内标题中显示，此处不重复）
                signal_count = len(signals_for_chart)
                title = f"{stock_code} {stock_name} ({signal_count}个信号)"
                chart_titles.append(title)

        except Exception as e:
            logging.error(f"生成股票 {stock_code} 的HTML图表失败: {e}")
            import traceback
            logging.error(traceback.format_exc())
            continue

    if not chart_figures:
        logging.warning("没有可用的图表，跳过HTML生成")
        return None

    # 计算网格布局
    num_charts = len(chart_figures)
    rows = (num_charts + columns - 1) // columns

    # 创建包含所有图表的HTML
    html_content = _create_combined_html(chart_figures, chart_titles, columns, rows)

    # 保存HTML文件（只生成一个文件）
    html_filename = f"strategy_scan_{columns}cols.html"
    html_path = os.path.join(output_dir, html_filename)

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    logging.info(f"HTML图表生成完成: {html_path} (共 {num_charts} 个图表)")
    return html_path


if __name__ == '__main__':
    # 测试代码
    base_dir = 'bin/candidate_stocks_breakout_a'
    file = generate_strategy_scan_html_charts(
        base_dir=base_dir,
        recent_days=15,
        columns=2,
        before_days=60,
        after_days=30
    )

    if file:
        print(f"\n✅ 成功生成HTML文件: {file}")
    else:
        print("❌ 没有生成HTML文件")
