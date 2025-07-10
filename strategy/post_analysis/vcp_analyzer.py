import re
from pathlib import Path

import pandas as pd
import plotly.express as px


def parse_log_file(file_path):
    """
    解析单个 run_log.txt 文件，提取 VCP 分数和对应的交易盈亏。

    Args:
        file_path (Path): run_log.txt 文件的路径。

    Returns:
        list: 一个包含元组 (stock_name, vcp_score, pnl) 的列表。
    """
    stock_name = file_path.parent.name
    results = []
    last_vcp_score = None

    # Regex patterns
    # 匹配VCP得分行: '... (VCP 参考: VCP-A, Score: 3.94) ***'
    vcp_pattern = re.compile(r"Score: ([\d\.-]+)\) \*\*\*")
    # 匹配交易关闭行: '... 交易关闭, 净盈亏: -2183.84, ...'
    pnl_pattern = re.compile(r"交易关闭, 净盈亏: ([\d\.-]+),")

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            vcp_match = vcp_pattern.search(line)
            if vcp_match:
                # 捕获到一个VCP分数，暂存它
                last_vcp_score = float(vcp_match.group(1))
                continue

            pnl_match = pnl_pattern.search(line)
            if pnl_match and last_vcp_score is not None:
                # 捕获到一笔交易的PnL，与之前暂存的VCP分数配对
                pnl = float(pnl_match.group(1))
                results.append((stock_name, last_vcp_score, pnl))
                # 重置VCP分数，避免重复使用
                last_vcp_score = None

    return results


def analyze_vcp_performance():
    """
    扫描所有 run_log.txt 文件，分析 VCP 分数与交易表现的关系，并生成报告和图表。
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
        print("[!] 未能在日志文件中找到任何 VCP 评分与交易结果的配对。")
        return

    print(f"[*] 共分析了 {len(all_trades)} 笔交易。")
    df = pd.DataFrame(all_trades, columns=['Stock', 'VCP Score', 'PnL'])

    # --- 统计分析 ---
    correlation = df['VCP Score'].corr(df['PnL'])

    # --- 按VCP评级分组分析 ---
    def get_grade(score):
        score = round(score)
        if score >= 4: return "A (>=4)"
        if score == 3: return "B (3)"
        if score == 2: return "C (2)"
        if score == 1: return "D (1)"
        return "F (<1)"

    df['Grade'] = df['VCP Score'].apply(get_grade)
    grade_summary = df.groupby('Grade')['PnL'].agg(['mean', 'count', 'sum']).sort_values(by='mean', ascending=False)

    # --- 生成报告 ---
    print("\n" + "=" * 60)
    print(" VCP 模型表现分析报告")
    print("=" * 60)
    print(f"\n[核心指标] VCP分数与交易盈亏的相关系数: {correlation:.4f}")
    if correlation > 0.3:
        print(" > 解读: 存在正相关关系。VCP分数越高，盈利倾向越强。")
    elif correlation < -0.3:
        print(" > 解读: 存在负相关关系。VCP分数越高，亏损倾向越强 (模型可能反了)。")
    else:
        print(" > 解读: 相关性不强。VCP分数与盈亏无明显线性关系。")

    print("\n--- 各VCP评级平均表现 ---")
    print(grade_summary.to_string(formatters={'mean': '{:,.2f}'.format, 'sum': '{:,.2f}'.format}))
    print("\n" + "=" * 60)

    # --- 可视化 ---
    # 新增：为点的大小创建一个新列
    df['abs_pnl'] = df['PnL'].abs()

    fig = px.scatter(
        df,
        x='VCP Score',
        y='PnL',
        hover_data=['Stock'],
        color='PnL',
        size='abs_pnl',  # 使用绝对盈亏作为点的大小
        color_continuous_scale=px.colors.diverging.RdYlGn,  # 使用红-黄-绿发散色系
        template='plotly_white',  # 使用更清晰的白色背景模板
        title=f'VCP Score vs. PnL (Correlation: {correlation:.4f})',
        labels={'PnL': 'Net Profit/Loss', 'VCP Score': 'VCP Score'}
    )
    fig.add_hline(y=0, line_dash="dash", line_color="grey")

    output_path = analysis_dir / 'vcp_pnl_scatter.html'
    fig.write_html(output_path)

    print(f"\n[*] 分析图表已保存到: {output_path.resolve()}")
    print("[*] 分析完成。")


if __name__ == '__main__':
    # 确保在conda trading环境下运行，因为需要pandas和plotly
    # conda activate trading
    # python strategy/post_analysis/vcp_analyzer.py
    analyze_vcp_performance()
