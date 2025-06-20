import backtrader as bt
import pandas as pd
from backtrader import feeds
from utils.file_util import read_stock_data

from strategy.kdj_macd import KDJ_MACD_Strategy

# 定义列名
columns = ['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额', '振幅', '涨跌幅', '涨跌额',
           '换手率']


# 创建一个扩展的PandasData类，添加涨跌幅、换手率和振幅
class ExtendedPandasData(feeds.PandasData):
    # 添加新的数据行
    lines = ('pct_chg', 'amplitude', 'turnover',)  # 涨跌幅、振幅、换手率
    
    # 添加参数，-1表示自动检测
    params = (
        ('pct_chg', -1),  # 涨跌幅
        ('amplitude', -1),  # 振幅
        ('turnover', -1),  # 换手率
    )


def read_and_convert_data(code, path, startdate=None, enddate=None):
    df = read_stock_data(code, path)

    if df is None:
        raise FileNotFoundError(f"未找到匹配的文件 {code}_*.csv")

    print(f"使用股票代码: {code}")

    # 转换日期格式为datetime
    df['日期'] = pd.to_datetime(df['日期'], errors='coerce')  # 强制转换，无效日期会变成NaT

    if df['日期'].isna().any():
        raise ValueError("日期列包含无效值，请检查数据格式")

    # 重命名列以匹配backtrader的格式
    df.rename(columns={
        '日期': 'datetime',
        '开盘': 'open',
        '收盘': 'close',
        '最高': 'high',
        '最低': 'low',
        '成交量': 'volume',
        '涨跌幅': 'pct_chg',  # 新增涨跌幅
        '振幅': 'amplitude',  # 新增振幅
        '换手率': 'turnover'  # 新增换手率
    }, inplace=True)

    # 选择backtrader需要的列以及新增的3列
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'pct_chg', 'amplitude', 'turnover']]

    # 按日期排序
    df.sort_values('datetime', inplace=True)

    # 时间过滤
    if startdate and enddate:
        df = df[(df['datetime'] >= startdate) & (df['datetime'] <= enddate)]

    # 转换为自定义的ExtendedPandasData格式
    return ExtendedPandasData(
        dataname=df,
        datetime='datetime',  # 明确指定datetime列
        open='open',
        high='high',
        low='low',
        close='close',
        volume='volume',
        pct_chg='pct_chg',  # 涨跌幅
        amplitude='amplitude',  # 振幅
        turnover='turnover',  # 换手率
        compression=1,  # 不压缩，即按天回测
        openinterest=-1  # 如果没有持仓量数据，设为-1
    )


def calculate_benchmark(data, initial_amount, final_amount):
    """计算基准表现和超额收益，使用与backtrader Returns分析器一致的逻辑"""
    # 获取起始和结束价格
    start_price = data.close[-len(data)+1]  # 第一个交易日的收盘价 
    end_price = data.close[0]  # 最后一个交易日的收盘价
    
    # 计算基准假设持仓数量和最终资金
    shares = initial_amount / start_price
    benchmark_final_value = shares * end_price
    
    # 计算基准收益率
    benchmark_return = (end_price / start_price - 1) * 100
    
    # 计算基准年化收益率
    # 获取交易天数
    trading_days = len(data)
    # 使用252个交易日作为一年，与backtrader的Returns分析器一致
    years = trading_days / 252
    benchmark_annual_return = ((end_price / start_price) ** (1/years) - 1) * 100 if years > 0 else 0
    
    # 计算策略相对于基准的超额收益
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
             strategy=KDJ_MACD_Strategy, strategy_params=None):
    data = read_and_convert_data(code, filepath, startdate, enddate)

    # 创建Cerebro引擎
    cerebro = bt.Cerebro()

    # 添加策略，支持自定义参数
    if strategy_params:
        cerebro.addstrategy(strategy, **strategy_params)
    else:
        cerebro.addstrategy(strategy)

    # 添加数据
    cerebro.adddata(data)

    # 初始资金
    cerebro.broker.set_cash(amount)
    cerebro.broker.setcommission(commission=0.00015)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.02)  # 夏普比率
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')  # 最大回撤
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')  # 年化收益率
    cerebro.addanalyzer(bt.analyzers.PyFolio, _name='pyfolio')  # 兼容PyFolio（可选）

    # 运行回测
    start_value = cerebro.broker.getvalue()
    result = cerebro.run()
    final_value = cerebro.broker.getvalue()
    print('初始资金: %.2f' % start_value)
    print('回测结束后资金: %.2f' % final_value)

    # 提取分析结果
    strat = result[0]
    print(f"最大回撤: {strat.analyzers.drawdown.get_analysis()['max']['drawdown']:.2f}%")
    print(f"年化收益率: {strat.analyzers.returns.get_analysis()['rnorm100']:.2f}%")
    try:
        print(f"夏普比率: {strat.analyzers.sharpe.get_analysis()['sharperatio']:.2f}")
    except (KeyError, TypeError):
        print("夏普比率: 数据不足，无法计算")
    
    # 计算基准表现
    benchmark_results = calculate_benchmark(data, amount, final_value)
    
    # 打印基准比较结果
    print(f"===== 基准测试（周期内买入后不做操作） =====")
    print(f"基准结束资金: {benchmark_results['benchmark_final_value']:.2f}")
    print(f"基准收益率: {benchmark_results['benchmark_return']:.2f}%")
    print(f"基准年化收益率: {benchmark_results['benchmark_annual_return']:.2f}%")
    print(f"策略总收益率: {benchmark_results['strategy_return']:.2f}%")
    print(f"超额收益: {benchmark_results['excess_return']:.2f}%")

    # 绘制回测结果
    cerebro.plot()
