"""日常复盘滚动窗口与换档归档。

日常查看窗口固定为最近约一季交易日；产物用固定文件名覆盖。
回看旧时间段：打开 excel/daily_history/{start}_{end}/ 下的文件。
"""

import glob
import logging
import os
import re
import shutil
from datetime import datetime

import pandas as pd
from openpyxl import load_workbook

from fetch.tonghuashun.fupan_cleaner import clean_all_fupan_files
from utils.date_util import (
    get_latest_trade_date,
    get_n_trading_days_before,
    get_next_trading_day,
    get_trading_days,
)

LOOKBACK_TRADING_DAYS = 60  # 约一季
LADDER_SHEET_NAME = '涨停梯队'
HISTORY_DIR = './excel/daily_history'
ROTATE_MARKER = os.path.join(HISTORY_DIR, 'last_rotate.txt')
FUPAN_PNG = './images/fupan_lb.png'
FUPAN_HTML = './images/fupan_lb.html'
STATS_PLOT_PREFIX = './images/market_analysis'
REASONS_FILE = './data/reasons/unique_reasons_latest.json'
MARKET_ANALYSIS_FILE = './excel/market_analysis.xlsx'
ARTIFACTS = [
    './excel/ladder_analysis.xlsx',
    './excel/ladder_analysis_龙头归档.xlsx',
    './excel/fupan_analysis.xlsx',
    MARKET_ANALYSIS_FILE,
    './excel/html_charts/leader_sheet_all_2cols.html',
    './excel/html_charts/momo_concept_group_all_2cols.html',
    FUPAN_PNG,
    FUPAN_HTML,
    REASONS_FILE,
]


def window_dates():
    """日常查看窗口：最近 LOOKBACK_TRADING_DAYS 个交易日（含最新交易日）。"""
    end_date = get_latest_trade_date()
    if not end_date:
        end_date = datetime.now().strftime('%Y%m%d')
    start = get_n_trading_days_before(end_date, LOOKBACK_TRADING_DAYS - 1)
    start_date = start.replace('-', '')
    return start_date, end_date


def drop_stale_ladder_period_sheets(output_file, keep_name=LADDER_SHEET_NAME):
    """滚动窗口改用固定 sheet 名后，清掉旧的「涨停梯队YYYYMM」残留页。"""
    if not os.path.exists(output_file):
        return
    wb = load_workbook(output_file)
    pat = re.compile(r'^涨停梯队\d{6}(_概念分组)?$')
    keep = {keep_name, f'{keep_name}_概念分组'}
    removed = [title for title in wb.sheetnames if title not in keep and pat.match(title)]
    if not removed:
        wb.close()
        return
    for title in removed:
        wb.remove(wb[title])
    wb.save(output_file)
    wb.close()
    print(f"已移除过期天梯 sheet: {removed}")


def trim_excel_rows_by_date(excel_path, start_date, date_col='日期'):
    """裁掉增量 Excel 中早于窗口起点的行。"""
    if not os.path.exists(excel_path):
        return
    df = pd.read_excel(excel_path)
    if date_col not in df.columns:
        return
    normalized = (
        df[date_col].astype(str)
        .str.replace(r'\D', '', regex=True)
        .str[:8]
    )
    before = len(df)
    df = df[normalized >= str(start_date)].copy()
    if len(df) >= before:
        return
    df.to_excel(excel_path, index=False)
    print(f"已裁剪 {excel_path} 至 {start_date} 起：{before} → {len(df)} 行")


def rotate_artifacts():
    """
    一键归档当前日常产物（复制，不删除当前文件）。
    回看旧时间段：打开 excel/daily_history/{start}_{end}/ 下的文件即可。
    不放入 daily_routine，需手动在 __main__ 中调用。
    """
    start_date, end_date = window_dates()
    dest_dir = os.path.join(HISTORY_DIR, f'{start_date}_{end_date}')
    os.makedirs(dest_dir, exist_ok=True)
    print(f"=== 换档归档到 {dest_dir} ===")

    copied = []
    for src in ARTIFACTS:
        if os.path.exists(src):
            dst = os.path.join(dest_dir, os.path.basename(src))
            shutil.copy2(src, dst)
            copied.append(os.path.basename(src))
            print(f"  已复制: {src}")
        else:
            print(f"  跳过（不存在）: {src}")

    for png in glob.glob(f'{STATS_PLOT_PREFIX}_*.png'):
        dst = os.path.join(dest_dir, os.path.basename(png))
        shutil.copy2(png, dst)
        copied.append(os.path.basename(png))
        print(f"  已复制: {png}")

    with open(ROTATE_MARKER, 'w', encoding='utf-8') as f:
        f.write(f'{start_date}\t{end_date}\t{datetime.now().isoformat(timespec="seconds")}\n')

    print("正在裁剪复盘源数据（fupan_stocks）到当前窗口...")
    clean_all_fupan_files(keep_days=LOOKBACK_TRADING_DAYS, dry_run=False)

    print(f"\n=== 换档完成，共归档 {len(copied)} 个文件 ===")
    print(f"回看请打开: {dest_dir}")
    print("当前日常文件保留，下次 daily_routine 会按滚动窗口覆盖生成。")
    return dest_dir


def maybe_remind_rotate():
    """daily_routine 全部步骤结束后提醒一次：窗口已满一季、可以换档归档。"""
    _, end_date = window_dates()
    last_end = None
    if os.path.exists(ROTATE_MARKER):
        with open(ROTATE_MARKER, 'r', encoding='utf-8') as f:
            parts = f.read().strip().split('\t')
        if len(parts) >= 2:
            last_end = parts[1]

    if not last_end:
        msg = ("[提醒] 尚未做过换档归档。滚动窗口会把窗口外的日常产物移出当前文件；"
               "若需回看请先运行 rotate_daily_artifacts()。")
        print(msg)
        logging.info(msg)
        return

    next_day = get_next_trading_day(last_end)
    if not next_day or next_day > end_date:
        return
    elapsed = len(get_trading_days(next_day, end_date))
    if elapsed >= LOOKBACK_TRADING_DAYS:
        msg = (f"[提醒] 距上次换档已约 {elapsed} 个交易日"
               f"（窗口 {LOOKBACK_TRADING_DAYS} 日），"
               f"可运行 rotate_daily_artifacts() 归档当前产物。")
        print(msg)
        logging.info(msg)
