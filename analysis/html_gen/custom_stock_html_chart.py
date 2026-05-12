"""
自选股票 HTML 交互图表生成器。

输入格式保持简单：每行一个 6 位股票代码。
"""

from __future__ import annotations

import logging
import os
import webbrowser
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from analysis.html_gen.strategy_scan_html_chart import (
    _create_single_chart_figure,
    _create_stock_favorite_combined_html,
)
from utils.backtrade.visualizer import read_stock_data
from utils.date_util import format_date, get_n_trading_days_before, get_next_trading_day

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')


def parse_stock_codes(raw_text: str) -> Tuple[List[str], List[str]]:
    """按行解析股票代码，去重并保留原始顺序。"""
    codes: List[str] = []
    invalid_lines: List[str] = []
    seen = set()

    for line in raw_text.splitlines():
        code = line.strip()
        if not code:
            continue
        if len(code) == 6 and code.isdigit():
            if code not in seen:
                seen.add(code)
                codes.append(code)
        else:
            invalid_lines.append(code)

    return codes, invalid_lines


def _find_stock_name(stock_code: str, data_dir: str) -> str:
    """从本地行情文件名中尽量取股票名称，如 600519_贵州茅台.csv。"""
    try:
        for filename in os.listdir(data_dir):
            if not filename.startswith(stock_code) or not filename.endswith('.csv'):
                continue
            base = os.path.splitext(filename)[0]
            if '_' in base:
                return base.split('_', 1)[1]
            break
    except FileNotFoundError:
        return ''
    return ''


def _resolve_anchor_date(stock_data, anchor_date: Optional[str]) -> str:
    if anchor_date:
        formatted = format_date(anchor_date)
        if not formatted:
            raise ValueError(f"无法解析锚定日期: {anchor_date}")
        return formatted

    return stock_data.index.max().strftime('%Y-%m-%d')


def generate_custom_stock_html_charts(
        stock_codes_text: str,
        columns: int = 2,
        before_days: int = 60,
        after_days: int = 30,
        output_dir: str = './excel/html_charts',
        data_dir: str = './data/astocks',
        anchor_date: Optional[str] = None,
) -> Optional[str]:
    """
    根据手动输入的股票代码生成 HTML 图表。

    stock_codes_text: 每行一个 6 位股票代码。
    anchor_date: 可选锚定日期；为空时使用每只股票本地数据的最新交易日。
    """
    if columns not in [1, 2, 3]:
        logging.warning(f"列数 {columns} 无效，使用默认值2")
        columns = 2

    stock_codes, invalid_lines = parse_stock_codes(stock_codes_text)
    if invalid_lines:
        logging.warning(f"忽略无效股票代码行: {invalid_lines}")
    if not stock_codes:
        logging.warning("未输入有效股票代码")
        return None

    os.makedirs(output_dir, exist_ok=True)

    chart_figures = []
    chart_titles = []
    chart_codes = []

    concept_lookup: Dict[str, List[str]] = {}
    try:
        from fetch.stock_concept_map import get_stock_concepts, is_map_available
        if is_map_available():
            concept_lookup = {code: get_stock_concepts(code) for code in stock_codes}
            logging.info(f"概念映射已加载，覆盖 {sum(1 for v in concept_lookup.values() if v)} 只股票")
        else:
            logging.info("概念映射文件不存在，跳过概念标签")
    except Exception as e:
        logging.warning(f"加载概念映射失败，跳过概念标签: {e}")

    fupan_zt_raw: Dict[str, str] = {}
    _zt_to_tags = None
    try:
        from analysis.loader.fupan_data_loader import load_zt_concept_by_stock_code, zt_concept_string_to_tags
        fupan_zt_raw = load_zt_concept_by_stock_code()
        _zt_to_tags = zt_concept_string_to_tags
    except Exception as e:
        logging.warning(f"加载复盘涨停概念失败，将仅用同花顺概念映射: {e}")

    for stock_code in stock_codes:
        try:
            stock_name = _find_stock_name(stock_code, data_dir)
            stock_data = read_stock_data(stock_code, data_dir)
            if stock_data is None or stock_data.empty:
                logging.warning(f"未找到股票数据: {stock_code}")
                continue

            stock_data = stock_data.dropna(subset=['Open', 'High', 'Low', 'Close']).sort_index()
            if stock_data.empty:
                logging.warning(f"股票 {stock_code} 清理停牌数据后无有效数据")
                continue

            signal_date = _resolve_anchor_date(stock_data, anchor_date)
            signal_date_ymd = signal_date.replace('-', '')
            chart_start = get_n_trading_days_before(signal_date_ymd, before_days)
            chart_end = signal_date_ymd
            for _ in range(after_days):
                next_day = get_next_trading_day(chart_end)
                if not next_day:
                    break
                chart_end = next_day

            start_dt = datetime.strptime(chart_start.replace('-', ''), '%Y%m%d')
            end_dt = datetime.strptime(chart_end, '%Y%m%d')
            chart_df = stock_data.loc[start_dt:end_dt].copy()
            if chart_df.empty:
                logging.warning(f"股票 {stock_code} 在指定日期范围内无数据")
                continue

            signals = [{
                'code': stock_code,
                'name': stock_name,
                'signal_date': signal_date,
                'signal_type': '自选',
                'price': None,
                'details': '用户输入',
            }]

            raw_zt = fupan_zt_raw.get(stock_code)
            zt_tags: List[str] = []
            if raw_zt and _zt_to_tags:
                zt_tags = _zt_to_tags(raw_zt)

            fig = _create_single_chart_figure(
                stock_code=stock_code,
                stock_name=stock_name,
                chart_df=chart_df,
                signal_dates_info=signals,
                before_days=before_days,
                after_days=after_days,
                data_dir=data_dir,
                concepts=concept_lookup.get(stock_code) or [],
                zt_limit_up_concepts=zt_tags if zt_tags else None,
            )
            if fig is None:
                continue

            chart_figures.append(fig)
            chart_codes.append(stock_code)
            # 页面上方灰底标题栏只显示本列表文字；Plotly 内 layout.title 含完整 HTML，
            # 易被用户忽略或与工具栏重叠，故外层至少同步「代码 名称 + 涨停概念」纯文本。
            _outer_zt = f" [{'+'.join(zt_tags)}]" if zt_tags else ""
            chart_titles.append(f"{stock_code} {stock_name}{_outer_zt}".strip())

        except Exception as e:
            logging.error(f"生成股票图失败 {stock_code}: {e}")
            continue

    if not chart_figures:
        logging.warning("没有可用图表，未生成HTML")
        return None

    rows = (len(chart_figures) + columns - 1) // columns
    html_content = _create_stock_favorite_combined_html(
        chart_figures,
        chart_titles,
        chart_codes,
        columns,
        rows,
        page_title="自选股票",
        favorite_scope="custom_stock",
    )

    html_filename = f"custom_stocks_{columns}cols.html"
    html_path = os.path.join(output_dir, html_filename)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    logging.info(f"自选股票 HTML生成完成: {html_path}（共 {len(chart_figures)} 只）")
    return html_path


