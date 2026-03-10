"""
VCP分数与回测盈亏关联分析

将候选股扫描文件(txt)与回测报告(md)关联，分析VCP Score是否能有效预测交易盈亏。

分析维度:
1. VCP Score 与收益率的相关性（Pearson / Spearman）
2. 按 VCP Score 分档统计（平均收益、胜率、止盈率）
3. 按 VCP 类型统计（VCP-A/B/C/D）
4. 按信号类型统计（快速通道/二次确认/回踩确认/止损纠错）
5. 过热分与收益率的关系
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats


# ─────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────

@dataclass
class SignalRecord:
    """候选股扫描记录"""
    stock_code: str
    stock_name: str
    signal_date: str  # YYYY-MM-DD
    price: float
    rating: int  # 评分（0/6/9等）
    signal_type: str  # 二次确认 / 快速通道 / 回踩确认 / 止损纠错
    vcp_type: str  # VCP-A / VCP-B / VCP-C / VCP-D
    vcp_score: float  # VCP Score
    heat_score: Optional[float] = None  # 过热分（仅二次确认信号有）


@dataclass
class TradeRecord:
    """回测交易记录"""
    stock_code: str
    stock_name: str
    signal_date: str  # YYYY-MM-DD
    buy_date: str
    sell_date: str
    holding_days: int
    buy_price: float
    sell_price: float
    return_rate: float  # 收益率百分比，如 15.00 表示 +15%
    max_profit: float  # 最大浮盈百分比
    max_loss: float  # 最大浮亏百分比
    sell_reason: str  # 止盈 / 止损 / 持满 / 数据截止


# ─────────────────────────────────────────────
# 解析器
# ─────────────────────────────────────────────

def parse_scan_summary(file_path: str) -> list[SignalRecord]:
    """
    解析候选股扫描汇总文件(txt)，提取每条信号的VCP信息。

    支持的信号格式:
    - 二次确认: ... 当前过热分: 1.36 (VCP 参考: VCP-C, Score: 1.77) ...
    - 快速通道: 买入信号: 快速通道【B级】 (VCP: VCP-D, Score: 1.33)
    - 回踩确认: 买入信号: 回踩确认 (价格=... VCP: VCP-C, Score: 1.80)
    - 止损纠错: 买入信号: 止损纠错 (价格=... VCP: VCP-B, Score: 2.52)
    """
    records = []

    # 行格式: 股票: 002380 科远智慧, 信号日期: 2026-03-05, 价格: 36.53, 评分: 0，详情: ...
    line_pattern = re.compile(
        r'股票:\s*(\d+)\s+(.+?),\s*信号日期:\s*([\d-]+),\s*价格:\s*([\d.]+),\s*评分:\s*(\d+)[，,]\s*详情:\s*(.*)'
    )
    # VCP 信息提取
    vcp_pattern = re.compile(r'VCP(?:\s*参考)?:\s*(VCP-[A-D]),\s*Score:\s*([\d.]+)')
    # 过热分
    heat_pattern = re.compile(r'过热分:\s*([\d.]+)')

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            m = line_pattern.match(line)
            if not m:
                continue

            code, name, date, price, rating, detail = m.groups()

            # 提取 VCP 类型和分数
            vcp_m = vcp_pattern.search(detail)
            if not vcp_m:
                continue  # 无VCP信息则跳过
            vcp_type = vcp_m.group(1)
            vcp_score = float(vcp_m.group(2))

            # 判断信号类型
            if '二次确认' in detail:
                signal_type = '二次确认'
            elif '快速通道' in detail:
                signal_type = '快速通道'
            elif '回踩确认' in detail:
                signal_type = '回踩确认'
            elif '止损纠错' in detail:
                signal_type = '止损纠错'
            else:
                signal_type = '其他'

            # 提取过热分（仅二次确认有）
            heat_score = None
            heat_m = heat_pattern.search(detail)
            if heat_m:
                heat_score = float(heat_m.group(1))

            records.append(SignalRecord(
                stock_code=code,
                stock_name=name.strip(),
                signal_date=date,
                price=float(price),
                rating=int(rating),
                signal_type=signal_type,
                vcp_type=vcp_type,
                vcp_score=vcp_score,
                heat_score=heat_score,
            ))

    return records


def _extract_date_range_from_filename(file_path: str) -> tuple[str, str]:
    """从文件名中提取日期范围，如 '20251220-20260309' → ('20251220', '20260309')"""
    m = re.search(r'(\d{8})-(\d{8})', os.path.basename(file_path))
    if not m:
        raise ValueError(f"无法从文件名中提取日期范围: {file_path}")
    return m.group(1), m.group(2)


def _resolve_year_for_md_date(md_date: str, start_date_str: str, end_date_str: str) -> str:
    """
    将回测报告中的 MM/DD 格式日期补全为 YYYY-MM-DD。
    基于文件名中的日期范围推断年份。
    """
    month, day = md_date.strip().split('/')
    month, day = int(month), int(day)

    start_date = datetime.strptime(start_date_str, '%Y%m%d')
    end_date = datetime.strptime(end_date_str, '%Y%m%d')

    # 尝试 end_year 和 start_year
    for year in [end_date.year, start_date.year]:
        try:
            candidate = datetime(year, month, day)
            if start_date <= candidate <= end_date:
                return candidate.strftime('%Y-%m-%d')
        except ValueError:
            continue

    # 兜底：如果月份 >= 10 大概率是 start_year，否则 end_year
    year = start_date.year if month >= 10 else end_date.year
    return f'{year}-{month:02d}-{day:02d}'


def parse_backtest_report(file_path: str) -> list[TradeRecord]:
    """
    解析回测报告(md)中的交易明细表。

    表格格式:
    | 股票 | 信号日 | 买入日 | 卖出日 | 持有 | 买入价 | 卖出价 | 收益率 | 最大浮盈 | 最大浮亏 | 卖出原因 |
    | 长光华芯(688048) | 02/26 | 02/27 | 03/04 | 4天 | 147.50 | 169.62 | +15.00% | +22.63% | -0.41% | 止盈15% |
    """
    start_str, end_str = _extract_date_range_from_filename(file_path)
    records = []

    # 匹配交易明细行
    # 股票名可能包含特殊字符如 x、ST、-U、-UW 等
    row_pattern = re.compile(
        r'\|\s*(.+?)\((\d+)\)\s*\|'  # 股票名(代码)
        r'\s*(\d{2}/\d{2})\s*\|'  # 信号日
        r'\s*(\d{2}/\d{2})\s*\|'  # 买入日
        r'\s*(\d{2}/\d{2})\s*\|'  # 卖出日
        r'\s*(\d+)天\s*\|'  # 持有天数
        r'\s*([\d.]+)\s*\|'  # 买入价
        r'\s*([\d.]+)\s*\|'  # 卖出价
        r'\s*([+-][\d.]+)%\s*\|'  # 收益率
        r'\s*([+-][\d.]+)%\s*\|'  # 最大浮盈
        r'\s*([+-][\d.]+)%\s*\|'  # 最大浮亏
        r'\s*(.+?)\s*\|'  # 卖出原因
    )

    in_trade_detail = False
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            # 定位交易明细区域
            if '交易明细' in line:
                in_trade_detail = True
                continue
            if not in_trade_detail:
                continue

            m = row_pattern.match(line.strip())
            if not m:
                continue

            (name, code, sig_d, buy_d, sell_d, days,
             buy_p, sell_p, ret, max_p, max_l, reason) = m.groups()

            signal_date = _resolve_year_for_md_date(sig_d, start_str, end_str)
            buy_date = _resolve_year_for_md_date(buy_d, start_str, end_str)
            sell_date = _resolve_year_for_md_date(sell_d, start_str, end_str)

            # 归一化卖出原因
            reason = reason.strip()
            if '止盈' in reason:
                sell_reason = '止盈'
            elif '止损' in reason:
                sell_reason = '止损'
            elif '持满' in reason:
                sell_reason = '持满'
            elif '数据截止' in reason:
                sell_reason = '数据截止'
            else:
                sell_reason = reason

            records.append(TradeRecord(
                stock_code=code,
                stock_name=name.strip(),
                signal_date=signal_date,
                buy_date=buy_date,
                sell_date=sell_date,
                holding_days=int(days),
                buy_price=float(buy_p),
                sell_price=float(sell_p),
                return_rate=float(ret),
                max_profit=float(max_p),
                max_loss=float(max_l),
                sell_reason=sell_reason,
            ))

    return records


# ─────────────────────────────────────────────
# 关联与分析
# ─────────────────────────────────────────────

def merge_data(signals: list[SignalRecord], trades: list[TradeRecord]) -> pd.DataFrame:
    """
    按 (stock_code, signal_date) 关联候选股信号与回测交易，返回合并后的 DataFrame。
    """
    sig_map = {}
    for s in signals:
        key = (s.stock_code, s.signal_date)
        sig_map[key] = s

    rows = []
    matched, unmatched = 0, 0
    for t in trades:
        key = (t.stock_code, t.signal_date)
        s = sig_map.get(key)
        if s is None:
            unmatched += 1
            continue
        matched += 1
        rows.append({
            'stock_code': t.stock_code,
            'stock_name': t.stock_name,
            'signal_date': t.signal_date,
            'signal_type': s.signal_type,
            'vcp_type': s.vcp_type,
            'vcp_score': s.vcp_score,
            'heat_score': s.heat_score,
            'rating': s.rating,
            'return_rate': t.return_rate,
            'max_profit': t.max_profit,
            'max_loss': t.max_loss,
            'sell_reason': t.sell_reason,
            'holding_days': t.holding_days,
        })

    print(f"\n🔗 数据关联: 回测共 {len(trades)} 条交易，成功匹配 {matched} 条，未匹配 {unmatched} 条")
    if unmatched > 0:
        print(f"   （未匹配可能因为回测文件使用了不同的候选股源文件）")

    return pd.DataFrame(rows)


def _format_table(headers: list[str], rows: list[list], alignments: Optional[list[str]] = None) -> str:
    """格式化文本表格，支持左/右/居中对齐"""
    if not rows:
        return "（无数据）"

    # 计算每列最大宽度（考虑中文字符宽度）
    def _display_width(s: str) -> int:
        w = 0
        for ch in str(s):
            w += 2 if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f' else 1
        return w

    def _pad(s: str, width: int, align: str = 'left') -> str:
        s = str(s)
        padding = width - _display_width(s)
        if padding <= 0:
            return s
        if align == 'right':
            return ' ' * padding + s
        elif align == 'center':
            left = padding // 2
            return ' ' * left + s + ' ' * (padding - left)
        return s + ' ' * padding

    all_rows = [headers] + rows
    col_widths = []
    for col_idx in range(len(headers)):
        col_widths.append(max(_display_width(str(r[col_idx])) for r in all_rows))

    if alignments is None:
        alignments = ['left'] * len(headers)

    lines = []
    # 表头
    header_line = '  '.join(_pad(h, col_widths[i], 'center') for i, h in enumerate(headers))
    lines.append(header_line)
    lines.append('─' * len(header_line.encode('gbk', errors='replace')))

    # 数据行
    for row in rows:
        line = '  '.join(_pad(str(row[i]), col_widths[i], alignments[i]) for i in range(len(headers)))
        lines.append(line)

    return '\n'.join(lines)


def analyze(df: pd.DataFrame, output_dir: Optional[str] = None):
    """执行完整的 VCP 有效性分析并输出结果"""

    report_lines = []

    def section(title: str):
        report_lines.append(f"\n{'=' * 60}")
        report_lines.append(f"  {title}")
        report_lines.append(f"{'=' * 60}")

    def content(text: str):
        report_lines.append(text)

    # ───── 0. 概览 ─────
    section("📊 数据概览")
    total = len(df)
    win = (df['return_rate'] > 0).sum()
    lose = (df['return_rate'] < 0).sum()
    even = (df['return_rate'] == 0).sum()
    content(f"  总交易数: {total}")
    content(f"  盈利: {win} ({win / total * 100:.1f}%)  |  亏损: {lose} ({lose / total * 100:.1f}%)  |  持平: {even}")
    content(f"  平均收益率: {df['return_rate'].mean():.2f}%")
    content(f"  收益率中位数: {df['return_rate'].median():.2f}%")
    content(f"  VCP Score 范围: {df['vcp_score'].min():.2f} ~ {df['vcp_score'].max():.2f}")

    # ───── 1. 相关性分析 ─────
    section("📈 维度一: VCP Score 与收益率的相关性")

    pearson_r, pearson_p = stats.pearsonr(df['vcp_score'], df['return_rate'])
    spearman_r, spearman_p = stats.spearmanr(df['vcp_score'], df['return_rate'])

    content(f"  Pearson  相关系数: {pearson_r:+.4f}  (p={pearson_p:.4f})")
    content(f"  Spearman 相关系数: {spearman_r:+.4f}  (p={spearman_p:.4f})")
    content("")

    if abs(pearson_r) < 0.1:
        interp = "几乎无线性相关"
    elif abs(pearson_r) < 0.3:
        interp = "弱相关"
    elif abs(pearson_r) < 0.5:
        interp = "中等相关"
    else:
        interp = "较强相关"
    direction = "正" if pearson_r > 0 else "负"
    sig = "显著" if pearson_p < 0.05 else "不显著"

    content(
        f"  → 结论: VCP Score 与收益率呈 {interp}（{direction}向），统计{sig}（p{'<' if pearson_p < 0.05 else '≥'}0.05）")

    # ───── 2. 按 VCP Score 分档统计 ─────
    section("📊 维度二: 按 VCP Score 分档统计")

    bins = [0, 1.0, 1.5, 2.0, 2.5, 3.0, float('inf')]
    labels = ['<1.0', '1.0~1.5', '1.5~2.0', '2.0~2.5', '2.5~3.0', '≥3.0']
    df['score_bin'] = pd.cut(df['vcp_score'], bins=bins, labels=labels, right=False)

    headers = ['Score区间', '数量', '平均收益', '中位收益', '胜率', '止盈率', '止损率']
    rows = []
    for label in labels:
        group = df[df['score_bin'] == label]
        n = len(group)
        if n == 0:
            rows.append([label, '0', '-', '-', '-', '-', '-'])
            continue
        avg_ret = group['return_rate'].mean()
        med_ret = group['return_rate'].median()
        win_rate = (group['return_rate'] > 0).sum() / n * 100
        tp_rate = (group['sell_reason'] == '止盈').sum() / n * 100
        sl_rate = (group['sell_reason'] == '止损').sum() / n * 100
        rows.append([
            label, str(n),
            f'{avg_ret:+.2f}%', f'{med_ret:+.2f}%',
            f'{win_rate:.1f}%', f'{tp_rate:.1f}%', f'{sl_rate:.1f}%'
        ])

    alignments = ['center', 'right', 'right', 'right', 'right', 'right', 'right']
    content(_format_table(headers, rows, alignments))

    # ───── 3. 按 VCP 类型统计 ─────
    section("📊 维度三: 按 VCP 类型统计")

    vcp_order = ['VCP-A', 'VCP-B', 'VCP-C', 'VCP-D']
    headers = ['VCP类型', '数量', '平均Score', '平均收益', '中位收益', '胜率', '止盈率', '止损率']
    rows = []
    for vcp in vcp_order:
        group = df[df['vcp_type'] == vcp]
        n = len(group)
        if n == 0:
            rows.append([vcp, '0', '-', '-', '-', '-', '-', '-'])
            continue
        avg_score = group['vcp_score'].mean()
        avg_ret = group['return_rate'].mean()
        med_ret = group['return_rate'].median()
        win_rate = (group['return_rate'] > 0).sum() / n * 100
        tp_rate = (group['sell_reason'] == '止盈').sum() / n * 100
        sl_rate = (group['sell_reason'] == '止损').sum() / n * 100
        rows.append([
            vcp, str(n), f'{avg_score:.2f}',
            f'{avg_ret:+.2f}%', f'{med_ret:+.2f}%',
            f'{win_rate:.1f}%', f'{tp_rate:.1f}%', f'{sl_rate:.1f}%'
        ])

    alignments = ['center', 'right', 'right', 'right', 'right', 'right', 'right', 'right']
    content(_format_table(headers, rows, alignments))

    # ───── 4. 按信号类型统计 ─────
    section("📊 维度四: 按信号类型统计")

    signal_types = ['快速通道', '二次确认', '回踩确认', '止损纠错']
    headers = ['信号类型', '数量', '平均Score', '平均收益', '中位收益', '胜率', '止盈率', '止损率']
    rows = []
    for st in signal_types:
        group = df[df['signal_type'] == st]
        n = len(group)
        if n == 0:
            continue
        avg_score = group['vcp_score'].mean()
        avg_ret = group['return_rate'].mean()
        med_ret = group['return_rate'].median()
        win_rate = (group['return_rate'] > 0).sum() / n * 100
        tp_rate = (group['sell_reason'] == '止盈').sum() / n * 100
        sl_rate = (group['sell_reason'] == '止损').sum() / n * 100
        rows.append([
            st, str(n), f'{avg_score:.2f}',
            f'{avg_ret:+.2f}%', f'{med_ret:+.2f}%',
            f'{win_rate:.1f}%', f'{tp_rate:.1f}%', f'{sl_rate:.1f}%'
        ])

    alignments = ['center', 'right', 'right', 'right', 'right', 'right', 'right', 'right']
    content(_format_table(headers, rows, alignments))

    # ───── 5. 过热分与收益率 ─────
    section("📊 维度五: 过热分与收益率的关系（仅二次确认信号）")

    df_heat = df[df['heat_score'].notna()].copy()
    if len(df_heat) < 5:
        content("  数据量不足，跳过过热分分析。")
        heat_conclusion = "数据不足，无法评估"
    else:
        h_pearson_r, h_pearson_p = stats.pearsonr(df_heat['heat_score'], df_heat['return_rate'])
        h_spearman_r, h_spearman_p = stats.spearmanr(df_heat['heat_score'], df_heat['return_rate'])
        content(f"  样本数: {len(df_heat)}")
        content(f"  Pearson  相关系数: {h_pearson_r:+.4f}  (p={h_pearson_p:.4f})"
                f"  {'✅ 显著' if h_pearson_p < 0.05 else '❌ 不显著'}")
        content(f"  Spearman 相关系数: {h_spearman_r:+.4f}  (p={h_spearman_p:.4f})"
                f"  {'✅ 显著' if h_spearman_p < 0.05 else '❌ 不显著'}")

        # 过热分的含义解读
        if h_pearson_r > 0:
            direction_hint = "过热分越高 → 收益越高（过热不一定是坏事，可能代表强势）"
        else:
            direction_hint = "过热分越高 → 收益越低（过热确实预示风险）"
        content(f"  方向解读: {direction_hint}")

        heat_bins = [0, 0.3, 0.6, 1.0, 1.5, float('inf')]
        heat_labels = ['<0.3', '0.3~0.6', '0.6~1.0', '1.0~1.5', '≥1.5']
        df_heat['heat_bin'] = pd.cut(df_heat['heat_score'], bins=heat_bins, labels=heat_labels, right=False)

        headers = ['过热分区间', '数量', '平均收益', '中位数收益', '胜率', '止盈率', '止损率']
        rows = []
        for label in heat_labels:
            group = df_heat[df_heat['heat_bin'] == label]
            n = len(group)
            if n == 0:
                rows.append([label, '0', '-', '-', '-', '-', '-'])
                continue
            avg_ret = group['return_rate'].mean()
            med_ret = group['return_rate'].median()
            win_rate = (group['return_rate'] > 0).sum() / n * 100
            tp_rate = (group['sell_reason'] == '止盈').sum() / n * 100
            sl_rate = (group['sell_reason'] == '止损').sum() / n * 100
            rows.append([
                label, str(n), f'{avg_ret:+.2f}%', f'{med_ret:+.2f}%',
                f'{win_rate:.1f}%', f'{tp_rate:.1f}%', f'{sl_rate:.1f}%'
            ])

        alignments = ['center', 'right', 'right', 'right', 'right', 'right', 'right']
        content(_format_table(headers, rows, alignments))

        # 过热分小结
        heat_bin_means = df_heat.groupby('heat_bin', observed=True)['return_rate'].mean()
        if len(heat_bin_means) >= 2:
            best_h = heat_bin_means.idxmax()
            worst_h = heat_bin_means.idxmin()
            content(f"\n  ▸ 最佳过热分区间: {best_h}（平均收益 {heat_bin_means[best_h]:+.2f}%）")
            content(f"  ▸ 最差过热分区间: {worst_h}（平均收益 {heat_bin_means[worst_h]:+.2f}%）")

        # 构建过热分结论
        if h_pearson_p < 0.05:
            heat_conclusion = f"过热分与收益率{'正' if h_pearson_r > 0 else '负'}相关，具有统计显著性（r={h_pearson_r:+.4f}, p={h_pearson_p:.4f}）"
        else:
            heat_conclusion = f"过热分与收益率无显著相关性（r={h_pearson_r:+.4f}, p={h_pearson_p:.4f}）"

    # ───── 6. 细粒度 VCP Score 分段分析（用于反推最优区间） ─────
    section("📊 维度六: 细粒度 VCP Score 分段分析")

    # 使用更细的分段（等宽），覆盖常见区间 0~5
    fine_bins = np.arange(0.0, 5.01, 0.25)  # [0,0.25),[0.25,0.5),...
    fine_labels = [f"{fine_bins[i]:.2f}~{fine_bins[i + 1]:.2f}" for i in range(len(fine_bins) - 1)]
    df['fine_score_bin'] = pd.cut(
        df['vcp_score'],
        bins=fine_bins,
        labels=fine_labels,
        right=False,
        include_lowest=True
    )

    fine_stats = df.groupby('fine_score_bin', observed=True).agg(
        count=('return_rate', 'count'),
        avg_return=('return_rate', 'mean'),
        med_return=('return_rate', 'median'),
        win_rate=('return_rate', lambda x: (x > 0).mean() * 100),
    )

    # 只保留样本数足够的区间，避免噪声
    min_fine_n = 10
    fine_stats_filtered = fine_stats[fine_stats['count'] >= min_fine_n].copy()

    headers = ['Score 区间', '数量', '平均收益', '中位数收益', '胜率']
    rows = []
    for idx, row in fine_stats_filtered.iterrows():
        rows.append([
            idx if isinstance(idx, str) else str(idx),
            str(int(row['count'])),
            f"{row['avg_return']:+.2f}%",
            f"{row['med_return']:+.2f}%",
            f"{row['win_rate']:.1f}%",
        ])

    if rows:
        alignments = ['left', 'right', 'right', 'right', 'right']
        # 仅输出细粒度分段的收益和胜率统计，不再给出自动映射或启发式建议，
        # 避免过度拟合，让人工根据这张表和图表自行判断哪些 Score 区间更优。
        content(_format_table(headers, rows, alignments))
    else:
        content("  样本数不足，无法进行细粒度 Score 分段分析（需要每段至少 10 个样本）。")

    # ───── 7. VCP Score × 过热分 交叉分析 ─────
    section("📊 维度六: VCP Score × 过热分 交叉分析")

    if len(df_heat) < 10:
        content("  过热分数据不足，跳过交叉分析。")
    else:
        # 将两个维度各分为高/低两组
        score_median = df_heat['vcp_score'].median()
        heat_median = df_heat['heat_score'].median()
        content(f"  VCP Score 中位数: {score_median:.2f}，过热分中位数: {heat_median:.2f}")
        content(f"  以中位数为界将样本分为 4 个象限:\n")

        df_heat['score_level'] = np.where(df_heat['vcp_score'] >= score_median, '高Score', '低Score')
        df_heat['heat_level'] = np.where(df_heat['heat_score'] >= heat_median, '高过热', '低过热')
        df_heat['cross_group'] = df_heat['score_level'] + ' + ' + df_heat['heat_level']

        cross_order = ['高Score + 低过热', '高Score + 高过热', '低Score + 低过热', '低Score + 高过热']
        headers = ['组合', '数量', '平均收益', '中位数收益', '胜率', '止盈率', '止损率']
        rows = []
        for group_name in cross_order:
            group = df_heat[df_heat['cross_group'] == group_name]
            n = len(group)
            if n == 0:
                rows.append([group_name, '0', '-', '-', '-', '-', '-'])
                continue
            avg_ret = group['return_rate'].mean()
            med_ret = group['return_rate'].median()
            win_rate = (group['return_rate'] > 0).sum() / n * 100
            tp_rate = (group['sell_reason'] == '止盈').sum() / n * 100
            sl_rate = (group['sell_reason'] == '止损').sum() / n * 100
            rows.append([
                group_name, str(n), f'{avg_ret:+.2f}%', f'{med_ret:+.2f}%',
                f'{win_rate:.1f}%', f'{tp_rate:.1f}%', f'{sl_rate:.1f}%'
            ])

        alignments = ['left', 'right', 'right', 'right', 'right', 'right', 'right']
        content(_format_table(headers, rows, alignments))

        # 交叉分析结论
        cross_means = df_heat.groupby('cross_group')['return_rate'].mean()
        if len(cross_means) >= 2:
            best_cross = cross_means.idxmax()
            worst_cross = cross_means.idxmin()
            content(f"\n  ▸ 最佳组合: {best_cross}（平均收益 {cross_means[best_cross]:+.2f}%）")
            content(f"  ▸ 最差组合: {worst_cross}（平均收益 {cross_means[worst_cross]:+.2f}%）")

            # 检查交互效应：同Score下，过热分高/低是否有差异
            high_score_groups = cross_means.filter(like='高Score')
            low_score_groups = cross_means.filter(like='低Score')

            if len(high_score_groups) == 2:
                h_diff = high_score_groups.get('高Score + 低过热', 0) - high_score_groups.get('高Score + 高过热', 0)
                content(f"  ▸ 高Score下: 低过热比高过热{'多' if h_diff > 0 else '少'} {abs(h_diff):.2f}% 收益")
            if len(low_score_groups) == 2:
                l_diff = low_score_groups.get('低Score + 低过热', 0) - low_score_groups.get('低Score + 高过热', 0)
                content(f"  ▸ 低Score下: 低过热比高过热{'多' if l_diff > 0 else '少'} {abs(l_diff):.2f}% 收益")

    # ───── 7. 综合结论 ─────
    section("📝 综合结论")

    # 检查单调性：Score 越高，平均收益是否越高
    bin_means = df.groupby('score_bin', observed=True)['return_rate'].mean()
    monotonic_up = all(
        bin_means.iloc[i] <= bin_means.iloc[i + 1]
        for i in range(len(bin_means) - 1)
    ) if len(bin_means) > 1 else False

    vcp_type_means = df.groupby('vcp_type')['return_rate'].mean()

    content(f"  1. VCP Score 与收益率的 Pearson 相关系数为 {pearson_r:+.4f}，"
            f"{'具有统计显著性' if pearson_p < 0.05 else '不具有统计显著性'}。")

    if monotonic_up:
        content(f"  2. 分档统计显示 Score 越高，平均收益越高，呈单调递增趋势 ✅")
    else:
        content(f"  2. 分档统计显示 Score 与收益并非严格单调递增关系。")

    if 'VCP-A' in vcp_type_means.index and 'VCP-D' in vcp_type_means.index:
        a_ret = vcp_type_means.get('VCP-A', 0)
        d_ret = vcp_type_means.get('VCP-D', 0)
        content(f"  3. VCP-A 平均收益 {a_ret:+.2f}% vs VCP-D 平均收益 {d_ret:+.2f}%"
                f"  →  {'A优于D ✅' if a_ret > d_ret else 'D优于A ❌（评分体系可能需调整）'}")

    # 最高/最低组对比
    if len(bin_means) >= 2:
        best_bin = bin_means.idxmax()
        worst_bin = bin_means.idxmin()
        content(f"  4. 表现最好的 Score 区间: {best_bin}（平均收益 {bin_means[best_bin]:+.2f}%）")
        content(f"     表现最差的 Score 区间: {worst_bin}（平均收益 {bin_means[worst_bin]:+.2f}%）")

    content(f"  5. 过热分: {heat_conclusion}")

    # 输出报告
    report_text = '\n'.join(report_lines)
    print(report_text)

    # 尝试生成图表
    _try_generate_charts(df, output_dir)

    # 保存文本报告
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        report_path = os.path.join(output_dir, 'vcp_analysis_report.txt')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_text)
        print(f"\n📄 文本报告已保存: {report_path}")

    return df


def _try_generate_charts(df: pd.DataFrame, output_dir: Optional[str]):
    """尝试生成分析图表，matplotlib 不可用时静默跳过"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib import rcParams
        # 设置中文字体
        rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
        rcParams['axes.unicode_minus'] = False
    except ImportError:
        print("\n⚠️  matplotlib 未安装，跳过图表生成。可通过 pip install matplotlib 安装。")
        return

    if output_dir is None:
        output_dir = '.'
    os.makedirs(output_dir, exist_ok=True)

    # 检查是否有过热分数据，决定布局
    df_heat = df[df['heat_score'].notna()]
    has_heat = len(df_heat) >= 5
    n_rows = 3 if has_heat else 2
    fig, axes = plt.subplots(n_rows, 2, figsize=(16, 6 * n_rows))
    fig.suptitle('VCP Score 有效性分析', fontsize=16, fontweight='bold')

    # ─── 图1: 散点图 VCP Score vs 收益率 ───
    ax = axes[0, 0]
    colors = df['return_rate'].apply(lambda x: '#2ecc71' if x > 0 else '#e74c3c')
    ax.scatter(df['vcp_score'], df['return_rate'], c=colors, alpha=0.5, s=25, edgecolors='none')
    # 添加趋势线
    z = np.polyfit(df['vcp_score'], df['return_rate'], 1)
    p = np.poly1d(z)
    x_line = np.linspace(df['vcp_score'].min(), df['vcp_score'].max(), 100)
    ax.plot(x_line, p(x_line), 'b--', alpha=0.7, linewidth=1.5, label=f'趋势线 (斜率={z[0]:.2f})')
    ax.axhline(y=0, color='gray', linestyle='-', alpha=0.3)
    ax.set_xlabel('VCP Score')
    ax.set_ylabel('收益率 (%)')
    ax.set_title('VCP Score vs 收益率')
    ax.legend(fontsize=9)

    # ─── 图2: 分档柱状图 ───
    ax = axes[0, 1]
    bins = [0, 1.0, 1.5, 2.0, 2.5, 3.0, float('inf')]
    labels = ['<1.0', '1.0~1.5', '1.5~2.0', '2.0~2.5', '2.5~3.0', '≥3.0']
    df['score_bin'] = pd.cut(df['vcp_score'], bins=bins, labels=labels, right=False)

    bin_stats = df.groupby('score_bin', observed=True).agg(
        avg_return=('return_rate', 'mean'),
        count=('return_rate', 'count'),
        win_rate=('return_rate', lambda x: (x > 0).mean() * 100)
    )

    x_pos = range(len(bin_stats))
    # 使用渐变色方案：从蓝到绿到橙
    color_palette = ['#3498db', '#2ecc71', '#16a085', '#f39c12', '#e67e22', '#e74c3c']
    bar_colors = [color_palette[i % len(color_palette)] for i in range(len(bin_stats))]
    bars = ax.bar(x_pos, bin_stats['avg_return'], color=bar_colors, alpha=0.8, edgecolor='white')

    # 在柱上标注数量和胜率
    for i, (idx, row) in enumerate(bin_stats.iterrows()):
        y_offset = 0.3 if row['avg_return'] >= 0 else -0.8
        ax.text(i, row['avg_return'] + y_offset,
                f"n={int(row['count'])}\n胜率{row['win_rate']:.0f}%",
                ha='center', va='bottom' if row['avg_return'] >= 0 else 'top', fontsize=8)

    ax.set_xticks(x_pos)
    ax.set_xticklabels(bin_stats.index)
    ax.axhline(y=0, color='gray', linestyle='-', alpha=0.3)
    ax.set_xlabel('VCP Score 区间')
    ax.set_ylabel('平均收益率 (%)')
    ax.set_title('各 Score 区间的平均收益率')

    # ─── 图3: VCP 类型对比 ───
    ax = axes[1, 0]
    vcp_order = ['VCP-A', 'VCP-B', 'VCP-C', 'VCP-D']
    vcp_stats = df.groupby('vcp_type').agg(
        avg_return=('return_rate', 'mean'),
        count=('return_rate', 'count'),
        win_rate=('return_rate', lambda x: (x > 0).mean() * 100)
    ).reindex(vcp_order).dropna()

    x_pos = range(len(vcp_stats))
    bar_colors = ['#3498db', '#2ecc71', '#f39c12', '#e74c3c'][:len(vcp_stats)]
    bars = ax.bar(x_pos, vcp_stats['avg_return'], color=bar_colors, alpha=0.8, edgecolor='white')

    for i, (idx, row) in enumerate(vcp_stats.iterrows()):
        y_offset = 0.3 if row['avg_return'] >= 0 else -0.8
        ax.text(i, row['avg_return'] + y_offset,
                f"n={int(row['count'])}\n胜率{row['win_rate']:.0f}%",
                ha='center', va='bottom' if row['avg_return'] >= 0 else 'top', fontsize=8)

    ax.set_xticks(x_pos)
    ax.set_xticklabels(vcp_stats.index)
    ax.axhline(y=0, color='gray', linestyle='-', alpha=0.3)
    ax.set_xlabel('VCP 类型')
    ax.set_ylabel('平均收益率 (%)')
    ax.set_title('各 VCP 类型的平均收益率')

    # ─── 图4: 信号类型对比 ───
    ax = axes[1, 1]
    signal_stats = df.groupby('signal_type').agg(
        avg_return=('return_rate', 'mean'),
        count=('return_rate', 'count'),
        win_rate=('return_rate', lambda x: (x > 0).mean() * 100)
    )
    # 按平均收益排序
    signal_stats = signal_stats.sort_values('avg_return', ascending=False)

    x_pos = range(len(signal_stats))
    # 使用不同颜色区分信号类型
    color_palette = ['#2ecc71', '#3498db', '#f39c12', '#e74c3c', '#9b59b6']
    bar_colors = [color_palette[i % len(color_palette)] for i in range(len(signal_stats))]
    bars = ax.bar(x_pos, signal_stats['avg_return'], color=bar_colors, alpha=0.8, edgecolor='white')

    for i, (idx, row) in enumerate(signal_stats.iterrows()):
        y_offset = 0.3 if row['avg_return'] >= 0 else -0.8
        ax.text(i, row['avg_return'] + y_offset,
                f"n={int(row['count'])}\n胜率{row['win_rate']:.0f}%",
                ha='center', va='bottom' if row['avg_return'] >= 0 else 'top', fontsize=8)

    ax.set_xticks(x_pos)
    ax.set_xticklabels(signal_stats.index)
    ax.axhline(y=0, color='gray', linestyle='-', alpha=0.3)
    ax.set_xlabel('信号类型')
    ax.set_ylabel('平均收益率 (%)')
    ax.set_title('各信号类型的平均收益率')

    # ─── 图5 & 图6: 过热分相关（仅在有数据时绘制） ───
    if has_heat:
        df_h = df_heat.copy()

        # ─── 图5: 过热分 vs 收益率 散点图 ───
        ax = axes[2, 0]
        colors = df_h['return_rate'].apply(lambda x: '#2ecc71' if x > 0 else '#e74c3c')
        ax.scatter(df_h['heat_score'], df_h['return_rate'], c=colors, alpha=0.5, s=25, edgecolors='none')
        # 趋势线
        z_h = np.polyfit(df_h['heat_score'], df_h['return_rate'], 1)
        p_h = np.poly1d(z_h)
        x_line_h = np.linspace(df_h['heat_score'].min(), df_h['heat_score'].max(), 100)
        ax.plot(x_line_h, p_h(x_line_h), 'b--', alpha=0.7, linewidth=1.5,
                label=f'趋势线 (斜率={z_h[0]:.2f})')
        ax.axhline(y=0, color='gray', linestyle='-', alpha=0.3)
        ax.set_xlabel('过热分')
        ax.set_ylabel('收益率 (%)')
        ax.set_title('过热分 vs 收益率（二次确认信号）')
        ax.legend(fontsize=9)

        # ─── 图6: 过热分分档柱状图 ───
        ax = axes[2, 1]
        heat_bins = [0, 0.3, 0.6, 1.0, 1.5, float('inf')]
        heat_labels = ['<0.3', '0.3~0.6', '0.6~1.0', '1.0~1.5', '≥1.5']
        df_h['heat_bin'] = pd.cut(df_h['heat_score'], bins=heat_bins, labels=heat_labels, right=False)

        heat_stats = df_h.groupby('heat_bin', observed=True).agg(
            avg_return=('return_rate', 'mean'),
            count=('return_rate', 'count'),
            win_rate=('return_rate', lambda x: (x > 0).mean() * 100)
        )

        x_pos = range(len(heat_stats))
        # 使用渐变色方案：从浅到深
        color_palette = ['#3498db', '#2ecc71', '#16a085', '#f39c12', '#e67e22']
        bar_colors = [color_palette[i % len(color_palette)] for i in range(len(heat_stats))]
        ax.bar(x_pos, heat_stats['avg_return'], color=bar_colors, alpha=0.8, edgecolor='white')

        for i, (idx, row) in enumerate(heat_stats.iterrows()):
            y_offset = 0.3 if row['avg_return'] >= 0 else -0.8
            ax.text(i, row['avg_return'] + y_offset,
                    f"n={int(row['count'])}\n胜率{row['win_rate']:.0f}%",
                    ha='center', va='bottom' if row['avg_return'] >= 0 else 'top', fontsize=8)

        ax.set_xticks(x_pos)
        ax.set_xticklabels(heat_stats.index)
        ax.axhline(y=0, color='gray', linestyle='-', alpha=0.3)
        ax.set_xlabel('过热分区间')
        ax.set_ylabel('平均收益率 (%)')
        ax.set_title('各过热分区间的平均收益率')

    plt.tight_layout()
    chart_path = os.path.join(output_dir, 'vcp_analysis_charts.png')
    fig.savefig(chart_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"📊 分析图表已保存: {chart_path}")


# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────

def run_vcp_analysis(scan_file: str, backtest_file: str, output_dir: Optional[str] = None):
    """
    执行 VCP 分数有效性分析。

    Args:
        scan_file: 候选股扫描汇总文件路径 (txt)
        backtest_file: 回测报告文件路径 (md)
        output_dir: 输出目录（保存报告和图表），None 则不保存文件
    """
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower().replace('-', '') != 'utf8':
        sys.stdout.reconfigure(encoding='utf-8')

    print(f"📂 候选股文件: {scan_file}")
    print(f"📂 回测报告:   {backtest_file}")

    signals = parse_scan_summary(scan_file)
    print(f"  → 解析到 {len(signals)} 条信号记录")

    trades = parse_backtest_report(backtest_file)
    print(f"  → 解析到 {len(trades)} 条交易记录")

    df = merge_data(signals, trades)
    if df.empty:
        print("❌ 无匹配数据，请检查文件是否对应。")
        return

    return analyze(df, output_dir)


if __name__ == '__main__':
    import sys

    if len(sys.argv) >= 3:
        scan_f = sys.argv[1]
        bt_f = sys.argv[2]
        out_d = sys.argv[3] if len(sys.argv) >= 4 else None
    else:
        # 默认路径
        scan_f = 'bin/candidate_stocks_breakout_a/scan_summary_20251220-20260309.txt'
        bt_f = 'bin/candidate_stocks_breakout_a/backtest/backtest_report_20251220-20260309.md'
        out_d = 'bin/candidate_stocks_breakout_a/backtest'

    run_vcp_analysis(scan_f, bt_f, out_d)
