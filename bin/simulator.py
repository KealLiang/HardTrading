import os
from contextlib import redirect_stdout
from datetime import datetime, timedelta

import backtrader as bt
import pandas as pd
from backtrader import feeds

from strategy.breakout_strategy import BreakoutStrategy
from strategy.kdj_macd import KDJ_MACD_Strategy
from utils.backtrade.analyzers import OrderLogger
from utils.backtrade.visualizer import analyze_and_visualize_trades, plot_signal_chart

# 至少需要一个最长的指标周期作为预热期
warm_up_days = 100


# 这是来自 origin_simulator.py 的原始、可工作的 read_stock_data 函数
def read_stock_data(code, path):
    """
    根据股票代码智能查找并读取CSV文件。
    文件名格式应为 "代码_名称.csv", 例如 "603986_兆易创新.csv"。
    """
    try:
        for filename in os.listdir(path):
            if filename.startswith(str(code)) and filename.endswith('.csv'):
                file_path = os.path.join(path, filename)
                # 无表头，需手动指定列名
                column_names = [
                    'date', 'code', 'open', 'close', 'high', 'low', 'volume',
                    'amount', 'amplitude', 'pct_chg', 'turnover', 'pe_ratio'
                ]
                df = pd.read_csv(
                    file_path,
                    header=None,
                    names=column_names,
                    index_col='date',
                    parse_dates=True
                )
                # 确保索引是tz-naive，以避免比较问题
                df.index = df.index.tz_localize(None)
                return df
    except FileNotFoundError:
        print(f"数据目录 '{path}' 未找到。")
    except Exception as e:
        print(f"读取股票 {code} 数据时出错: {e}")
    return None


# 创建一个扩展的PandasData类，添加涨跌幅、换手率和振幅
class ExtendedPandasData(feeds.PandasData):
    lines = ('pct_chg', 'amplitude', 'turnover',)
    params = (
        ('pct_chg', -1), ('amplitude', -1), ('turnover', -1),
    )


def calculate_benchmark(data, initial_amount, final_amount):
    start_price = data.close[-len(data) + 1]
    end_price = data.close[0]
    shares = initial_amount / start_price
    benchmark_final_value = shares * end_price
    benchmark_return = (end_price / start_price - 1) * 100
    trading_days = len(data)
    years = trading_days / 252
    benchmark_annual_return = ((end_price / start_price) ** (1 / years) - 1) * 100 if years > 0 else 0
    strategy_return = (final_amount / initial_amount - 1) * 100
    excess_return = strategy_return - benchmark_return
    return {
        'benchmark_final_value': benchmark_final_value,
        'benchmark_return': benchmark_return,
        'benchmark_annual_return': benchmark_annual_return,
        'strategy_return': strategy_return,
        'excess_return': excess_return
    }


