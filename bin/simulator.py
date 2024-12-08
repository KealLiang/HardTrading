import backtrader as bt

from strategy.kdj_macd import KDJ_MACD_Strategy
from strategy.sma import SMAStrategy


def load_data(filename):
    # 加载CSV数据
    return bt.feeds.GenericCSVData(
        dataname=filename,
        dtformat='%Y-%m-%d',
        timeframe=bt.TimeFrame.Days,
        compression=1,
        openinterest=-1  # 如果没有持仓量数据，设为-1
    )


def go_trade(name, amount=100000):
    data = load_data(f'data/{name}_bt.csv')

    # 创建Cerebro引擎
    cerebro = bt.Cerebro()

    # 添加策略
    cerebro.addstrategy(KDJ_MACD_Strategy)

    # 添加数据
    cerebro.adddata(data)

    # 初始资金
    cerebro.broker.set_cash(amount)
    cerebro.broker.setcommission(commission=0.0002354)

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
    print(f"夏普比率: {strat.analyzers.sharpe.get_analysis()['sharperatio']:.2f}")
    print(f"年化收益率: {strat.analyzers.returns.get_analysis()['rnorm100']:.2f}%")

    # 绘制回测结果
    cerebro.plot()
