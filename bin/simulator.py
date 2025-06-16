import os

import backtrader as bt
import pandas as pd
from backtrader import feeds

from strategy.kdj_macd import KDJ_MACD_Strategy

# 定义要排除的前缀列表
exclude_prefixes = ['_XD', '_C']


# 定义列名
columns = ['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额', '振幅', '涨跌幅', '涨跌额',
           '换手率']


def read_and_convert_data(code, path, startdate=None, enddate=None):
    # 构造文件名和路径
    file_name_pattern = f'{code}_*.csv'  # 匹配以代码开头的文件
    files = [f for f in os.listdir(path) if f.startswith(code) and f.endswith('.csv')]

    if not files:
        raise FileNotFoundError(f"未找到匹配的文件 {file_name_pattern}")
    
    # 筛选掉不需要的文件
    filtered_files = [f for f in files if not any(prefix in f for prefix in exclude_prefixes)]

    # 如果筛选后没有文件，则使用原始文件列表
    if not filtered_files:
        filtered_files = files
        print(f"警告: 所有匹配文件都含有排除前缀，使用原始文件列表。")

    # 取第一个匹配的文件
    file_path = os.path.join(path, filtered_files[0])
    print(f"使用文件: {file_path}")

    df = pd.read_csv(file_path, header=None, names=columns)

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
        '成交量': 'volume'
    }, inplace=True)

    # 选择backtrader需要的列
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume']]

    # 按日期排序
    df.sort_values('datetime', inplace=True)

    # 时间过滤
    if startdate and enddate:
        df = df[(df['datetime'] >= startdate) & (df['datetime'] <= enddate)]

    # 转换为backtrader的PandasData格式
    return feeds.PandasData(
        dataname=df,
        datetime='datetime',  # 明确指定datetime列
        compression=1,  # 不压缩，即按天回测
        openinterest=-1  # 如果没有持仓量数据，设为-1
    )


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
    print('初始资金: %.2f' % cerebro.broker.getvalue())
    result = cerebro.run()
    print('回测结束后资金: %.2f' % cerebro.broker.getvalue())

    # 提取分析结果
    strat = result[0]
    print(f"最大回撤: {strat.analyzers.drawdown.get_analysis()['max']['drawdown']:.2f}%")
    print(f"年化收益率: {strat.analyzers.returns.get_analysis()['rnorm100']:.2f}%")
    try:
        print(f"夏普比率: {strat.analyzers.sharpe.get_analysis()['sharperatio']:.2f}")
    except (KeyError, TypeError):
        print("夏普比率: 数据不足，无法计算")

    # 绘制回测结果
    cerebro.plot()
