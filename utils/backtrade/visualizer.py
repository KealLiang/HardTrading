import os
import re
from datetime import timedelta

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from matplotlib import font_manager
from matplotlib.font_manager import FontProperties

from strategy.constant.signal_constants import SIGNAL_MARKER_MAP, SIG_UNKNOWN, SIG_SOURCE

plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题


def _extract_scores_from_details(signal_info):
    """从信号详情中解析VCP和过热分"""
    if not signal_info:
        return None, None

    details_text = ""
    # 优先寻找包含VCP分数的 '二次确认' 信号
    for signal in signal_info:
        # 寻找最可能包含分数的信号详情
        current_details = signal.get('details', '')
        if 'VCP' in current_details and '过热分' in current_details:
            details_text = current_details
            break

    if not details_text:
        return None, None

    overheat_match = re.search(r'过热分:\s*([\d\.]+)', details_text)
    vcp_match = re.search(r'Score:\s*([\d\.\-]+)', details_text)

    overheat_score = overheat_match.group(1) if overheat_match else None
    vcp_score = vcp_match.group(1) if vcp_match else None

    return overheat_score, vcp_score


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


def _add_signal_markers_to_plot(chart_df, signal_info):
    """
    根据信号信息，在图表上添加标记。
    返回一个 addplots 列表和一个 used_signal_types 列表。
    """
    if not signal_info:
        return [], []

    # 过滤掉超出图表范围的信号
    filtered_signal_info = []
    chart_start_date = pd.to_datetime(chart_df.index[0]).date()
    chart_end_date = pd.to_datetime(chart_df.index[-1]).date()

    for signal in signal_info:
        signal_date = signal['date']
        if isinstance(signal_date, str):
            signal_date = pd.to_datetime(signal_date).date()
        elif hasattr(signal_date, 'date'):
            signal_date = signal_date.date()

        if chart_start_date <= signal_date <= chart_end_date:
            filtered_signal_info.append(signal)

    signal_markers_dict = {}
    used_signal_types = []
    addplots = []

    for signal in filtered_signal_info:
        signal_date = signal['date']
        signal_type = signal['type']

        if signal_type not in signal_markers_dict:
            signal_markers_dict[signal_type] = [float('nan')] * len(chart_df)
            used_signal_types.append(signal_type)

        try:
            signal_dt = pd.to_datetime(signal_date)
            marker_idx = chart_df.index.searchsorted(signal_dt, side='right') - 1
            if marker_idx >= 0 and marker_idx < len(chart_df):  # 确保索引在有效范围内
                vertical_offset = 0.95
                if signal_type in ['蓄势待发']:
                    vertical_offset = 0.93
                elif signal_type in ['口袋支点']:
                    vertical_offset = 0.91
                signal_markers_dict[signal_type][marker_idx] = chart_df.iloc[marker_idx]['Low'] * vertical_offset
        except (KeyError, IndexError):
            pass

    for signal_type, markers in signal_markers_dict.items():
        marker_style = SIGNAL_MARKER_MAP.get(signal_type, SIGNAL_MARKER_MAP[SIG_UNKNOWN])
        addplots.append(
            mpf.make_addplot(
                markers,
                type='scatter',
                marker=marker_style['marker'],
                color=marker_style['color'],
                markersize=marker_style['size'],
                label=signal_type
            )
        )
    return addplots, used_signal_types


