"""
龙头sheet全量HTML交互图表生成器

数据来源：
- excel/ladder_analysis.xlsx 中所有“龙头xxxx”工作表

功能：
- 读取全部龙头sheet，提取所有曾入选的股票
- 基于每日快照计算“入选日”和“移除日”事件（支持多次进出）
- 生成与策略扫描一致风格的K线+成交量HTML图表
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from openpyxl import load_workbook

from analysis.html_gen.strategy_scan_html_chart import (
    _create_combined_html,
    _create_single_chart_figure,
)
from fetch.stock_concept_map import get_stock_concepts, is_map_available
from utils.backtrade.visualizer import read_stock_data
from utils.date_util import get_n_trading_days_before, get_next_trading_day

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')


def _extract_date_from_header(header_val: object) -> Optional[str]:
    """从表头单元格提取 YYYY-MM-DD 日期字符串。"""
    if not header_val:
        return None
    text = str(header_val).strip()
    if not text:
        return None

    first_line = text.split('\n')[0].strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', first_line):
        return first_line
    return None


def _infer_snapshot_date_from_sheet_name(sheet_name: str, header_dates: List[str]) -> Optional[str]:
    """
    从工作表名“龙头MMDD”推断快照日期（YYYY-MM-DD）。

    说明：
    - 历史龙头sheet会被回填最新日期列，不能用“最大表头日期”作为该sheet快照日。
    - 优先根据sheet名中的MMDD，在表头日期中寻找同月同日并选择最早年份（通常是该sheet创建日）。
    """
    m = re.search(r'^龙头(\d{2})(\d{2})$', str(sheet_name).strip())
    if not m:
        return None

    mm = int(m.group(1))
    dd = int(m.group(2))
    if not header_dates:
        return None

    matched = []
    for d in header_dates:
        try:
            dt = datetime.strptime(d, '%Y-%m-%d')
        except Exception:
            continue
        if dt.month == mm and dt.day == dd:
            matched.append(dt)

    if matched:
        matched.sort()
        return matched[0].strftime('%Y-%m-%d')

    # 兜底：若表头中不存在同MMDD（极少数异常sheet），按当前年推一个日期
    year = datetime.now().year
    try:
        dt = datetime(year, mm, dd)
        return dt.strftime('%Y-%m-%d')
    except Exception:
        return None


def _parse_leader_sheet_snapshot(sheet_name: str, ws) -> Tuple[Optional[str], Dict[str, Dict]]:
    """
    解析单个龙头sheet快照。

    Returns:
        (snapshot_date, stock_map)
        snapshot_date: 该sheet所代表的日期(YYYY-MM-DD)，取表头中最大日期
        stock_map: {code: {'code','name','sheet_concept'}}
    """
    # 识别日期列（第5列开始通常是交易日列）
    header_dates: List[str] = []
    for col_idx in range(5, ws.max_column + 1):
        date_str = _extract_date_from_header(ws.cell(row=1, column=col_idx).value)
        if date_str:
            header_dates.append(date_str)

    if not header_dates:
        return None, {}

    # 快照日期优先取“龙头MMDD”的推断结果，避免被历史回填列污染
    snapshot_date = _infer_snapshot_date_from_sheet_name(sheet_name, header_dates)
    if not snapshot_date:
        # 兼容异常命名sheet，最后兜底才使用最大表头日期
        snapshot_date = max(header_dates)
    stock_map: Dict[str, Dict] = {}

    for row_idx in range(4, ws.max_row + 1):
        code_val = ws.cell(row=row_idx, column=1).value
        if code_val is None:
            continue
        code = str(code_val).strip()
        if not re.match(r'^\d{6}$', code):
            continue

        name = str(ws.cell(row=row_idx, column=3).value or '').strip()
        sheet_concept = str(ws.cell(row=row_idx, column=2).value or '').strip()
        stock_map[code] = {
            'code': code,
            'name': name,
            'sheet_concept': sheet_concept,
        }

    return snapshot_date, stock_map


def _load_all_leader_snapshots(excel_path: str) -> List[Dict]:
    """加载全部龙头sheet快照并按日期排序。"""
    wb = load_workbook(excel_path, data_only=True)

    snapshots: List[Dict] = []
    for sheet_name in wb.sheetnames:
        if not str(sheet_name).startswith("龙头"):
            continue

        ws = wb[sheet_name]
        snapshot_date, stock_map = _parse_leader_sheet_snapshot(sheet_name, ws)
        if not snapshot_date:
            logging.warning(f"跳过sheet {sheet_name}：未识别到有效日期")
            continue

        snapshots.append({
            'sheet_name': sheet_name,
            'snapshot_date': snapshot_date,
            'stock_map': stock_map,
        })

    snapshots.sort(key=lambda x: x['snapshot_date'])
    return snapshots


def _build_stock_signals_from_snapshots(snapshots: List[Dict]) -> Dict[str, List[Dict]]:
    """
    从每日龙头快照构建股票事件序列。

    事件定义：
    - 入选日：当日存在，前一日不存在
    - 移除日：当日不存在，前一日存在
    """
    if not snapshots:
        return {}

    all_codes = set()
    stock_meta: Dict[str, Dict] = {}
    for snap in snapshots:
        for code, info in snap['stock_map'].items():
            all_codes.add(code)
            if code not in stock_meta:
                stock_meta[code] = {
                    'name': info.get('name', ''),
                    'sheet_concept': info.get('sheet_concept', ''),
                }
            else:
                # 如果后续sheet名称更完整，则更新
                if not stock_meta[code].get('name') and info.get('name'):
                    stock_meta[code]['name'] = info.get('name')
                if not stock_meta[code].get('sheet_concept') and info.get('sheet_concept'):
                    stock_meta[code]['sheet_concept'] = info.get('sheet_concept')

    stock_signals_map: Dict[str, List[Dict]] = {}

    for code in all_codes:
        name = stock_meta.get(code, {}).get('name', '')
        sheet_concept = stock_meta.get(code, {}).get('sheet_concept', '')
        prev_in = False
        signals: List[Dict] = []

        for snap in snapshots:
            current_in = code in snap['stock_map']
            signal_date = snap['snapshot_date']

            if current_in and not prev_in:
                signals.append({
                    'code': code,
                    'name': name,
                    'signal_date': signal_date,
                    'signal_type': '龙头入选',
                    'price': None,
                    'details': f"来源: {snap['sheet_name']}",
                    'sheet_concept': sheet_concept,
                })
            elif (not current_in) and prev_in:
                signals.append({
                    'code': code,
                    'name': name,
                    'signal_date': signal_date,
                    'signal_type': '龙头移除',
                    'price': None,
                    'details': f"来源: {snap['sheet_name']}",
                    'sheet_concept': sheet_concept,
                })

            prev_in = current_in

        if signals:
            stock_signals_map[code] = signals

    return stock_signals_map


def _latest_leader_entry_date(signals: List[Dict]) -> str:
    """最近一次龙头入选日；无入选事件时退回全部信号中的最大日期。"""
    dates = [s['signal_date'] for s in signals if s.get('signal_type') == '龙头入选']
    if dates:
        return max(dates)
    return max(s['signal_date'] for s in signals)


def _sheet_concept_for_latest_entry(signals: List[Dict]) -> str:
    """以最近一次龙头入选为基准取 sheet 题材概念列。"""
    entries = [s for s in signals if s.get('signal_type') == '龙头入选']
    if not entries:
        return (signals[0].get('sheet_concept', '') if signals else '') or ''
    latest = max(entries, key=lambda x: x['signal_date'])
    return str(latest.get('sheet_concept', '') or '')


def generate_leader_sheet_html_charts(
        excel_path: str = './excel/ladder_analysis.xlsx',
        columns: int = 2,
        before_days: int = 60,
        after_days: int = 30,
        output_dir: str = './excel/html_charts',
        data_dir: str = './data/astocks',
) -> Optional[str]:
    """
    从全部龙头sheet生成全量HTML图表（包含入选/移除标记）。
    """
    if columns not in [1, 2, 3]:
        logging.warning(f"列数 {columns} 无效，使用默认值2")
        columns = 2

    if not os.path.exists(excel_path):
        logging.error(f"Excel文件不存在: {excel_path}")
        return None

    snapshots = _load_all_leader_snapshots(excel_path)
    if not snapshots:
        logging.error("未找到可用的龙头sheet")
        return None

    stock_signals_map = _build_stock_signals_from_snapshots(snapshots)
    if not stock_signals_map:
        logging.warning("未提取到有效的入选/移除信号")
        return None

    os.makedirs(output_dir, exist_ok=True)

    # 标准概念映射（可选）
    concept_lookup: Dict[str, List[str]] = {}
    try:
        if is_map_available():
            concept_lookup = {code: get_stock_concepts(code) for code in stock_signals_map}
    except Exception as e:
        logging.warning(f"加载概念映射失败，跳过标准概念标签: {e}")

    chart_figures = []
    chart_titles = []

    # 排序：按最近一次「龙头入选」日期倒序；无入选则按最后一条信号日期
    sorted_codes = sorted(
        stock_signals_map.keys(),
        key=lambda c: _latest_leader_entry_date(stock_signals_map[c]),
        reverse=True,
    )

    for stock_code in sorted_codes:
        signals_info = stock_signals_map[stock_code]
        try:
            stock_name = signals_info[0].get('name', '')

            # 同股去重：同一天同类型只保留一次
            uniq = {}
            for sig in signals_info:
                k = (sig['signal_date'], sig['signal_type'])
                if k not in uniq:
                    uniq[k] = sig
            dedup_signals = sorted(uniq.values(), key=lambda x: x['signal_date'])

            signal_dates = [sig['signal_date'] for sig in dedup_signals]
            earliest_date = min(signal_dates)
            latest_date = max(signal_dates)

            earliest_date_yyyymmdd = earliest_date.replace('-', '')
            latest_date_yyyymmdd = latest_date.replace('-', '')

            chart_start = get_n_trading_days_before(earliest_date_yyyymmdd, before_days)
            chart_end = latest_date_yyyymmdd
            for _ in range(after_days):
                next_day = get_next_trading_day(chart_end)
                if not next_day:
                    break
                chart_end = next_day

            stock_data = read_stock_data(stock_code, data_dir)
            if stock_data is None or stock_data.empty:
                logging.warning(f"未找到股票数据: {stock_code} {stock_name}")
                continue

            start_dt = datetime.strptime(chart_start.replace('-', ''), '%Y%m%d')
            end_dt = datetime.strptime(chart_end, '%Y%m%d')
            chart_df = stock_data.loc[start_dt:end_dt].copy()
            chart_df = chart_df.dropna(subset=['Open', 'High', 'Low', 'Close'])
            if chart_df.empty:
                continue

            concepts = concept_lookup.get(stock_code) or []
            fig = _create_single_chart_figure(
                stock_code=stock_code,
                stock_name=stock_name,
                chart_df=chart_df,
                signal_dates_info=dedup_signals,
                before_days=before_days,
                after_days=after_days,
                data_dir=data_dir,
                concepts=concepts,
            )
            if fig is None:
                continue

            chart_figures.append(fig)
            # 卡片标题：以最近一次龙头入选为基准的题材概念
            sheet_concept = _sheet_concept_for_latest_entry(dedup_signals)
            if sheet_concept:
                title = f"{stock_code} {stock_name} | {sheet_concept}"
            else:
                title = f"{stock_code} {stock_name}"
            chart_titles.append(title)

        except Exception as e:
            logging.error(f"生成股票图失败 {stock_code}: {e}")
            continue

    if not chart_figures:
        logging.warning("没有可用图表，未生成HTML")
        return None

    rows = (len(chart_figures) + columns - 1) // columns
    html_content = _create_combined_html(chart_figures, chart_titles, columns, rows)

    html_filename = f"leader_sheet_all_{columns}cols.html"
    html_path = os.path.join(output_dir, html_filename)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    logging.info(f"龙头sheet HTML生成完成: {html_path}（共 {len(chart_figures)} 只）")
    return html_path

