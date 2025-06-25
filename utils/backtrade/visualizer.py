import os
from datetime import timedelta

import mplfinance as mpf
import pandas as pd


# from utils.backtrade.data_loader import read_stock_data # <- 移除依赖

def read_stock_data(code, data_dir):
    """
    内联的数据加载函数，使 visualizer.py 独立。
    """
    target_file = None
    try:
        for filename in os.listdir(data_dir):
            if filename.startswith(str(code)) and filename.endswith('.csv'):
                target_file = filename
                break
    except FileNotFoundError:
        return None

    if not target_file:
        return None

    file_path = os.path.join(data_dir, target_file)
    try:
        # 修正列名顺序以匹配源文件: open, close, high, low
        column_names = [
            'datetime', 'code', 'open', 'close', 'high', 'low', 'volume',
            'amount', 'amplitude', 'pct_chg', 'turnover', 'pe_ratio'
        ]
        df = pd.read_csv(
            file_path, header=None, names=column_names,
            index_col='datetime', parse_dates=True
        )
        # mplfinance 需要大写的列名，这里直接重命名
        df.rename(columns={
            'open': 'Open', 'close': 'Close', 'high': 'High',
            'low': 'Low', 'volume': 'Volume'
        }, inplace=True)
        return df
    except Exception:
        return None


def analyze_and_visualize_trades(
        log_csv='trade_log.csv',
        data_dir='data/astocks',
        output_dir='strategy/post_analysis',
        post_exit_period=60
):
    """
    读取交易日志，配对买卖操作，并对每笔完整交易进行可视化。

    参数:
    - log_csv: 交易日志CSV文件路径。
    - data_dir: 股票日线数据(.csv文件)所在的目录。
    - output_dir: 生成的图表保存的目录。
    - post_exit_period: 在图表中显示卖出点之后的K线天数，用于离场后分析。
    """
    # 1. 读取并处理交易日志
    try:
        log_df = pd.read_csv(log_csv, parse_dates=['datetime'])
    except FileNotFoundError:
        print(f"错误: 交易日志 {log_csv} 未找到。请先运行回测生成该文件。")
        return

    buys = log_df[log_df['type'] == 'BUY'].copy()
    sells = log_df[log_df['type'] == 'SELL'].copy()

    trades = []
    used_sell_indices = set()

    for _, buy_op in buys.iterrows():
        # 寻找此买入操作对应的卖出操作
        # 条件：同一个股票代码，在买入之后发生，且尚未被配对的第一个卖出
        potential_sells = sells[
            (sells['symbol'] == buy_op['symbol']) &
            (sells['datetime'] > buy_op['datetime']) &
            (~sells.index.isin(used_sell_indices))
            ]

        if not potential_sells.empty:
            sell_op = potential_sells.iloc[0]

            trade = {
                'symbol': buy_op['symbol'],
                'datetime_buy': buy_op['datetime'],
                'price_buy': buy_op['price'],
                'size_buy': buy_op['size'],
                'datetime_sell': sell_op['datetime'],
                'price_sell': sell_op['price'],
                'size_sell': sell_op['size'],
            }
            trades.append(trade)
            used_sell_indices.add(sell_op.name)

    if not trades:
        print("未能配对任何完整的买卖交易。请检查日志文件。")
        return

    trades_df = pd.DataFrame(trades)
    print(f"成功配对 {len(trades_df)} 笔完整交易。开始生成图表...")

    # 2. 遍历每一笔交易并生成图表
    for trade_id, trade in trades_df.iterrows():
        stock_code = str(trade['symbol'])
        stock_data = read_stock_data(stock_code, data_dir)

        if stock_data is None:
            continue

        entry_date = trade['datetime_buy']
        exit_date = trade['datetime_sell']

        start_chart = entry_date - timedelta(days=60)
        end_chart = exit_date + timedelta(days=post_exit_period)

        chart_df = stock_data.loc[start_chart:end_chart].copy()

        if chart_df.empty:
            print(f"警告: 交易 {trade_id + 1} 在 {stock_code} 中找不到指定的日期范围。")
            continue

        # 标记买卖点
        buy_markers = [float('nan')] * len(chart_df)
        sell_markers = [float('nan')] * len(chart_df)
        try:
            entry_idx = chart_df.index.searchsorted(entry_date, side='right') - 1
            exit_idx = chart_df.index.searchsorted(exit_date, side='right') - 1
            if entry_idx >= 0:
                buy_markers[entry_idx] = chart_df.iloc[entry_idx]['Low'] * 0.98
            if exit_idx >= 0:
                sell_markers[exit_idx] = chart_df.iloc[exit_idx]['High'] * 1.02
        except (KeyError, IndexError) as e:
            print(f"警告: 在为交易 {trade_id + 1} 标记买卖点时出错: {e}。")
            continue

        ap = [
            mpf.make_addplot(buy_markers, type='scatter', marker='^', color='g', markersize=100),
            mpf.make_addplot(sell_markers, type='scatter', marker='v', color='r', markersize=100)
        ]

        pnl = (trade['price_sell'] - trade['price_buy']) * abs(trade['size_sell'])
        pnl_status = "盈利" if pnl > 0 else "亏损"
        title = (
            f"股票: {stock_code} | 交易ID: {trade_id + 1} | {pnl_status}: {pnl:.2f}\\n"
            f"入场: {entry_date.strftime('%Y-%m-%d')} @ {trade['price_buy']:.2f} | "
            f"出场: {exit_date.strftime('%Y-%m-%d')} @ {trade['price_sell']:.2f}"
        )

        output_path = os.path.join(output_dir, f"trade_{trade_id + 1}_{stock_code}.png")

        try:
            mpf.plot(
                chart_df, type='candle', style='charles', title=title,
                ylabel='价格', volume=True, ylabel_lower='成交量',
                addplot=ap, figsize=(16, 8), savefig=dict(fname=output_path, dpi=150)
            )
            print(f"已生成图表: {output_path}")
        except Exception as e:
            print(f"\\n错误: mplfinance绘图失败 (交易ID: {trade_id + 1}): {e}")

    print("\\n所有交易可视化完成。")


if __name__ == '__main__':
    # 当作为脚本独立运行时，使用默认参数，这主要用于调试
    # 假设日志和数据在当前目录的相对位置
    print("作为独立脚本运行 visualizer...")
    analyze_and_visualize_trades(
        log_csv='./trade_log.csv',
        data_dir='./data/astocks',
        output_dir='./strategy/post_analysis/debug_run'
    )
