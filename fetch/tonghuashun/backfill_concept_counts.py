# -*- coding: utf-8 -*-
"""
历史热门概念计数回填脚本

从 images/wordcloud/hot/ 目录中已存在的 {date}_concept.png 提取日期列表，
用问财逐日拉取涨停数据，计算概念计数并写入
data/concepts_data/hot_concept_counts.csv（已有数据的日期自动跳过）。

用法（在 D:/Trading 目录下执行）:
    python -m fetch.tonghuashun.backfill_concept_counts            # 回填全部历史
    python -m fetch.tonghuashun.backfill_concept_counts --days 10  # 只回填最近10个图上日期
    python -m fetch.tonghuashun.backfill_concept_counts --chart    # 回填后顺便生成轮动图
"""
import argparse
import os
import re
import time

import pandas as pd
import pywencai

from config.holder import config
from fetch.tonghuashun.hot_concept_rotation import (
    COUNTS_CSV,
    build_rotation_chart,
    save_concept_counts,
)
from fetch.tonghuashun.wencai_client import apply_pywencai_headers_patch

apply_pywencai_headers_patch()

IMG_DIR = 'images/wordcloud/hot'
REQUEST_INTERVAL = 2  # 每次请求间隔（秒），避免触发风控


def get_dates_from_images():
    """从词云图文件名提取日期列表（升序）。"""
    dates = []
    for f in os.listdir(IMG_DIR):
        m = re.match(r'^(\d{8})_concept\.png$', f)
        if m:
            dates.append(m.group(1))
    return sorted(set(dates))


def already_done(date):
    """该日期是否已有计数数据。"""
    if not os.path.exists(COUNTS_CSV):
        return False
    df = pd.read_csv(COUNTS_CSV, dtype={'date': str})
    return date in set(df['date'])


def fetch_day_counts(date):
    """拉取指定日期涨停数据并计算概念计数。"""
    param = f"{date}涨停，非涉嫌信息披露违规且非立案调查且非ST"
    df = pywencai.get(query=param, sort_key='成交金额', sort_order='desc',
                      loop=True, cookie=config.ths_cookie)
    col = '涨停原因类别[' + date + ']'
    if df is None or df.empty or col not in df.columns:
        return {}
    concepts = df[col].str.split('+').explode().dropna()
    concepts = concepts[concepts != '']
    return concepts.value_counts().to_dict()


def backfill(days=None, make_chart=False):
    dates = get_dates_from_images()
    if days:
        dates = dates[-days:]
    print(f"待处理日期数: {len(dates)}")

    failed = []
    for i, d in enumerate(dates, 1):
        if already_done(d):
            print(f"[{i}/{len(dates)}] 跳过 {d}（已有数据）")
            continue
        try:
            counts = fetch_day_counts(d)
            if not counts:
                print(f"[{i}/{len(dates)}] {d} 无概念数据（可能非交易日或接口无返回）")
            else:
                save_concept_counts(d, counts)
                print(f"[{i}/{len(dates)}] 完成 {d}: {len(counts)} 个概念")
            time.sleep(REQUEST_INTERVAL)
        except Exception as e:
            print(f"[{i}/{len(dates)}] 失败 {d}: {e}")
            failed.append(d)

    if failed:
        print(f"\n失败日期（可重跑本脚本续传）: {failed}")

    if make_chart:
        build_rotation_chart()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='回填历史热门概念计数')
    parser.add_argument('--days', type=int, default=None,
                        help='只回填最近 N 个图上日期，默认全部')
    parser.add_argument('--chart', action='store_true',
                        help='回填完成后生成概念轮动图')
    args = parser.parse_args()
    backfill(days=args.days, make_chart=args.chart)
