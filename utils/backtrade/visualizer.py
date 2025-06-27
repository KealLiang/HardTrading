import os
from datetime import timedelta

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from matplotlib import font_manager
from matplotlib.font_manager import FontProperties

plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题


# --- 助手函数 ---

def _format_code(code):
    """确保股票代码为6位字符串,不足则补0。"""
    return str(code).zfill(6)


def read_stock_data(code, data_dir):
    """根据股票代码智能查找并读取CSV文件。"""
    code_str = _format_code(code)
    target_file = None
    try:
        for filename in os.listdir(data_dir):
            if filename.startswith(code_str) and filename.endswith('.csv'):
                target_file = filename
                break
    except FileNotFoundError:
        return None

    if not target_file:
        return None

    file_path = os.path.join(data_dir, target_file)
    try:
        column_names = [
            'date', 'code', 'open', 'close', 'high', 'low', 'volume',
            'amount', 'amplitude', 'pct_chg', 'turnover', 'pe_ratio'
        ]
        df = pd.read_csv(
            file_path, header=None, names=column_names,
            index_col='date', parse_dates=True
        )
        df.index = df.index.tz_localize(None)
        df.rename(columns={
            'open': 'Open', 'close': 'Close', 'high': 'High',
            'low': 'Low', 'volume': 'Volume'
        }, inplace=True)
        return df
    except Exception as e:
        print(f"读取股票 {code_str} 数据时出错: {e}")
        return None


def _get_font_properties():
    """获取一个可用的中文字体属性，优先使用相对路径。"""
    font_path = 'fonts/微软雅黑.ttf'
    if os.path.exists(font_path):
        print(f"成功加载字体: {font_path}")
        return FontProperties(fname=font_path)

    # 备用字体查找
    font_paths_to_try = ['msyh.ttc', 'SimHei.ttf', 'PingFang.ttc', 'Arial Unicode MS.ttf']
    for font_name in font_paths_to_try:
        found_path = font_manager.findfont(font_name, fallback_to_default=True)
        if found_path and os.path.basename(found_path).lower() in font_name.lower():
            print(f"成功加载系统字体: {os.path.basename(found_path)}")
            return FontProperties(fname=found_path)

    print("警告: 未找到任何预设的中文字体。图表标题可能显示为乱码。")
    return None


def _setup_mpf_style():
    """设置mplfinance的图表样式，包括字体和颜色。"""
    font_prop = _get_font_properties()

    mc = mpf.make_marketcolors(
        up='red', down='green',
        edge={'up': 'red', 'down': 'green'},
        wick={'up': 'red', 'down': 'green'},
        volume='inherit'
    )

    rc_params = {'font.family': font_prop.get_name()} if font_prop else {}
    style = mpf.make_mpf_style(
        base_mpf_style='yahoo', marketcolors=mc, rc=rc_params
    )
    return style


def pair_trades(log_csv_path):
    """将买入和卖出日志配对成完整的交易DataFrame。"""
    try:
        log_df = pd.read_csv(log_csv_path, parse_dates=['datetime'])
    except FileNotFoundError:
        print(f"错误: 交易日志 {log_csv_path} 未找到。")
        return pd.DataFrame()

    buys = log_df[log_df['type'] == 'BUY'].copy()
    sells = log_df[log_df['type'] == 'SELL'].copy()

    trades = []
    used_sell_indices = set()

    for _, buy_op in buys.iterrows():
        symbol_str = _format_code(buy_op['symbol'])

        potential_sells = sells[
            (sells['symbol'].apply(_format_code) == symbol_str) &
            (sells['datetime'] > buy_op['datetime']) &
            (~sells.index.isin(used_sell_indices))
            ]

        if not potential_sells.empty:
            sell_op = potential_sells.iloc[0]
            trades.append({
                'symbol': symbol_str,
                'datetime_buy': buy_op['datetime'],
                'price_buy': buy_op['price'],
                'size_buy': buy_op['size'],
                'datetime_sell': sell_op['datetime'],
                'price_sell': sell_op['price'],
                'size_sell': sell_op['size'],
            })
            used_sell_indices.add(sell_op.name)

    return pd.DataFrame(trades)


