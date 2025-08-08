import os
import pandas as pd
from datetime import datetime
from tqdm import tqdm
import logging

# 依赖项
from bin import simulator
from strategy.breakout_strategy import BreakoutStrategy


def run_psq_analysis_report():
    """
    一键化执行PSQ综合分析，并生成最终报告。
    """
    print("=== 开始执行PSQ聚合分析报告生成流程 ===")

    # 1. 定义用于分析的股票池和回测时间
    # 注意：为了得到有统计意义的结果，这个列表最好包含10个以上有代表性的股票
    stock_pool = [
        '300033', '300059', '000062', '300204', '600610', '002693',
        '301357', '600744', '002173', '002640', '002104', '002658',
        '000014'
    ]
    start_date = datetime(2022, 1, 1)
    end_date = datetime(2025, 7, 4)
    output_dir = "bin/post_analysis"
    os.makedirs(output_dir, exist_ok=True)

    # 2. 批量运行回测并捕获所有交易的PSQ数据
    print(f"\n[1/3] 正在对 {len(stock_pool)} 只股票进行回测以收集PSQ数据...")
    all_trades_globally = []
    with tqdm(total=len(stock_pool), desc="回测进度") as pbar:
        for stock_code in stock_pool:
            try:
                # 运行回测，并直接捕获返回的交易数据
                # 注意：这里需要 go_trade 函数返回 all_trades_data
                trade_data = simulator.go_trade(
                    code=stock_code,
                    amount=100000,
                    startdate=start_date,
                    enddate=end_date,
                    strategy=BreakoutStrategy,
                    strategy_params={'debug': True},  # 必须开启debug才能生成分析报告
                    log_trades=False,  # 在分析阶段可以关闭交易日志以加速
                    visualize=False,  # 关闭可视化以加速
                    interactive_plot=False
                )
                if trade_data:
                    # 为每笔交易数据添加股票代码，便于追溯
                    for trade in trade_data:
                        trade['code'] = stock_code
                    all_trades_globally.extend(trade_data)

            except Exception as e:
                logging.error(f"分析股票 {stock_code} 时出错: {e}")
            pbar.update(1)

    if not all_trades_globally:
        print("\n未能收集到任何交易数据，程序终止。请检查策略和数据。")
        return

    print(f"\n[2/3] 数据收集完成，共捕获 {len(all_trades_globally)} 笔交易。正在进行统计分析...")

    # 3. 对捕获的数据进行分类和统计
    df = pd.DataFrame(all_trades_globally)

    # a. 分类交易
    pnl_std_dev = df['pnl'].std()
    significance_threshold = 0.25 * pnl_std_dev
    winners = df[df['pnl'] > significance_threshold]
    losers = df[df['pnl'] < -significance_threshold]
    mediocre = df[(-significance_threshold <= df['pnl']) & (df['pnl'] <= significance_threshold)]

    # b. 定义要分析的PSQ指标
    psq_metrics = {
        'obs_scores': '观察期平均PSQ',
        'obs_end_score': '入场日PSQ (观察期终值)',
        'pos_scores': '持仓期平均PSQ',
        'pos_first_n_scores': '持仓期前3日平均PSQ'
    }

    # 为了计算，需要先将列表形式的PSQ分数转换成平均分
    df['obs_scores'] = df['obs_scores'].apply(lambda x: sum(x) / len(x) if x else 0)
    df['obs_end_score'] = df['obs_scores'].apply(lambda x: x[-1] if isinstance(x, list) and x else 0)
    df['pos_scores'] = df['pos_scores'].apply(lambda x: sum(x) / len(x) if x else 0)
    df['pos_first_n_scores'] = df['pos_scores'].apply(lambda x: sum(x[:3]) / len(x[:3]) if isinstance(x, list) and x else 0)


    def calculate_enhanced_stats(dataframe, psq_metrics_map):
        report_data = []
        for col_name, display_name in psq_metrics_map.items():
            if col_name in dataframe.columns and not dataframe[col_name].empty:
                # 使用 .describe() 一次性计算所有核心统计量
                stats = dataframe[col_name].describe()
                report_data.append({
                    'PSQ指标': display_name,
                    '计数': int(stats.get('count', 0)),
                    '平均值': stats.get('mean', 0),
                    '标准差': stats.get('std', 0),
                    '最小值': stats.get('min', 0),
                    '25%分位': stats.get('25%', 0),
                    '中位数': stats.get('50%', 0),
                    '75%分位': stats.get('75%', 0),
                    '最大值': stats.get('max', 0),
                })
        return pd.DataFrame(report_data)

    # c. 生成各个类别的统计报告
    winner_stats_df = calculate_enhanced_stats(winners, psq_metrics)
    mediocre_stats_df = calculate_enhanced_stats(mediocre, psq_metrics)
    loser_stats_df = calculate_enhanced_stats(losers, psq_metrics)

    # 4. 生成Markdown格式的最终报告
    print("\n[3/3] 分析完成，正在生成Markdown报告...")
    report_path = os.path.join(output_dir, "psq_summary_report.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# PSQ 特征聚合分析报告\n\n")
        f.write(f"- **分析股票池**: `{stock_pool}`\n")
        f.write(f"- **回测时间范围**: `{start_date.strftime('%Y-%m-%d')}` to `{end_date.strftime('%Y-%m-%d')}`\n")
        f.write(f"- **总交易笔数**: {len(all_trades_globally)}\n\n")

        def format_df_to_markdown(df, title):
            if df.empty:
                return f"### {title}\n\n无数据\n\n"
            # 格式化浮点数列
            for col in ['平均值', '标准差', '最小值', '25%分位', '中位数', '75%分位', '最大值']:
                if col in df.columns:
                    df[col] = df[col].apply(lambda x: f"{x:.2f}")
            return f"### {title}\n\n{df.to_markdown(index=False)}\n\n"

        f.write(format_df_to_markdown(winner_stats_df, f"盈利交易特征 ({len(winners)} 笔)"))
        f.write(format_df_to_markdown(mediocre_stats_df, f"平庸交易特征 ({len(mediocre)} 笔)"))
        f.write(format_df_to_markdown(loser_stats_df, f"亏损交易特征 ({len(losers)} 笔)"))

    print(f"\n✅ PSQ聚合分析报告已成功保存至: {os.path.abspath(report_path)}")
    print("\n=== 分析流程全部完成！ ===")


if __name__ == '__main__':
    run_psq_analysis_report() 