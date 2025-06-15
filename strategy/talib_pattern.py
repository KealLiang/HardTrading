import backtrader as bt
import numpy as np
import talib


class TALibPatternStrategy(bt.Strategy):
    """
    使用TA-Lib库实现的K线形态识别策略
    这个策略使用TA-Lib内置函数识别多种K线形态，并基于形态信号进行交易
    """
    params = (
        ('order_percentage', 0.2),  # 每次交易使用账户资金的比例
        ('stop_loss_pct', 0.05),    # 止损百分比
    )

    def __init__(self):
        # 获取OHLC数据，用于TA-Lib函数
        self.dataopen = self.data.open
        self.datahigh = self.data.high
        self.datalow = self.data.low
        self.dataclose = self.data.close

        # 当前订单
        self.order = None
        self.buyprice = None
        self.stop_loss = None

        # 需要的最小历史数据点数
        self.min_history = 10

    def log(self, txt, dt=None):
        """日志打印函数"""
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()}, {txt}')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY 买入: 成交价 {order.executed.price:.2f}, 数量 {order.executed.size}')
                self.buyprice = order.executed.price
                self.stop_loss = self.buyprice * (1 - self.p.stop_loss_pct)
            elif order.issell():
                self.log(f'SELL 卖出: 成交价 {order.executed.price:.2f}, 数量 {order.executed.size}')
                self.stop_loss = None

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('订单失败')

        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        arrow = ('-' * 10) + '>'
        self.log(f'交易盈亏 {arrow} 毛收益 {trade.pnl:.2f}, 净收益 {trade.pnlcomm:.2f}')

    def next(self):
        # 如果有未完成的订单，不操作
        if self.order:
            return

        # 确保有足够的历史数据进行形态识别
        if len(self.data) < self.min_history:
            return

        # 获取最近的OHLC数据
        open_arr = np.array(self.dataopen.get(size=self.min_history))
        high_arr = np.array(self.datahigh.get(size=self.min_history))
        low_arr = np.array(self.datalow.get(size=self.min_history))
        close_arr = np.array(self.dataclose.get(size=self.min_history))

        # 计算K线形态信号
        try:
            # 存储形态及其信号值的字典
            pattern_results = {
                '锤子线': talib.CDLHAMMER(open_arr, high_arr, low_arr, close_arr)[-1],
                '吞没形态': talib.CDLENGULFING(open_arr, high_arr, low_arr, close_arr)[-1],
                '启明星': talib.CDLMORNINGSTAR(open_arr, high_arr, low_arr, close_arr)[-1],
                '三白兵': talib.CDL3WHITESOLDIERS(open_arr, high_arr, low_arr, close_arr)[-1],
                '上吊线': talib.CDLHANGINGMAN(open_arr, high_arr, low_arr, close_arr)[-1],
                '黄昏星': talib.CDLEVENINGSTAR(open_arr, high_arr, low_arr, close_arr)[-1],
                '三黑鸦': talib.CDL3BLACKCROWS(open_arr, high_arr, low_arr, close_arr)[-1]
            }
            
            # 提取看涨和看跌信号
            bullish_patterns = {k: v for k, v in pattern_results.items() if v > 0}
            bearish_patterns = {k: v for k, v in pattern_results.items() if v < 0}
            
            # 风险管理 - 止损
            if self.position and self.dataclose[0] < self.stop_loss:
                self.log(f'触发止损: 当前价格 {self.dataclose[0]:.2f}, 止损价 {self.stop_loss:.2f}')
                self.order = self.sell(size=self.position.size)
                return
            
            # 交易信号执行
            if bullish_patterns and not self.position:
                # 买入
                cash = self.broker.get_cash()
                size = int(cash * self.p.order_percentage / self.dataclose[0])
                if size > 0:
                    # 输出所有触发的看涨形态
                    signal_names = ', '.join(bullish_patterns.keys())
                    self.log(f'买入信号({signal_names}): 价格 {self.dataclose[0]:.2f}, 数量 {size}')
                    self.order = self.buy(size=size)
            
            elif bearish_patterns and self.position:
                # 卖出
                # 输出所有触发的看跌形态
                signal_names = ', '.join(bearish_patterns.keys())
                self.log(f'卖出信号({signal_names}): 价格 {self.dataclose[0]:.2f}')
                self.order = self.sell(size=self.position.size)
            
        except Exception as e:
            self.log(f'形态识别错误: {str(e)}')

    def stop(self):
        """回测结束后输出最终结果"""
        self.log(f'回测结束: 最终账户价值 {self.broker.getvalue():.2f}')