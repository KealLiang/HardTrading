# -*- coding: utf-8 -*-
"""
热门概念轮动图模块

职责：
1. save_concept_counts: 每日概念计数落盘（CSV，按日期覆盖更新）
2. build_rotation_chart: 读取计数数据，渲染"概念河流图" PNG
   - 每条彩色带 = 一个概念，带宽 = 当日涨停家数
   - 每天按当日家数重新堆叠排序，带的上下穿越即轮动
"""
import hashlib
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.font_manager import FontProperties
from matplotlib.path import Path
from matplotlib.patches import PathPatch

FONT_PATH = 'fonts/微软雅黑.ttf'
COUNTS_CSV = 'data/concepts_data/hot_concept_counts.csv'
OUTPUT_PATH = 'images/hot_concept_rotation.png'

# 相邻区分度高的 20 色（基于 matplotlib tab20 调整）
PALETTE = [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
    '#8c564b', '#e377c2', '#17becf', '#bcbd22', '#7f7f7f',
    '#aec7e8', '#ffbb78', '#98df8a', '#ff9896', '#c5b0d5',
    '#c49c94', '#f7b6d2', '#9edae5', '#dbdb8d', '#c7c7c7',
]

_font_prop = None


def _font():
    global _font_prop
    if _font_prop is None:
        _font_prop = FontProperties(fname=FONT_PATH)
    return _font_prop


def extract_concept_counts(date, sorted_temp_df):
    """
    从涨停数据中提取概念计数。

    Args:
        date: 日期字符串 'YYYYMMDD'
        sorted_temp_df: 含 '涨停原因类别[date]' 列的 DataFrame

    Returns:
        dict: {概念: 出现次数}
    """
    concepts = sorted_temp_df['涨停原因类别[' + date + ']'].str.split('+').explode()
    concepts = concepts.dropna()
    concepts = concepts[concepts != '']
    return concepts.value_counts().to_dict()


def save_concept_counts(date, concept_counts):
    """
    将某日的概念计数写入 CSV（同日期覆盖更新）。

    Args:
        date: 日期字符串 'YYYYMMDD'
        concept_counts: dict {概念: 次数} 或含 概念/出现次数 列的 DataFrame
    """
    date = str(date)
    if isinstance(concept_counts, pd.DataFrame):
        items = list(zip(concept_counts['概念'], concept_counts['出现次数']))
    else:
        items = list(concept_counts.items())

    items = [(str(k).strip(), int(v)) for k, v in items if k and str(k).strip()]
    if not items:
        print(f"概念计数为空，跳过保存 {date}")
        return

    new_rows = pd.DataFrame(items, columns=['concept', 'count'])
    new_rows.insert(0, 'date', date)

    os.makedirs(os.path.dirname(COUNTS_CSV), exist_ok=True)
    if os.path.exists(COUNTS_CSV):
        old = pd.read_csv(COUNTS_CSV, dtype={'date': str})
        old = old[old['date'] != date]
        df = pd.concat([old, new_rows], ignore_index=True)
    else:
        df = new_rows

    df = df.sort_values(['date', 'count'], ascending=[True, False])
    df.to_csv(COUNTS_CSV, index=False, encoding='utf-8-sig')
    print(f"概念计数已保存: {COUNTS_CSV} ({date}, {len(items)} 个概念)")


def _concept_colors(top_concepts):
    """按窗口内累计排名分配颜色，相邻概念颜色区分度高且跨次运行稳定。"""
    return {c: PALETTE[i % len(PALETTE)] for i, c in enumerate(top_concepts)}


def _day_layout(piv, window, top_concepts):
    """
    计算每天各概念色带的上下边界。

    每天按当日 count 降序堆叠（并列时按窗口累计降序），带间留缝隙。

    Returns:
        (layout, max_total)
        layout: {date: {concept: (bottom, top)}}
    """
    totals = piv.sum(axis=1)
    gap = 0.8
    layout = {}
    max_total = 0.0
    for d in window:
        col = piv[d]
        order = sorted(top_concepts, key=lambda c: (-col.get(c, 0), -totals[c]))
        y = 0.0
        day_layout = {}
        for c in order:
            cnt = float(col.get(c, 0))
            day_layout[c] = (y, y + cnt)
            y += cnt + gap
        layout[d] = day_layout
        max_total = max(max_total, y - gap)
    return layout, max_total