def pair_trades(log_csv_path, full_log_path=None, include_open=False):
    """
    将买入和卖出日志配对成完整的交易DataFrame。
    新增功能: 如果提供了完整日志路径，会尝试解析并添加额外标记的日期。
    新增功能: `include_open` 参数决定是否包含未平仓的交易。
    """
    try:
        log_df = pd.read_csv(log_csv_path, parse_dates=['datetime'])
    except FileNotFoundError:
        print(f"错误: 交易日志 {log_csv_path} 未找到。")
        return pd.DataFrame()

    full_log_lines = []
    if full_log_path and os.path.exists(full_log_path):
        try:
            with open(full_log_path, 'r', encoding='utf-8') as f:
                full_log_lines = f.readlines()
        except Exception as e:
            print(f"警告: 读取完整交易日志 {full_log_path} 出错: {e}")

    def _find_marker_date(buy_op, log_lines):
        if not log_lines:
            return None
        try:
            buy_date_str = buy_op['datetime'].strftime('%Y-%m-%d')
            buy_size_str = f"{int(buy_op['size'])}股"
            buy_log_line_idx = -1
            for i, line in enumerate(log_lines):
                if (buy_date_str in line and '买入成交' in line and
                        buy_size_str in line):
                    buy_log_line_idx = i
                    break

            if buy_log_line_idx != -1:
                # 从买入日志行向上查找源信号
                for i in range(buy_log_line_idx - 1, -1, -1):
                    line = log_lines[i]
                    if '(源信号:' in line:
                        date_str = line.split('@')[-1].strip().split(')')[0]
                        return pd.to_datetime(date_str)
        except Exception:
            return None
        return None

    buys = log_df[log_df['type'] == 'BUY'].copy()
    sells = log_df[log_df['type'] == 'SELL'].copy()

    trades = []
    used_sell_indices = set()
    used_buy_indices = set()

    for buy_idx, buy_op in buys.iterrows():
        symbol_str = _format_code(buy_op['symbol'])

        potential_sells = sells[
            (sells['symbol'].apply(_format_code) == symbol_str) &
            (sells['datetime'] > buy_op['datetime']) &
            (~sells.index.isin(used_sell_indices))
            ]

        if not potential_sells.empty:
            sell_op = potential_sells.iloc[0]
            extra_marker_date = _find_marker_date(buy_op, full_log_lines)

            trades.append({
                'symbol': symbol_str,
                'datetime_buy': buy_op['datetime'],
                'price_buy': buy_op['price'],
                'size_buy': buy_op['size'],
                'datetime_sell': sell_op['datetime'],
                'price_sell': sell_op['price'],
                'size_sell': sell_op['size'],
                'datetime_marker': extra_marker_date,
            })
            used_sell_indices.add(sell_op.name)
            used_buy_indices.add(buy_idx)

    if include_open:
        open_buys = buys[~buys.index.isin(used_buy_indices)]
        for _, buy_op in open_buys.iterrows():
            extra_marker_date = _find_marker_date(buy_op, full_log_lines)
            trades.append({
                'symbol': _format_code(buy_op['symbol']),
                'datetime_buy': buy_op['datetime'],
                'price_buy': buy_op['price'],
                'size_buy': buy_op['size'],
                'datetime_sell': pd.NaT,
                'price_sell': float('nan'),
                'size_sell': float('nan'),
                'datetime_marker': extra_marker_date,
            })

    return pd.DataFrame(trades)