def _plot_single_trade(trade, trade_id, data_dir, output_dir, style, post_exit_period):
    """为单笔交易生成并保存图表。"""
    stock_code = _format_code(trade['symbol'])
    stock_data = read_stock_data(stock_code, data_dir)

    if stock_data is None:
        print(f"警告: 交易 {trade_id} 未能找到股票代码为 {stock_code} 的数据文件，已跳过。")
        return

    entry_date = trade['datetime_buy']
    exit_date = trade['datetime_sell']
    start_chart = entry_date - timedelta(days=60)
    end_chart = exit_date + timedelta(days=post_exit_period)

    chart_df = stock_data.loc[start_chart:end_chart].copy()
    if chart_df.empty:
        print(f"警告: 交易 {trade_id} 在 {stock_code} 中找不到指定的绘图日期范围，已跳过。")
        return

    # 准备买卖点标记
    buy_markers = [float('nan')] * len(chart_df)
    sell_markers = [float('nan')] * len(chart_df)
    try:
        entry_idx = chart_df.index.searchsorted(entry_date, side='right') - 1
        exit_idx = chart_df.index.searchsorted(exit_date, side='right') - 1
        if entry_idx >= 0:
            buy_markers[entry_idx] = chart_df.iloc[entry_idx]['Low'] * 0.98
        if exit_idx >= 0:
            sell_markers[exit_idx] = chart_df.iloc[exit_idx]['High'] * 1.02
    except (KeyError, IndexError):
        # 如果日期不存在，忽略标记
        pass

    addplots = [
        mpf.make_addplot(buy_markers, type='scatter', marker='^', color='lime', markersize=150),
        mpf.make_addplot(sell_markers, type='scatter', marker='v', color='magenta', markersize=150)
    ]

    pnl = (trade['price_sell'] - trade['price_buy']) * abs(trade['size_sell'])
    title = (
        f"股票: {stock_code} | 交易ID: {trade_id} | {'盈利' if pnl > 0 else '亏损'}: {pnl:.2f}\n"
        f"入场: {entry_date.strftime('%Y-%m-%d')} @ {trade['price_buy']:.2f} | "
        f"出场: {exit_date.strftime('%Y-%m-%d')} @ {trade['price_sell']:.2f}"
    )

    output_path = os.path.join(output_dir, f"trade_{trade_id}_{stock_code}.png")

    fig, axes = mpf.plot(
        chart_df, type='candle', style=style, title=title,
        ylabel='价格', volume=True, ylabel_lower='成交量',
        addplot=addplots, figsize=(16, 8), returnfig=True,
        tight_layout=True
    )

    # 自定义坐标轴，解决日期显示问题
    num_days = len(chart_df)
    interval = max(1, num_days // 20) if num_days > 20 else 1
    axes[0].xaxis.set_major_locator(mdates.DayLocator(interval=interval))
    fig.autofmt_xdate(rotation=30)

    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"已生成图表: {output_path}")


# --- 主函数 ---

def analyze_and_visualize_trades(
        log_csv='trade_log.csv',
        data_dir='data/astocks',
        output_dir='strategy/post_analysis',
        post_exit_period=60
):
    """
    读取交易日志，配对买卖操作，并对每笔完整交易进行可视化。
    """
    trades_df = pair_trades(log_csv)
    if trades_df.empty:
        print("未能配对任何完整的买卖交易。请检查日志文件。")
        return

    print(f"\n成功配对 {len(trades_df)} 笔完整交易。开始生成图表...")

    style = _setup_mpf_style()

    for i, trade in trades_df.iterrows():
        try:
            _plot_single_trade(
                trade=trade,
                trade_id=i + 1,
                data_dir=data_dir,
                output_dir=output_dir,
                style=style,
                post_exit_period=post_exit_period
            )
        except Exception as e:
            print(f"\n错误: 为交易 {i + 1} 生成图表时发生未知错误: {e}")
            import traceback
            print(traceback.format_exc())

    print("\n所有交易可视化完成。")


if __name__ == '__main__':
    print("作为独立脚本运行 visualizer...")
    # 确保调试时输出目录存在
    debug_output_dir = './strategy/post_analysis/debug_run'
    os.makedirs(debug_output_dir, exist_ok=True)
    analyze_and_visualize_trades(
        log_csv='./trade_log.csv',
        data_dir='./data/astocks',
        output_dir=debug_output_dir
    )
