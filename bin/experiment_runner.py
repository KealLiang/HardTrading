import os
import re
from datetime import datetime
from pathlib import Path
from contextlib import redirect_stdout
import pandas as pd

# 依赖项，需要确保这些模块可以被正确导入
from bin import simulator
from strategy.breakout_strategy import BreakoutStrategy


# --- Core Backtesting Function (moved and adapted from simulator.py) ---

def run_batch_backtest(strategy_class, strategy_params, stock_codes, summary_filepath,
                      startdate=None, enddate=None, amount=100000):
    """
    对预设的股票池进行批量回测，并将所有控制台输出汇总到指定的日志文件中。
    这是从 simulator.py 中移动并改造的。

    Args:
        strategy_class: 要运行的策略类。
        strategy_params: 策略的参数字典。
        stock_codes: 要回测的股票代码列表。
        summary_filepath: 结果汇总文件的完整路径。
        startdate: 回测开始日期，默认为datetime(2022, 1, 1)。
        enddate: 回测结束日期，默认为datetime(2025, 7, 4)。
        amount: 初始资金，默认为100000。
    """
    # 设置默认日期
    if startdate is None:
        startdate = datetime(2022, 1, 1)
    if enddate is None:
        enddate = datetime(2025, 7, 4)

    output_dir = os.path.dirname(summary_filepath)
    os.makedirs(output_dir, exist_ok=True)

    print(f"批量回测启动，结果将保存到: {summary_filepath}")

    with open(summary_filepath, 'w', encoding='utf-8') as f:
        with redirect_stdout(f):
            print(f"===== 批量回测报告 =====")
            print(f"策略: {strategy_class.__name__}")
            print(f"参数: {strategy_params}")
            print(f"回测时间范围: {startdate.strftime('%Y-%m-%d')} 至 {enddate.strftime('%Y-%m-%d')}")
            print(f"初始资金: {amount:,}")
            print(f"回测时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("=" * 80)

            for code in stock_codes:
                print(f"--- 开始回测股票: {code} ---")
                try:
                    # 注意：批量回测时，关闭交互式绘图以避免阻塞
                    simulator.go_trade(
                        code=code,
                        amount=amount,
                        startdate=startdate,
                        enddate=enddate,
                        strategy=strategy_class,
                        strategy_params=strategy_params,
                        log_trades=True,
                        visualize=False,
                        interactive_plot=False
                    )
                    print(f"--- 股票: {code} 回测完成 ---")
                except Exception as e:
                    print(f"--- 股票: {code} 回测失败: {e} ---")
                print("-" * 60)

            print("===== 批量回测全部完成 =====")
    print(f"批量回测执行完毕。请查看报告: {summary_filepath}")


# --- Comparison Logic (moved and adapted from compare_backtests.py) ---

def _get_change_description(metric_name, old_val, new_val):
    """
    Generates a qualitative description of the change between two metric values.
    """
    if old_val == 'N/A' or new_val == 'N/A':
        return "N/A"

    if not isinstance(old_val, (int, float)) or not isinstance(new_val, (int, float)):
        return "类型错误"

    higher_is_better = [
        'final_value', 'annualized_return', 'sharpe_ratio',
        'total_return', 'alpha'
    ]

    is_higher_better = metric_name in higher_is_better

    if abs(old_val) < 1e-9:
        if new_val > 1e-9:
            return "⬆️ 新增"
        return "➡️ 无变化"

    pct_change = (new_val - old_val) / abs(old_val) * 100

    NO_CHANGE_THRESHOLD = 0.1
    SIGNIFICANT_CHANGE_THRESHOLD = 5.0

    if abs(pct_change) < NO_CHANGE_THRESHOLD:
        return "➡️ 无变化"

    is_improvement = (pct_change > 0) if is_higher_better else (pct_change < 0)

    if is_improvement:
        if abs(pct_change) > SIGNIFICANT_CHANGE_THRESHOLD:
            return f"😀 显著改善 ({pct_change:+.1f}%)"
        else:
            return f"😊 轻微改善 ({pct_change:+.1f}%)"
    else:
        if abs(pct_change) > SIGNIFICANT_CHANGE_THRESHOLD:
            return f"😨 显著变差 ({pct_change:+.1f}%)"
        else:
            return f"😭 轻微变差 ({pct_change:+.1f}%)"


def _parse_backtest_summary(file_content):
    """
    Parses a backtest summary file and extracts key metrics for each stock.
    """
    stock_sections = re.split(r'--- 开始回测股票: (.*?) ---', file_content)
    results = {}
    if len(stock_sections) < 2: return results

    for i in range(1, len(stock_sections), 2):
        stock_code = stock_sections[i].strip()
        content = stock_sections[i + 1]
        metrics = {}
        patterns = {
            'final_value': r'回测结束后资金:\s*([\d\.,\-]+)',
            'max_drawdown': r'最大回撤:\s*([\d\.\-]+)%',
            'annualized_return': r'年化收益率:\s*([\d\.\-]+)%',
            'sharpe_ratio': r'夏普比率:\s*([\d\.\-]+)',
            'total_return': r'策略总收益率:\s*([\d\.\-]+)%',
            'alpha': r'超额收益:\s*([\d\.\-]+)%',
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                try:
                    metrics[key] = float(match.group(1).replace(',', ''))
                except (ValueError, AttributeError):
                    metrics[key] = 'N/A'
            else:
                metrics[key] = 'N/A'
        results[stock_code] = metrics
    return results


def compare_and_save_results(file1_path_str, file2_path_str, output_dir_str):
    """
    读取两个回测结果文件，生成对比报告，并保存到指定的输出目录。
    """
    file1 = Path(file1_path_str)
    file2 = Path(file2_path_str)
    output_dir = Path(output_dir_str)

    os.makedirs(output_dir, exist_ok=True)

    if not file1.is_file() or not file2.is_file():
        print(f"错误: 找不到对比文件 {file1} 或 {file2}")
        return

    content1 = file1.read_text(encoding='utf-8')
    content2 = file2.read_text(encoding='utf-8')

    results1 = _parse_backtest_summary(content1)
    results2 = _parse_backtest_summary(content2)

    if file1.stat().st_mtime > file2.stat().st_mtime:
        new_results, old_results = results1, results2
        new_name, old_name = file1.name, file2.name
    else:
        new_results, old_results = results2, results1
        new_name, old_name = file2.name, file1.name

    all_stocks = sorted(set(old_results.keys()) | set(new_results.keys()))
    data = []

    if not old_results or not new_results:
        print("警告: 至少一个结果集为空，无法生成对比报告。")
        return

    default_metrics = {key: 'N/A' for key in next(iter(new_results.values()), {})}
    metric_map = {
        'final_value': '最终资金',
        'max_drawdown': '最大回撤 (%)',
        'annualized_return': '年化收益 (%)',
        'sharpe_ratio': '夏普比率',
        'total_return': '策略总收益率 (%)',
        'alpha': '超额收益 (%)',
    }

    for stock in all_stocks:
        old_metrics = old_results.get(stock, default_metrics)
        new_metrics = new_results.get(stock, default_metrics)
        for key, display_name in metric_map.items():
            old_val = old_metrics.get(key, 'N/A')
            new_val = new_metrics.get(key, 'N/A')
            change_desc = _get_change_description(key, old_val, new_val)
            row_stock_name = stock if key == 'final_value' else ''
            data.append({
                '股票代码': row_stock_name,
                '指标': display_name,
                '旧版': old_val,
                '新版': new_val,
                '变化': change_desc
            })
        if stock != all_stocks[-1]:
            data.append({'股票代码': '---', '指标': '---', '旧版': '---', '新版': '---', '变化': '---'})

    df = pd.DataFrame(data)

    for col in ['旧版', '新版']:
        df[col] = df[col].apply(lambda x: f'{x:,.2f}' if isinstance(x, float) else x)

    df = df.rename(columns={'旧版': f'旧版 ({old_name})', '新版': f'新版 ({new_name})'})

    output_path = output_dir / f'comparison_report_{old_name.split(".")[0]}_vs_{new_name.split(".")[0]}.md'
    title = f"# 回测对比报告: `{old_name}` vs `{new_name}`\n\n"
    markdown_output = title + df.to_markdown(index=False)

    try:
        output_path.write_text(markdown_output, encoding='utf-8')
        print(f"\n✅ 对比报告已成功保存至: {output_path.resolve()}\n")
    except Exception as e:
        print(f"\n❌ 保存文件失败: {e}\n")


# --- Main Orchestration Function ---

def run_comparison_experiment():
    """
    一键化参数对比实验的总指挥。
    在这里修改和定义你要测试的参数。
    """
    print("=== 开始一键化参数对比实验 ===")

    # 1. 定义你要对比的两套参数
    params_A = {
        'debug': False,
        # 基准参数...
    }
    params_B = {
        'debug': False,
        'atr_multiplier': 2.5,
        'bband_period': 25
        # 在这里添加或修改你想测试的参数
    }

    # 2. 定义股票池和输出文件
    stock_pool = ['300033', '300059', '000062', '300204', '600610', '002693', '301357', '600744', '002173', '002640', '002104', '002658']
    output_dir = "bin/post_analysis"

    file_A = os.path.join(output_dir, "backtest_baseline.txt")
    file_B = os.path.join(output_dir, "backtest_challenger.txt")

    # 3. 运行基准版回测
    print("\n[1/3] 正在运行基准版参数回测...")
    run_batch_backtest(
        strategy_class=BreakoutStrategy,
        strategy_params=params_A,
        stock_codes=stock_pool,
        summary_filepath=file_A
    )

    # 4. 运行挑战版回测
    print("\n[2/3] 正在运行挑战版参数回测...")
    run_batch_backtest(
        strategy_class=BreakoutStrategy,
        strategy_params=params_B,
        stock_codes=stock_pool,
        summary_filepath=file_B
    )

    # 5. 生成对比报告
    print("\n[3/3] 正在生成对比报告...")
    compare_and_save_results(file_A, file_B, output_dir)

    print("\n=== 一键对比实验完成！ ===")


if __name__ == '__main__':
    # 当直接运行此脚本时，执行实验
    run_comparison_experiment() 