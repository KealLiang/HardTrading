import backtrader as bt


class PanicReboundStrategy(bt.Strategy):
    """
    一个专门用于捕捉市场极端超卖后V型反弹机会的策略。

    - 核心逻辑:
      当RSI进入极端超卖区域(默认25)，并且价格触及或跌破布林带下轨时，执行买入。
    - 风控:
      - 使用买入当日的最低价作为硬止损。
      - 当价格反弹至布林带中轨时止盈。
      - 设有最大持仓天数作为时间止损。
    """
    params = (
        # -- 指标参数 --
        ('bband_period', 20),
        ('bband_devfactor', 2.0),
        ('rsi_period', 14),
        ('rsi_oversold', 30),  # RSI超卖阈值 (设为更频繁触发的值以供调试)

        # -- 交易参数 --
        ('initial_stake_pct', 0.90),  # 初始仓位
        ('panic_rebound_hold_days', 10),  # 最大持有天数
    )

    def __init__(self):
        # -- 指标 --
        self.bband = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bband_period, devfactor=self.p.bband_devfactor
        )
        self.rsi = bt.indicators.RSI(self.data, period=self.p.rsi_period)

        # -- 状态跟踪 --
        self.order = None
        self.buy_tick = 0  # 记录买入时的bar
        self.stop_price = 0.0  # 硬止损价格

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()} - {txt}')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                position_pct = order.executed.value / self.broker.getvalue() * 100
                self.log(
                    f'买入成交 (恐慌反弹): {order.executed.size}股 @ {order.executed.price:.2f}, '
                    f'仓位: {position_pct:.2f}%'
                )
                # 买入后，立即设置状态
                self.buy_tick = len(self)
                self.stop_price = self.data.low[0]
                self.log(f'*** 进入【恐慌反弹】模式, 硬止损位于 {self.stop_price:.2f} ***')

            elif order.issell():
                self.log(
                    f'卖出成交: {abs(order.executed.size)}股 @ {order.executed.price:.2f}'
                )
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('订单未能成交')

        self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f'交易关闭, 净盈亏: {trade.pnlcomm:.2f}, 当前总资产: {self.broker.getvalue():.2f}')
            # 重置所有交易相关的状态
            self.buy_tick = 0
            self.stop_price = 0.0

    def next(self):
        if self.order:
            return

        if self.position:
            self._handle_trade()
        else:
            self._check_buy_signal()

    def _handle_trade(self):
        """处理持仓的风控逻辑"""
        # A. 硬止损：如果价格创下买入日以来的新低
        if self.data.low[0] < self.stop_price:
            self.log(f'卖出信号: 创下新低, 触发硬止损 @ {self.stop_price:.2f}')
            self.order = self.close()
            return

        # B. 时间止损：如果持有时间过长
        hold_days = len(self) - self.buy_tick
        if hold_days >= self.p.panic_rebound_hold_days:
            self.log(f'卖出信号: 持有 {hold_days} 天, 时间止损')
            self.order = self.close()
            return

        # C. 止盈逻辑：反弹到布林带中轨
        if self.data.close[0] > self.bband.lines.mid[0]:
            self.log(f'卖出信号: 价格反弹至中轨, 止盈')
            self.order = self.close()
            return

    def _check_buy_signal(self):
        """检查买入信号"""
        is_panic = self.rsi[0] < self.p.rsi_oversold and self.data.low[0] <= self.bband.lines.bot[0]

        if is_panic:
            self.log('机会信号:【恐慌反弹】(RSI超卖 & 触及下轨)')
            stake = self.broker.getvalue() * self.p.initial_stake_pct
            size = int(stake / self.data.close[0])
            if size > 0:
                self.order = self.buy(size=size)
