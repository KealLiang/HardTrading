import re
from pathlib import Path

import pandas as pd

# --- 用户配置 ---
# 在这里直接修改您想要对比的两个文件名
FILE1_NAME = 'backtest_summary.txt'
FILE2_NAME = 'backtest_summary2.txt'


# --- 配置结束 ---

def get_change_description(metric_name, old_val, new_val):
    """
    Generates a qualitative description of the change between two metric values.
    """
    if old_val == 'N/A' or new_val == 'N/A':
        return "N/A"

    if not isinstance(old_val, (int, float)) or not isinstance(new_val, (int, float)):
        return "类型错误"

    # Define which metrics are better when higher
    higher_is_better = [
        'final_value', 'annualized_return', 'sharpe_ratio',
        'total_return', 'alpha'
    ]

    # Max drawdown is better when lower
    is_higher_better = metric_name in higher_is_better

    if abs(old_val) < 1e-9:  # Avoid division by zero
        if new_val > 1e-9:
            return "⬆️ 新增"
        return "➡️ 无变化"

    pct_change = (new_val - old_val) / abs(old_val) * 100

    # Define thresholds
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


def parse_backtest_summary(file_content):
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


def compare_results(old_results, new_results, old_name, new_name):
    """
    Compares two sets of backtest results and returns a pandas DataFrame.
    """
    all_stocks = sorted(set(old_results.keys()) | set(new_results.keys()))
    data = []
    if not old_results or not new_results:
        print("Warning: One of the result sets is empty. Cannot generate comparison.")
        return pd.DataFrame()

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
            change_desc = get_change_description(key, old_val, new_val)

            # Use stock name for the first metric row, empty for others
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
    return df


def run_comparison():
    """
    Main function to run the backtest comparison.
    Hardcoded file paths for direct execution.
    """
    script_dir = Path(__file__).parent
    file1 = script_dir / FILE1_NAME
    file2 = script_dir / FILE2_NAME

    if not file1.is_file():
        print(f"Error: File not found at {file1}")
        return
    if not file2.is_file():
        print(f"Error: File not found at {file2}")
        return

    content1 = file1.read_text(encoding='utf-8')
    content2 = file2.read_text(encoding='utf-8')

    results1 = parse_backtest_summary(content1)
    results2 = parse_backtest_summary(content2)

    if file1.stat().st_mtime > file2.stat().st_mtime:
        new_results, old_results = results1, results2
        new_name, old_name = file1.name, file2.name
    else:
        new_results, old_results = results2, results1
        new_name, old_name = file2.name, file1.name

    comparison_df = compare_results(old_results, new_results, old_name, new_name)

    if comparison_df.empty:
        return

    # Determine output path
    output_path = script_dir / f'comparison_report_{old_name.split(".")[0]}_vs_{new_name.split(".")[0]}.md'

    # Generate title and markdown table
    title = f"# 回测对比报告: `{old_name}` vs `{new_name}`\n\n"
    markdown_output = title + comparison_df.to_markdown(index=False)

    # Save to file
    try:
        output_path.write_text(markdown_output, encoding='utf-8')
        print(f"\n✅ 对比报告已成功保存至: {output_path.resolve()}\n")
    except Exception as e:
        print(f"\n❌ 保存文件失败: {e}\n")


if __name__ == '__main__':
    run_comparison()
