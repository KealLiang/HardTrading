import re
from pathlib import Path

import pandas as pd
import plotly.express as px


def parse_log_file(file_path):
    """
    解析单个 run_log.txt 文件，提取与每笔交易相关的全套评分数据。

    Args:
        file_path (Path): run_log.txt 文件的路径。

    Returns:
        list: 一个包含字典的列表，每个字典代表一笔完整的交易及其所有评分。
    """
    stock_name = file_path.parent.name.split('_')[0]  # 移除日期部分
    results = []

    # 使用一个字典来暂存当前交易周期内的所有评分
    last_scores = {}

    # --- 正则表达式 ---
    # 匹配初始信号及其构成 (总分必须在最后，因为它包含了前面的所有内容)
    signal_pattern = re.compile(
        r"环境\(分:(\d+).*?"
        r"压缩\(分:(\d+).*?"
        r"量能\(分:(\d+).*?"
        r"总分: (\d+)"
    )
    # 匹配二次确认信号时的过热分和VCP分
    confirm_pattern = re.compile(
        r"当前过热分: ([\d\.-]+).*?"
        r"\(VCP 参考: .*?, Score: ([\d\.-]+)\) \*\*\*"
    )
    # 匹配交易关闭时的盈亏
    pnl_pattern = re.compile(r"交易关闭, 净盈亏: ([\d\.-]+),")

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            signal_match = signal_pattern.search(line)
            if signal_match:
                # 每次出现新的初始信号，就更新暂存的分数
                last_scores['env_score'] = int(signal_match.group(1))
                last_scores['squeeze_score'] = int(signal_match.group(2))
                last_scores['volume_score'] = int(signal_match.group(3))
                last_scores['total_score'] = int(signal_match.group(4))
                continue

            confirm_match = confirm_pattern.search(line)
            if confirm_match:
                # 捕获到二次确认信号，记录当时的分数
                last_scores['overheat_score'] = float(confirm_match.group(1))
                last_scores['vcp_score'] = float(confirm_match.group(2))
                continue

            pnl_match = pnl_pattern.search(line)
            if pnl_match and 'vcp_score' in last_scores:
                # 交易关闭，并且我们已经捕获了VCP分数，说明这是一笔完整的交易
                pnl = float(pnl_match.group(1))

                # 将所有暂存的评分与这笔交易的PnL关联
                final_trade_data = last_scores.copy()
                final_trade_data['PnL'] = pnl
                final_trade_data['Stock'] = stock_name
                results.append(final_trade_data)

                # 重置暂存字典，为下一笔交易做准备
                last_scores = {}

    return results


def create_scatter_plot(df, score_column, pnl_column, title):
    """
    创建一个散点图的 Plotly Figure 对象。
    """
    if score_column not in df.columns or df[score_column].isnull().all():
        return None

    correlation = df[score_column].corr(df[pnl_column])

    fig = px.scatter(
        df,
        x=score_column,
        y=pnl_column,
        hover_data=['Stock'],
        color=pnl_column,
        size='abs_pnl',
        color_continuous_scale=px.colors.diverging.RdYlGn,
        template='plotly_white',
        title=f'{title} (Correlation: {correlation:.4f})',
        labels={'PnL': 'Net Profit/Loss', score_column: title}
    )
    fig.add_hline(y=0, line_dash="dash", line_color="grey")
    return fig, correlation


def analyze_score_performance():
    """
    扫描所有 run_log.txt 文件，分析所有关键分数与交易表现的关系，并生成统一的报告和图表。
    """
    analysis_dir = Path(__file__).parent
    all_trades = []

    print(f"[*] 正在扫描目录: {analysis_dir}")
    log_files = list(analysis_dir.rglob('**/run_log.txt'))

    if not log_files:
        print("[!] 未找到任何 run_log.txt 文件。请确保已运行回测。")
        return

    print(f"[*] 找到 {len(log_files)} 个日志文件，开始解析...")
    for log_file in log_files:
        trades = parse_log_file(log_file)
        all_trades.extend(trades)

    if not all_trades:
        print("[!] 未能在日志文件中找到任何完整的交易评分数据。请检查日志格式。")
        return

    print(f"[*] 共分析了 {len(all_trades)} 笔交易。")
    df = pd.DataFrame(all_trades)
    df['abs_pnl'] = df['PnL'].abs()

    # --- 待分析的评分列和它们的图表标题 ---
    scores_to_analyze = {
        'vcp_score': 'VCP Score',
        'total_score': 'Initial Signal Score',
        'env_score': 'Environment Score',
        'squeeze_score': 'Squeeze Score',
        'volume_score': 'Volume Score',
        'overheat_score': 'Overheat Score',
    }

    figures = []
    correlations = {}

    # --- 核心分析循环 ---
    for col, title in scores_to_analyze.items():
        fig, corr = create_scatter_plot(df, col, 'PnL', title)
        if fig:
            figures.append(fig)
            correlations[title] = corr

    # --- 生成控制台报告 ---
    print("\n" + "=" * 60)
    print(" 全维度模型表现分析报告")
    print("=" * 60)
    print("\n[核心指标] 各分数与交易盈亏的相关系数:")
    for title, corr in correlations.items():
        interpretation = ""
        if corr > 0.3:
            interpretation = "-> (强正相关)"
        elif corr > 0.1:
            interpretation = "-> (弱正相关)"
        elif corr < -0.3:
            interpretation = "-> (强负相关, 符合预期!)" if "Overheat" in title else "-> (强负相关, 模型可能反了!)"
        elif corr < -0.1:
            interpretation = "-> (弱负相关)"
        print(f"  - {title:<22}: {corr: .4f} {interpretation}")
    print("\n" + "=" * 60)

    # --- 可视化：将所有图表合并到一个HTML文件 ---
    if not figures:
        print("[!] 没有任何图表可以生成。")
        return

    output_path = analysis_dir / 'full_score_analysis.html'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("<html><head><title>全维度VCP模型分析</title></head><body>")
        f.write("<h1>全维度VCP模型分析报告</h1>")
        for fig in figures:
            f.write(fig.to_html(full_html=False, include_plotlyjs='cdn'))
            f.write("<hr>")  # 添加分割线
        f.write("</body></html>")

    print(f"\n[*] 全维度分析图表已保存到: {output_path.resolve()}")
    print("[*] 分析完成。")


if __name__ == '__main__':
    analyze_score_performance()