def go_trade(code, amount=100000, startdate=None, enddate=None, filepath='./data/astocks',
             strategy=KDJ_MACD_Strategy, strategy_params=None,
             log_trades=False, visualize=False, signal_info=None, interactive_plot=True):
    """执行股票回测和可视化。

    参数:
    code - 股票代码
    amount - 初始资金
    startdate, enddate - 回测起止日期
    filepath - 股票数据目录
    strategy - 回测策略类
    strategy_params - 策略参数
    log_trades - 是否记录交易日志
    visualize - 是否生成交易可视化
    signal_info - 信号信息列表，每个元素包含date, type, details
    interactive_plot - 是否显示交互式图表
    """
    print(f"使用股票代码: {code}, 预热期: {warm_up_days}")

    dataframe = read_stock_data(code, filepath)
    if dataframe is None:
        print("数据加载失败，程序退出。")
        return

    # 计算实际需要的数据起点
    data_start_date = startdate - timedelta(days=warm_up_days) if startdate else None

    # 日期过滤
    if data_start_date:
        dataframe = dataframe.loc[data_start_date:]
    if enddate:
        dataframe = dataframe.loc[:enddate]

    if dataframe.empty:
        print("指定日期范围内无数据，程序退出。")
        return

    cerebro = bt.Cerebro()

    if strategy_params:
        cerebro.addstrategy(strategy, **strategy_params)
    else:
        cerebro.addstrategy(strategy)

    data = ExtendedPandasData(dataname=dataframe)
    cerebro.adddata(data, name=code)

    output_dir = None
    if log_trades or visualize:
        start_date_str = dataframe.index[0].strftime('%Y%m%d')
        end_date_str = dataframe.index[-1].strftime('%Y%m%d')

        # 兼容处理：如果有人通过旧的方式调用，自动处理
        if isinstance(signal_info, list) and signal_info and not isinstance(signal_info[0], dict):
            # 可能是旧的signal_dates格式，转换为signal_info格式
            signal_info = [{'date': date, 'type': 'Unknown', 'details': ''} for date in signal_info]

        if signal_info:
            # 使用第一个信号的日期来命名文件夹
            signal_date_str = pd.to_datetime(signal_info[0]['date']).strftime('%Y%m%d')
            folder_name = f"{code}_{signal_date_str}_{strategy.__name__}"
            base_path = os.path.join('bin', 'candidate_stocks_result')
            output_dir = os.path.join(base_path, folder_name)
        else:
            # 普通回测的输出
            folder_name = f"{code}_{start_date_str}-{end_date_str}"
            base_path = os.path.join('strategy', 'post_analysis')
            output_dir = os.path.join(base_path, folder_name)

        os.makedirs(output_dir, exist_ok=True)
        # 完整运行日志的路径
        full_log_path = os.path.join(output_dir, 'run_log.txt')

    if log_trades:
        log_csv_path = os.path.join(output_dir, 'trade_log.csv')
        cerebro.addanalyzer(OrderLogger, log_path=log_csv_path, _name='orderlogger')

    cerebro.broker.set_cash(amount)
    cerebro.broker.setcommission(commission=0.00015)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.PyFolio, _name='pyfolio')

    start_value = cerebro.broker.getvalue()

    # --- 运行Cerebro并捕获日志 ---
    print("开始执行策略回测...")
    if log_trades or visualize:
        print(f"策略执行日志将保存到: {full_log_path}")
        with open(full_log_path, 'w', encoding='utf-8') as f:
            with redirect_stdout(f):
                result = cerebro.run()
    else:
        result = cerebro.run()

    final_value = cerebro.broker.getvalue()
    print('初始资金: %.2f' % start_value)
    print('回测结束后资金: %.2f' % final_value)

    strat = result[0]
    print(f"最大回撤: {strat.analyzers.drawdown.get_analysis()['max']['drawdown']:.2f}%")
    print(f"年化收益率: {strat.analyzers.returns.get_analysis()['rnorm100']:.2f}%")
    try:
        print(f"夏普比率: {strat.analyzers.sharpe.get_analysis()['sharperatio']:.2f}")
    except (KeyError, TypeError, AttributeError):
        print("夏普比率: 数据不足，无法计算")

    benchmark_results = calculate_benchmark(data, amount, final_value)
    print("===== 基准测试（周期内买入后不做操作） =====")
    print(f"基准结束资金: {benchmark_results['benchmark_final_value']:.2f}")
    print(f"基准收益率: {benchmark_results['benchmark_return']:.2f}%")
    print(f"基准年化收益率: {benchmark_results['benchmark_annual_return']:.2f}%")
    print(f"策略总收益率: {benchmark_results['strategy_return']:.2f}%")
    print(f"超额收益: {benchmark_results['excess_return']:.2f}%")

    if visualize and log_trades and output_dir:
        print("=" * 50)
        print("回测完成，开始执行交易可视化分析...")
        print("=" * 50)

        # 检查交易日志中是否有实际成交
        trade_log_has_trades = False
        try:
            # 更可靠地检查: 读取log文件并查看是否为空
            if os.path.exists(log_csv_path):
                log_df = pd.read_csv(log_csv_path)
                if not log_df.empty:
                    trade_log_has_trades = True
        except (OSError, FileNotFoundError, pd.errors.EmptyDataError):
            pass  # 文件不存在、无法访问或为空(只有头)，则认为无成交

        if trade_log_has_trades:
            # 扫描模式下（有signal_info），需要可视化未平仓的交易
            visualize_open_trades = True if signal_info else False
            analyze_and_visualize_trades(
                log_csv=log_csv_path,
                full_log_path=full_log_path,
                data_dir=filepath,
                output_dir=output_dir,
                signal_info=signal_info,
                include_open_trades=visualize_open_trades
            )
        elif signal_info:  # 无成交，但有信号（扫描模式）
            print("未执行任何交易，但检测到信号。生成信号分析图...")
            plot_signal_chart(
                code=code,
                data_dir=filepath,
                output_dir=output_dir,
                signal_info=signal_info
            )

    if interactive_plot:
        cerebro.plot()


if __name__ == '__main__':
    stock_code = '301357'
    initial_cash = 100000
    data_path = './data/astocks'
    go_trade(
        code=stock_code,
        amount=initial_cash,
        startdate=datetime(2022, 1, 1),
        enddate=datetime(2025, 7, 4),
        filepath=data_path,
        strategy=BreakoutStrategy,
        log_trades=True,
        visualize=True,
        interactive_plot=False, # 先不弹出交互图，方便查看日志
        signal_info=[]
    )