def _plot_single_trade(trade, trade_id, data_dir, output_dir, style, post_exit_period, signal_info=None, stock_name=None):
    """为单笔交易生成并保存图表, 兼容未平仓交易。"""
    stock_code = _format_code(trade['symbol'])
    stock_data = read_stock_data(stock_code, data_dir)

    if stock_data is None:
        print(f"警告: 交易 {trade_id} 未能找到股票代码为 {stock_code} 的数据文件，已跳过。")
        return

    entry_date = trade['datetime_buy']
    is_open_trade = pd.isna(trade['datetime_sell'])

    # 确定图表结束日期
    if is_open_trade:
        exit_date = None
        # 对于未平仓交易, 图表结束日期是入场后的一段时间
        end_chart = entry_date + timedelta(days=post_exit_period)
    else:
        exit_date = trade['datetime_sell']
        # 对于已平仓交易, 图表结束日期是出场后的一段时间
        end_chart = exit_date + timedelta(days=post_exit_period)

    start_chart = entry_date - timedelta(days=60)
    chart_df = stock_data.loc[start_chart:end_chart].copy()

    if chart_df.empty:
        print(f"警告: 交易 {trade_id} 在 {stock_code} 中找不到指定的绘图日期范围，已跳过。")
        return

    # 清理停牌数据（包含NaN的行），确保 Open, High, Low, Close 数据完整
    chart_df = chart_df.dropna(subset=['Open', 'High', 'Low', 'Close'])
    
    if chart_df.empty:
        print(f"警告: 交易 {trade_id} 清理停牌数据后无有效数据，已跳过。")
        return

    # 准备买卖点标记
    buy_markers = [float('nan')] * len(chart_df)
    sell_markers = [float('nan')] * len(chart_df)
    addplots = []

    try:
        entry_idx = chart_df.index.searchsorted(entry_date, side='right') - 1
        if entry_idx >= 0:
            buy_markers[entry_idx] = chart_df.iloc[entry_idx]['Low'] * 0.98
        addplots.append(mpf.make_addplot(buy_markers, type='scatter', marker='^', color='lime', markersize=150))

        if not is_open_trade:
            exit_idx = chart_df.index.searchsorted(exit_date, side='right') - 1
            if exit_idx >= 0:
                sell_markers[exit_idx] = chart_df.iloc[exit_idx]['High'] * 1.02
            addplots.append(mpf.make_addplot(sell_markers, type='scatter', marker='v', color='magenta', markersize=150))

    except (KeyError, IndexError):
        pass

    # 用于图例的信号类型和标记
    signal_addplots, used_signal_types = _add_signal_markers_to_plot(chart_df, signal_info)
    addplots.extend(signal_addplots)

    # --- 生成图表标题 ---
    stock_display = f"{stock_code} {stock_name}" if stock_name else stock_code
    overheat_score, vcp_score = _extract_scores_from_details(signal_info)
    extra_info = ""
    if overheat_score is not None and vcp_score is not None:
        extra_info = f" (过热分: {overheat_score}, VCP Score: {vcp_score})"

    if is_open_trade:
        title = (
            f"股票: {stock_display} | 交易ID: {trade_id} | 持仓中\n"
            f"入场: {entry_date.strftime('%Y-%m-%d')} @ {trade['price_buy']:.2f}{extra_info}"
        )
    else:
        pnl = (trade['price_sell'] - trade['price_buy']) * abs(trade['size_sell'])
        pnl_percent = 0
        if trade['price_buy'] > 0:
            pnl_percent = ((trade['price_sell'] - trade['price_buy']) / trade['price_buy']) * 100

        title = (
            f"股票: {stock_display} | 交易ID: {trade_id} | {'盈利' if pnl > 0 else '亏损'}: {pnl:.2f} ({pnl_percent:+.2f}%)\n"
            f"入场: {entry_date.strftime('%Y-%m-%d')} @ {trade['price_buy']:.2f} | "
            f"出场: {exit_date.strftime('%Y-%m-%d')} @ {trade['price_sell']:.2f}{extra_info}"
        )

    output_path = os.path.join(output_dir, f"trade_{trade_id}_{stock_code}.png")

    # 创建图表，返回figure和axes用于后续处理
    fig, axes = mpf.plot(
        chart_df, type='candle', style=style,
        ylabel='价格', volume=True, ylabel_lower='成交量',
        addplot=addplots, figsize=(16, 8), returnfig=True,
        tight_layout=True
    )
    axes[0].set_title(title, loc='left', fontweight='bold')

    # 添加图例
    if used_signal_types:
        axes[0].legend(loc='upper left')

    # 自定义坐标轴，解决日期显示问题
    num_days = len(chart_df)
    interval = max(1, num_days // 20) if num_days > 20 else 1
    axes[0].xaxis.set_major_locator(mdates.DayLocator(interval=interval))
    fig.autofmt_xdate(rotation=30)

    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"已生成图表: {output_path}")