def launch_custom_stock_chart_app() -> None:
    """启动一个简单的桌面输入框，粘贴股票代码后生成 HTML 图表。"""
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("自选股票 HTML 图表")
    root.geometry("420x520")

    frame = ttk.Frame(root, padding=12)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text="股票代码（每行一个）").pack(anchor=tk.W)
    text_box = tk.Text(frame, height=18, width=44)
    text_box.pack(fill=tk.BOTH, expand=True, pady=(6, 10))

    options = ttk.Frame(frame)
    options.pack(fill=tk.X, pady=(0, 10))

    ttk.Label(options, text="列数").grid(row=0, column=0, sticky=tk.W)
    columns_var = tk.StringVar(value="2")
    ttk.Entry(options, textvariable=columns_var, width=8).grid(row=0, column=1, padx=(6, 18))

    ttk.Label(options, text="前置交易日").grid(row=0, column=2, sticky=tk.W)
    before_var = tk.StringVar(value="60")
    ttk.Entry(options, textvariable=before_var, width=8).grid(row=0, column=3, padx=(6, 0))

    ttk.Label(options, text="后置交易日").grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
    after_var = tk.StringVar(value="30")
    ttk.Entry(options, textvariable=after_var, width=8).grid(row=1, column=1, padx=(6, 18), pady=(8, 0))

    ttk.Label(options, text="锚定日期(可空)").grid(row=1, column=2, sticky=tk.W, pady=(8, 0))
    anchor_var = tk.StringVar(value="")
    ttk.Entry(options, textvariable=anchor_var, width=12).grid(row=1, column=3, padx=(6, 0), pady=(8, 0))

    status_var = tk.StringVar(value="粘贴代码后点击生成")
    ttk.Label(frame, textvariable=status_var).pack(anchor=tk.W, pady=(0, 8))

    def on_generate() -> None:
        try:
            html_path = generate_custom_stock_html_charts(
                stock_codes_text=text_box.get("1.0", tk.END),
                columns=int(columns_var.get().strip() or "2"),
                before_days=int(before_var.get().strip() or "60"),
                after_days=int(after_var.get().strip() or "30"),
                anchor_date=anchor_var.get().strip() or None,
            )
        except Exception as e:
            messagebox.showerror("生成失败", str(e))
            return

        if not html_path:
            messagebox.showwarning("未生成", "没有可用图表，请检查股票代码或本地行情数据。")
            return

        abs_path = os.path.abspath(html_path)
        status_var.set(f"已生成: {abs_path}")
        webbrowser.open(abs_path)

    ttk.Button(frame, text="生成图表", command=on_generate).pack(fill=tk.X)

    root.mainloop()
