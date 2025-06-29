import logging
import os
import types
from datetime import datetime

import backtrader as bt
import pandas as pd
from tqdm import tqdm

import bin.simulator as simulator
from bin.simulator import read_stock_data, ExtendedPandasData
from strategy.breakout_strategy import BreakoutStrategy
from utils.date_util import get_current_or_prev_trading_day

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s - %(message)s')


def get_stock_pool(source=None, data_dir='./data/astocks'):
    """
    获取股票池列表。
    :param source: 股票来源。可以是列表, 'all', 或文件路径 (默认: 'bin/candidate_stocks.txt')。
    :param data_dir: 股票数据目录, 当 source='all' 时使用。
    :return: 股票代码列表。
    """
    if isinstance(source, list):
        return [str(s).zfill(6) for s in source]

    if source is None:
        source = 'bin/candidate_stocks.txt'

    if os.path.exists(source):
        try:
            with open(source, 'r', encoding='utf-8') as f:
                stocks = [line.strip() for line in f if line.strip() and not line.startswith("股票代码")]
            return [s.zfill(6) for s in stocks]
        except Exception as e:
            logging.error(f"读取股票池文件 {source} 失败: {e}")
            return []

    if source == 'all':
        try:
            return [f.split('_')[0] for f in os.listdir(data_dir) if f.endswith('.csv')]
        except FileNotFoundError:
            logging.error(f"数据目录 {data_dir} 不存在。")
            return []

    logging.warning(f"无法识别的股票池来源: {source}")
    return []


def _scan_single_stock(code, strategy_class, strategy_params, data_path,
                       scan_start_date, scan_end_date):
    """
    对单个股票进行扫描，捕获在指定日期范围内的买入信号。 (内部函数)
    """
    try:
        dataframe = read_stock_data(code, data_path)
        if dataframe is None or dataframe.empty:
            return None

        # 确保有足够的数据用于指标预热
        required_start = pd.to_datetime(scan_start_date) - pd.Timedelta(days=100)
        if dataframe.index[0] > required_start:
            return None

        data_feed = ExtendedPandasData(dataname=dataframe)

        cerebro = bt.Cerebro(stdstats=False)
        cerebro.adddata(data_feed, name=code)

        # --- 使用回调函数机制 ---
        all_signals_from_strategy = []
        def signal_handler(signal):
            all_signals_from_strategy.append(signal)

        # 在策略参数中加入回调
        if strategy_params is None:
            strategy_params = {}
        strategy_params['signal_callback'] = signal_handler
        
        cerebro.addstrategy(strategy_class, **strategy_params)

        cerebro.run()

        # --- 从所有信号中筛选出最终的买入信号 ---
        final_buy_signals = []
        scan_start_date_obj = pd.to_datetime(scan_start_date).date()
        scan_end_date_obj = pd.to_datetime(scan_end_date).date()

        for signal in all_signals_from_strategy:
            signal_date = signal['datetime']
            if signal['signal_type'] == 'BUY_SIGNAL' and \
               scan_start_date_obj <= signal_date <= scan_end_date_obj:
                final_buy_signals.append({
                    'code': signal['code'],
                    'signal_date': signal_date,
                    'price': signal['close'],
                    'details': signal.get('details', 'N/A')
                })

        return final_buy_signals

    except Exception:
        return None


def _run_scan(strategy_class, start_date, end_date,
              stock_pool_source=None, data_path='./data/astocks',
              strategy_params=None):
    """
    运行股票扫描器。(内部函数)
    """
    stock_list = get_stock_pool(stock_pool_source, data_path)
    if not stock_list:
        logging.error("股票池为空，扫描终止。")
        return []

    logging.info(f"开始扫描 {len(stock_list)} 只股票，策略: {strategy_class.__name__}, "
                 f"日期范围: [{start_date}, {end_date}]")

    all_signals = []
    
    # 为扫描过程创建一个静默版的策略参数
    scan_params = (strategy_params or {}).copy()
    scan_params['silent'] = True

    with tqdm(total=len(stock_list), desc="扫描进度") as pbar:
        for code in stock_list:
            signals = _scan_single_stock(code, strategy_class, scan_params, data_path,
                                         start_date, end_date)
            if signals:
                all_signals.extend(signals)
            pbar.update(1)

    logging.info(f"扫描完成。共在 {len(set(s['code'] for s in all_signals))} 只股票中找到 {len(all_signals)} 个买入信号。")
    return all_signals