def plot_signal_chart(code, data_dir, output_dir, signal_info, stock_name=None):
    """
    为未发生交易但有信号的股票生成信号分析图。
    """
    stock_code = _format_code(code)
    stock_data = read_stock_data(stock_code, data_dir)
    style = _setup_mpf_style()

    if stock_data is None or stock_data.empty:
        print(f"警告: 无法为 {stock_code} 加载数据，跳过信号图生成。")
        return

    if not signal_info:
        print(f"警告: {stock_code} 没有提供信号信息，无法生成信号图。")
        return

    # 使用第一个信号确定图表范围
    primary_signal_date = pd.to_datetime(signal_info[0]['date'])
    start_chart = primary_signal_date - timedelta(days=90)
    end_chart = primary_signal_date + timedelta(days=30)
    chart_df = stock_data.loc[start_chart:end_chart].copy()

    if chart_df.empty:
        print(f"警告: 在 {stock_code} 中找不到指定的信号绘图日期范围，已跳过。")
        return

    # 清理停牌数据（包含NaN的行），确保 Open, High, Low, Close 数据完整
    chart_df = chart_df.dropna(subset=['Open', 'High', 'Low', 'Close'])
    
    if chart_df.empty:
        print(f"警告: {stock_code} 清理停牌数据后无有效数据，已跳过。")
        return

    # 获取信号标记
    addplots, used_signal_types = _add_signal_markers_to_plot(chart_df, signal_info)

    stock_display = f"{stock_code} {stock_name}" if stock_name else stock_code
    overheat_score, vcp_score = _extract_scores_from_details(signal_info)
    extra_info = ""
    if overheat_score is not None and vcp_score is not None:
        extra_info = f" (过热分: {overheat_score}, VCP Score: {vcp_score})"

    title = f"信号分析: {stock_display}\n主要信号日期: {primary_signal_date.strftime('%Y-%m-%d')}{extra_info}"

    signal_date_str = primary_signal_date.strftime('%Y%m%d')
    output_path = os.path.join(output_dir, f"signal_chart_{stock_code}_{signal_date_str}.png")

    fig, axes = mpf.plot(
        chart_df, type='candle', style=style,
        ylabel='价格', volume=True, ylabel_lower='成交量',
        addplot=addplots, figsize=(16, 8), returnfig=True,
        tight_layout=True
    )
    axes[0].set_title(title, loc='left', fontweight='bold')

    if used_signal_types:
        axes[0].legend(loc='upper left')

    # 自定义坐标轴，解决日期显示问题
    num_days = len(chart_df)
    interval = max(1, num_days // 20) if num_days > 20 else 1
    axes[0].xaxis.set_major_locator(mdates.DayLocator(interval=interval))
    fig.autofmt_xdate(rotation=30)

    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"已生成信号分析图: {output_path}")


# --- 主函数 ---

def analyze_and_visualize_trades(
        log_csv='trade_log.csv',
        full_log_path=None,
        data_dir='data/astocks',
        output_dir='strategy/post_analysis',
        post_exit_period=60,
        signal_info=None,
        include_open_trades=False,
        stock_name=None
):
    """
    读取交易日志，配对买卖操作，并对每笔完整交易进行可视化。
    
    Parameters:
    -----------
    log_csv : str
        交易日志CSV文件路径
    full_log_path : str, optional
        完整日志文件路径，用于解析额外信息
    data_dir : str
        股票数据目录
    output_dir : str
        输出目录
    post_exit_period : int
        出场后的观察天数
    signal_info : list of dict, optional
        信号详细信息列表，每个字典包含 date, type, details
    include_open_trades : bool
        是否包含未平仓的交易进行可视化
    stock_name : str, optional
        股票名称
    """
    trades_df = pair_trades(log_csv, full_log_path, include_open=include_open_trades)
    if trades_df.empty:
        print("未能配对任何完整的买卖交易。请检查日志文件。")
        return

    print(f"\n成功配对 {len(trades_df)} 笔完整交易。开始生成图表...")

    style = _setup_mpf_style()

    for i, trade in trades_df.iterrows():
        try:
            # --- 信号决策逻辑 ---
            # 优先使用外部传入的 signal_info (扫描器模式)
            # 如果没有，则使用从日志中解析出的 源信号 (独立回测模式)
            signals_to_plot = signal_info
            if not signals_to_plot and 'datetime_marker' in trade and pd.notna(trade['datetime_marker']):
                signals_to_plot = [{
                    'date': trade['datetime_marker'],
                    'type': SIG_SOURCE,
                    'details': '回测模式下的买入源信号'
                }]

            _plot_single_trade(
                trade=trade,
                trade_id=i + 1,
                data_dir=data_dir,
                output_dir=output_dir,
                style=style,
                post_exit_period=post_exit_period,
                signal_info=signals_to_plot,
                stock_name=stock_name
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