def _ribbon(ax, x0, x1, bot0, top0, bot1, top1, color):
    """绘制两个交易日之间的平滑色带（三次贝塞尔）。"""
    if top0 - bot0 <= 0 and top1 - bot1 <= 0:
        return
    mid = (x0 + x1) / 2.0
    vertices = [
        (x0, top0),
        (mid, top0), (mid, top1), (x1, top1),
        (x1, bot1),
        (mid, bot1), (mid, bot0), (x0, bot0),
        (x0, top0),
    ]
    codes = [Path.MOVETO,
             Path.CURVE4, Path.CURVE4, Path.CURVE4,
             Path.LINETO,
             Path.CURVE4, Path.CURVE4, Path.CURVE4,
             Path.CLOSEPOLY]
    patch = PathPatch(Path(vertices, codes), facecolor=color,
                      edgecolor=color, linewidth=0.8, alpha=0.55)
    ax.add_patch(patch)


def build_rotation_chart(days=7, top_n=10, output_path=OUTPUT_PATH,
                         counts_csv=None, show=False):
    """
    生成热门概念河流轮动图。

    Args:
        days: 时间窗口（最近 N 个交易日）
        top_n: 展示的概念数量（按窗口内累计涨停家数取 Top N）
        output_path: PNG 输出路径
        counts_csv: 计数 CSV 路径（默认 COUNTS_CSV，测试时可覆盖）
        show: 是否 plt.show()

    Returns:
        str: 成功返回输出路径，失败返回 None
    """
    csv_path = counts_csv or COUNTS_CSV
    if not os.path.exists(csv_path):
        print(f"计数文件不存在: {csv_path}，请先运行回填或等待每日脚本积累数据")
        return None

    df = pd.read_csv(csv_path, dtype={'date': str})
    all_dates = sorted(df['date'].unique())
    if not all_dates:
        print("计数文件为空")
        return None
    window = all_dates[-days:]
    if len(window) < 2:
        print(f"数据不足（仅 {len(window)} 个交易日），至少需要 2 天才能画轮动")
        return None

    wdf = df[df['date'].isin(window)]
    totals = wdf.groupby('concept')['count'].sum().sort_values(ascending=False)
    top_concepts = list(totals.head(top_n).index)
    if not top_concepts:
        print("窗口内无概念数据")
        return None

    piv = (wdf[wdf['concept'].isin(top_concepts)]
           .pivot_table(index='concept', columns='date', values='count',
                        aggfunc='sum')
           .reindex(columns=window).fillna(0))

    colors = _concept_colors(top_concepts)
    layout, max_total = _day_layout(piv, window, top_concepts)

    spacing = 10.0
    xs = {d: i * spacing for i, d in enumerate(window)}

    height_in = max(4.5, min(9.0, 2.2 + max_total * 0.12))
    fig, ax = plt.subplots(figsize=(14, height_in))
    fp = _font()

    # 色带
    for j in range(len(window) - 1):
        d0, d1 = window[j], window[j + 1]
        x0, x1 = xs[d0], xs[d1]
        for c in top_concepts:
            bot0, top0 = layout[d0][c]
            bot1, top1 = layout[d1][c]
            _ribbon(ax, x0, x1, bot0, top0, bot1, top1, colors[c])

    # 每日参考虚线 + 日期标签
    top_y = max_total + 1.0
    for d in window:
        ax.axvline(xs[d], color='#cccccc', linewidth=0.5,
                   linestyle='--', zorder=0)
        label = f"{d[:4]}/{d[4:6]}/{d[6:]}"
        ax.text(xs[d], top_y + 0.6, label, ha='center', va='bottom',
                fontsize=11, color='#555555', fontproperties=fp)

    # 右侧概念标签（名称 + 最新家数；今日为 0 的概念也标注，显示掉队）
    last_d = window[-1]
    x_last = xs[last_d]
    for c in top_concepts:
        bot, top = layout[last_d][c]
        cnt = int(piv.loc[c, last_d])
        y = (bot + top) / 2.0 if top > bot else bot
        ax.text(x_last + 0.25, y, f"{c} {cnt}",
                ha='left', va='center', fontsize=12,
                color=colors[c], fontproperties=fp)

    ax.set_xlim(-0.8, x_last + 3.2)
    ax.set_ylim(-0.8, top_y + 2.2)
    ax.axis('off')
    ax.set_title(f"近{len(window)}个交易日热门概念轮动（Top {len(top_concepts)}，带宽=涨停家数）",
                 fontsize=14, fontproperties=fp, pad=18)

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    plt.savefig(output_path, format='png', dpi=150,
                bbox_inches='tight', pad_inches=0.15)
    plt.close(fig)

    if show:
        plt.show()

    print(f"概念轮动图已保存: {output_path}")
    return output_path


if __name__ == '__main__':
    build_rotation_chart()
