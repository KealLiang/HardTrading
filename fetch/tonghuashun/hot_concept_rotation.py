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
import re

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


# 前缀归并族：命中前缀的概念统一归并到指定名称（优先于自动规则，可自行增删）
SYNONYM_PREFIX_FAMILIES = {
    '三季报': '三季报业绩',
    '第三季度': '三季报业绩',
    '三季度': '三季报业绩',
}

_CJK_RE = re.compile(r'[\u4e00-\u9fff]')


def _manual_family(name):
    """命中前缀归并族则返回族名，否则返回 None。"""
    for prefix, family in SYNONYM_PREFIX_FAMILIES.items():
        if name.startswith(prefix):
            return family
    return None


def _edit_distance_one(a, b):
    """判断两词编辑距离是否为 1（一次替换/插入/删除）。"""
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        return sum(1 for x, y in zip(a, b) if x != y) == 1
    if la > lb:
        a, b, la, lb = b, a, lb, la
    i = 0
    while i < la and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def _common_edges(a, b):
    """返回 (共同前缀长度, 共同后缀长度)。"""
    short = min(len(a), len(b))
    prefix = 0
    while prefix < short and a[prefix] == b[prefix]:
        prefix += 1
    suffix = 0
    while suffix < short and a[-1 - suffix] == b[-1 - suffix]:
        suffix += 1
    return prefix, suffix


def _is_synonym(a, b):
    """
    判断两个概念名是否为近义词（最简字符规则，无外部依赖）。

    规则：
    1. 一个是另一个的子串 -> 层级概念（算力/算力租赁、机器人/人形机器人），不合并
    2. 含纯拉丁缩写（CPO/PCB/CRO）的 -> 不同概念，不合并
    3. 编辑距离必须正好为 1（增减一字，或等长替换一字）
    4. 等长替换时，差异字前后必须都有共享字（改的是修饰字而非核心字），
       避免 南京国资/北京国资、光伏电站/光伏电池 这类语义不同的词被并掉
    """
    if a == b:
        return True
    if a in b or b in a:
        return False
    if not _CJK_RE.search(a) or not _CJK_RE.search(b):
        return False
    if min(len(a), len(b)) < 4:
        return False
    if not _edit_distance_one(a, b):
        return False
    if len(a) != len(b):
        return True  # 增减一字（纯包含关系已被上面拦截）
    prefix, suffix = _common_edges(a, b)
    return prefix >= 2 and suffix >= 1


def _merge_synonyms(totals):
    """
    按近义词规则合并概念名，返回 {原名: 代表名}。

    采用"锚点贪心"（不做传递合并）：按累计计数从高到低遍历，
    能并入已有代表词就并入，否则自成一个新组。
    避免 A~B、B~C 链式合并把整片概念串成一个大组。

    Args:
        totals: pd.Series，index 为概念名，值为窗口内累计计数

    Returns:
        dict: 被合并的词 -> 代表词（未合并的词不在结果中）
    """
    names = sorted(totals.index, key=lambda n: (-totals[n], -len(n)))

    # 1) 前缀归并族优先
    mapping = {}
    for n in names:
        family = _manual_family(n)
        if family and family != n:
            mapping[n] = family

    # 2) 自动规则：锚点贪心，不做传递合并
    reps = []
    for n in names:
        if n in mapping:
            continue
        for rep in reps:
            if _is_synonym(n, rep):
                mapping[n] = rep
                break
        else:
            reps.append(n)
    return mapping


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

    # 近义词合并（避免近义词占用 Top N 名额）
    pre_totals = wdf.groupby('concept')['count'].sum()
    merge_map = _merge_synonyms(pre_totals)
    if merge_map:
        for src, rep in sorted(merge_map.items(), key=lambda kv: kv[1]):
            print(f"近义词合并: {src} -> {rep}")
        wdf = wdf.assign(concept=wdf['concept'].map(lambda c: merge_map.get(c, c)))

    # 合并组明细：代表名 -> 被并入的原词（按累计计数降序），用于标签小字标注合并模式
    merge_groups = {}
    for src, rep in merge_map.items():
        merge_groups.setdefault(rep, []).append(src)
    for rep in merge_groups:
        merge_groups[rep].sort(key=lambda s: (-pre_totals.get(s, 0), s))

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
    # 合并过的概念额外用一行小字列出被并入的原词，标明"这个数字是怎么来的"
    last_d = window[-1]
    x_last = xs[last_d]

    ax.set_xlim(-0.8, x_last + 3.2)
    ax.set_ylim(-0.8, top_y + 2.2)
    ax.axis('off')
    ax.set_title(f"近{len(window)}个交易日热门概念轮动（Top {len(top_concepts)}，带宽=涨停家数）",
                 fontsize=14, fontproperties=fp, pad=18)
    plt.tight_layout()

    # 字号换算成数据单位：先定稿坐标轴尺寸再实测，避免估算偏差导致标签重叠
    fig.canvas.draw()
    y_span = (top_y + 2.2) - (-0.8)
    ax_h_pt = ax.get_window_extent().height / fig.dpi * 72.0
    data_per_pt = y_span / max(ax_h_pt, 1.0)
    min_gap = 20 * data_per_pt   # 单行标签（12pt 字高约 17pt，留 1.35 倍行距）
    gap_two = 27 * data_per_pt   # 双行标签（12pt 名称 + 8pt 说明）
    pad = 2 * data_per_pt

    def _merge_note(subs):
        """合并组的小字说明，只列代表性原词；超过 2 个用 /… 表示还有更多。"""
        if not subs:
            return ''
        return '/'.join(subs[:2]) + ('/…' if len(subs) > 2 else '')

    labels = []
    for c in top_concepts:
        bot, top = layout[last_d][c]
        y = (bot + top) / 2.0 if top > bot else bot
        labels.append({'name': c, 'y': y, 'note': _merge_note(merge_groups.get(c))})
    labels.sort(key=lambda it: it['y'])
    for i in range(1, len(labels)):
        need = gap_two if (labels[i]['note'] or labels[i - 1]['note']) else min_gap
        if labels[i]['y'] - labels[i - 1]['y'] < need:
            labels[i]['y'] = labels[i - 1]['y'] + need

    for it in labels:
        c, y, note = it['name'], it['y'], it['note']
        cnt = int(piv.loc[c, last_d])
        ax.text(x_last + 0.25, y + (pad if note else 0), f"{c} {cnt}",
                ha='left', va='bottom' if note else 'center', fontsize=12,
                color=colors[c], fontproperties=fp)
        if note:
            ax.text(x_last + 0.25, y - pad, note,
                    ha='left', va='top', fontsize=8, alpha=0.85,
                    color=colors[c], fontproperties=fp)

    # 标签被上推时按需扩展顶部，避免裁切
    if labels[-1]['y'] + gap_two * 0.6 > top_y + 2.2:
        ax.set_ylim(-0.8, labels[-1]['y'] + gap_two * 0.6)

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
