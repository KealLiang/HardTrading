import backtrader as bt

class SMAStrategy(bt.Strategy):
    params = (
        ('sma_period', 15),  # 均线周期，默认15
        ('order_percentage', 0.2),  # 每次交易使用账户资金的x%
    )

    def __init__(self):
        # 初始化指标
        self.sma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.params.sma_period)
        self.order = None  # 当前订单
        self.buyprice = None  # 买入价格
        self.buycomm = None  # 买入手续费

    def log(self, txt, dt=None):
        """日志打印函数，默认打印当前时间和信息"""
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()}, {txt}')

    def notify_order(self, order):
        """处理订单状态变化"""
        if order.status in [order.Submitted, order.Accepted]:
            # 订单已提交或已接受，暂不处理
            return

        # 订单已完成
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'买入: 成交价 {order.executed.price:.2f}, 成交量 {order.executed.size}, 手续费 {order.executed.comm:.2f}')
                self.buyprice = order.executed.price
                self.buycomm = order.executed.comm
            elif order.issell():
                self.log(f'卖出: 成交价 {order.executed.price:.2f}, 成交量 {order.executed.size}, 手续费 {order.executed.comm:.2f}')

        # 订单被取消、拒绝或出错
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('订单失败')

        # 清除订单
        self.order = None

    def notify_trade(self, trade):
        """处理交易状态变化"""
        if not trade.isclosed:
            return
        self.log(f'交易盈亏: 毛收益 {trade.pnl:.2f}, 净收益 {trade.pnlcomm:.2f}')

    def next(self):
        """策略核心逻辑"""
        # 检查是否有未完成的订单，避免重复下单
        if self.order:
            return

        # 获取当前账户资金和目标仓位
        cash = self.broker.get_cash()
        size = cash * self.params.order_percentage // self.data.close[0]

        # 买入逻辑：价格上穿均线
        if self.data.close[0] > self.sma[0] and not self.position:
            self.log(f'买入信号: 当前收盘价 {self.data.close[0]:.2f}, 均线值 {self.sma[0]:.2f}')
            self.order = self.buy(size=size)

        # 卖出逻辑：价格下穿均线
        elif self.data.close[0] < self.sma[0] and self.position:
            self.log(f'卖出信号: 当前收盘价 {self.data.close[0]:.2f}, 均线值 {self.sma[0]:.2f}')
            self.order = self.sell(size=self.position.size)

    def stop(self):
        """回测结束后输出最终账户价值"""
        self.log(f'回测结束: 最终账户价值 {self.broker.getvalue():.2f}')