def scan_and_visualize(scan_strategy, scan_start_date, scan_end_date=None,
                       stock_pool=None, strategy_params=None):
    """
    执行股票扫描，并将结果输出到文件和图表。
    :param scan_strategy: 用于扫描的策略类。
    :param scan_start_date: 扫描开始日期 (格式: 'YYYYMMDD')。
    :param scan_end_date: 扫描结束日期 (格式: 'YYYYMMDD')，若为None则为最近交易日。
    :param stock_pool: 股票池来源 (None, 'all', list, or file path)。
    :param strategy_params: 策略参数字典。
    """
    # --- 1. 日期处理 ---
    start_date_fmt = f"{scan_start_date[:4]}-{scan_start_date[4:6]}-{scan_start_date[6:8]}"
    if scan_end_date is None:
        today_str = datetime.now().strftime('%Y%m%d')
        end_date_str = get_current_or_prev_trading_day(today_str)
        end_date_fmt = f"{end_date_str[:4]}-{end_date_str[4:6]}-{end_date_str[6:8]}"
    else:
        end_date_str = scan_end_date
        end_date_fmt = f"{scan_end_date[:4]}-{scan_end_date[4:6]}-{scan_end_date[6:8]}"

    # --- 2. 执行扫描 ---
    signals = _run_scan(
        strategy_class=scan_strategy,
        start_date=start_date_fmt,
        end_date=end_date_fmt,
        stock_pool_source=stock_pool,
        strategy_params=strategy_params
    )

    if not signals:
        print("扫描完成，没有发现符合条件的信号。")
        return

    # --- 3. 创建输出目录和日志文件 ---
    output_dir = os.path.join('bin', 'candidate_stocks_result')
    os.makedirs(output_dir, exist_ok=True)
    summary_path = os.path.join(output_dir, f"scan_summary_{scan_start_date}-{end_date_str}.txt")

    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(f"扫描策略: {scan_strategy.__name__}\n")
        f.write(f"扫描范围: {start_date_fmt} to {end_date_fmt}\n")
        f.write(f"总计发现 {len(signals)} 个信号，涉及 {len(set(s['code'] for s in signals))} 只股票。\n")
        f.write("-" * 50 + "\n")
        for signal in signals:
            f.write(f"股票: {signal['code']}, "
                    f"信号日期: {signal['signal_date'].strftime('%Y-%m-%d')}, "
                    f"价格: {signal['price']:.2f}, "
                    f"详情: {signal.get('details', '')}\n")

    print(f"\n扫描结果摘要已保存到: {summary_path}")
    print(f"开始对 {len(signals)} 个信号逐一进行可视化分析...")

    # --- 4. 对每个信号进行可视化 ---
    for signal in signals:
        code = signal['code']
        signal_date = signal['signal_date']
        
        vis_start_date = signal_date - pd.Timedelta(days=90)
        vis_end_date = signal_date + pd.Timedelta(days=90)

        print("-" * 70)
        print(f"正在分析股票: {code}, 信号日期: {signal_date.strftime('%Y-%m-%d')}")

        simulator.go_trade(
            code=code,
            startdate=vis_start_date,
            enddate=vis_end_date,
            strategy=scan_strategy,
            strategy_params=strategy_params,
            log_trades=True,
            visualize=True,
            signal_dates=[signal_date],
            interactive_plot=False  # 禁用弹出图表
        )

if __name__ == '__main__':
    # 使用示例
    scan_and_visualize(
        scan_strategy=BreakoutStrategy,
        scan_start_date='20240101',
        scan_end_date='20250620',
        stock_pool=None  # None, 'all', or list
    ) 