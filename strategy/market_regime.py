import backtrader as bt

class MarketRegimeStrategy(bt.Strategy):
    """
    动态市场状态策略 - 修复版
    - 首先判断市场处于上升、震荡、下跌中的哪一种状态
    - 然后根据不同的状态执行相应的买卖逻辑
    """
    params = (
        # -- 市场状态定义 --
        ('ma_short_period', 20),
        ('ma_long_period', 50),
        ('ma_slope_period', 5),

        # -- 资金与持仓管理 --
        ('order_percentage', 0.20),
        ('max_hold_period', 10),
        ('initial_stop_loss_pct', 0.07),

        # -- 上升行情参数 --
        ('uptrend_rsi_buy', 50),
        ('uptrend_sell_pct_chg', 0.05),  # 降低了卖出阈值

        # -- 震荡行情参数 --
        ('ranging_buy_pct_chg', -0.03),
        ('ranging_rsi_buy', 30),
        ('ranging_profit_target', 0.08),

        # -- 下跌行情参数 --
        ('downtrend_bias_buy', -0.15),
        ('downtrend_profit_target', 0.05),
        ('downtrend_max_hold', 3),
    )

    def __init__(self):
        # --- 指标定义 ---
        self.ma_short = bt.indicators.SMA(self.datas[0].close, period=self.p.ma_short_period)
        self.ma_long = bt.indicators.SMA(self.datas[0].close, period=self.p.ma_long_period)
        self.rsi = bt.indicators.RSI(self.datas[0].close, period=14)
        self.bbands = bt.indicators.BollingerBands(self.datas[0].close)

        # --- 状态跟踪 ---
        self.order = None
        self.buy_price = None
        self.buy_tick = 0
        self.initial_cash = self.broker.get_cash()  # 记录初始资金
        
        # 检查初始状态
        if self.position:
            # 如果有初始持仓，先平掉它
            self.log(f"检测到初始持仓: {self.position.size} 股，将在策略开始时平仓")
            # 我们不能马上卖出，因为在init时还不能下单，需要在next中处理
            self.clear_initial_position = True
        else:
            self.clear_initial_position = False

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()} - {txt}')

    def get_position_value(self):
        """计算当前持仓市值"""
        return self.position.size * self.datas[0].close[0] if self.position and self.position.size > 0 else 0
    
    def get_total_value(self):
        """计算当前总资产"""
        return self.broker.get_cash() + self.get_position_value()

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            cash = self.broker.get_cash()
            position_value = self.get_position_value()
            total_value = cash + position_value
            
            if order.isbuy():
                self.buy_price = order.executed.price
                self.buy_tick = len(self)  # 记录当前bar的索引
                self.log(f'买入成交: 价格={order.executed.price:.2f}, 数量={order.executed.size:.0f}, '
                         f'现金={cash:.2f}, 持仓={position_value:.2f}, 总资产={total_value:.2f}')
            elif order.issell():
                profit = None
                if hasattr(self, 'buy_price') and self.buy_price:
                    profit = (order.executed.price - self.buy_price) * order.executed.size * -1
                    profit_pct = (order.executed.price / self.buy_price - 1) * 100 if self.buy_price else 0
                    self.log(f'卖出成交: 价格={order.executed.price:.2f}, 数量={-order.executed.size:.0f}, '
                             f'盈亏={profit:.2f} ({profit_pct:.2f}%), '
                             f'现金={cash:.2f}, 持仓={position_value:.2f}, 总资产={total_value:.2f}')
                else:
                    self.log(f'卖出成交: 价格={order.executed.price:.2f}, 数量={-order.executed.size:.0f}, '
                             f'现金={cash:.2f}, 持仓={position_value:.2f}, 总资产={total_value:.2f}')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('订单取消/保证金不足/被拒绝')

        self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f'交易结算: 毛盈亏={trade.pnl:.2f}, 净盈亏={trade.pnlcomm:.2f}')
            self.buy_price = None
            self.buy_tick = 0

    def next(self):
        # 跳过order在执行中的情况
        if self.order:
            return
            
        # 先处理初始持仓（如果有）
        if hasattr(self, 'clear_initial_position') and self.clear_initial_position:
            self.log("清除初始持仓")
            self.order = self.close()  # 平掉所有持仓
            self.clear_initial_position = False
            return

        # 获取当前的索引
        current_bar = len(self)
        
        # --- 1. 确定当前市场状态 ---
        ma_long_slope = self.ma_long[0] - self.ma_long[-self.p.ma_slope_period]
        is_uptrend = self.ma_short[0] > self.ma_long[0] and ma_long_slope > 0
        is_downtrend = self.ma_short[0] < self.ma_long[0] and ma_long_slope < 0
        is_ranging = not is_uptrend and not is_downtrend
        
        market_state = "上升" if is_uptrend else "下跌" if is_downtrend else "震荡"

        # --- 2. 卖出逻辑 (优先处理) ---
        if self.position and self.position.size > 0:
            # 检查买入时间点是否合理
            if self.buy_tick <= 0:
                self.buy_tick = current_bar - 1  # 如果发现错误，假设是昨天买入的
                
            hold_days = current_bar - self.buy_tick
            
            # 全局卖出条件
            if hold_days >= self.p.max_hold_period:
                self.log(f'卖出信号: {market_state}行情 - 持仓超过 {self.p.max_hold_period} 天')
                self.order = self.sell(size=self.position.size)  # 卖出全部持仓
                return

            if self.buy_price and self.datas[0].close[0] < self.buy_price * (1 - self.p.initial_stop_loss_pct):
                self.log(f'卖出信号: {market_state}行情 - 触发初始止损位 {self.p.initial_stop_loss_pct*100:.0f}%')
                self.order = self.sell(size=self.position.size)
                return

            # 分状态卖出逻辑
            if is_uptrend:
                if self.datas[0].pct_chg[0] > self.p.uptrend_sell_pct_chg:
                    self.log(f'卖出信号: 上升行情 - 大阳线止盈, 涨跌幅: {self.datas[0].pct_chg[0]:.2f}%')
                    self.order = self.sell(size=self.position.size)
                    return
            
            elif is_ranging:
                if self.buy_price and (self.datas[0].close[0] - self.buy_price) / self.buy_price > self.p.ranging_profit_target:
                    self.log(f'卖出信号: 震荡行情 - 达到利润目标 {self.p.ranging_profit_target*100:.0f}%')
                    self.order = self.sell(size=self.position.size)
                    return
                if self.datas[0].close[0] > self.bbands.top[0]:
                    self.log('卖出信号: 震荡行情 - 触及布林带上轨')
                    self.order = self.sell(size=self.position.size)
                    return
            
            elif is_downtrend:
                if self.buy_price and (self.datas[0].close[0] - self.buy_price) / self.buy_price > self.p.downtrend_profit_target:
                    self.log(f'卖出信号: 下跌行情 - 快速获利 {self.p.downtrend_profit_target*100:.0f}%')
                    self.order = self.sell(size=self.position.size)
                    return
                if self.datas[0].close[0] > self.ma_short[0]:
                     self.log('卖出信号: 下跌行情 - 触及均线阻力')
                     self.order = self.sell(size=self.position.size)
                     return
                if hold_days >= self.p.downtrend_max_hold:
                    self.log(f'卖出信号: 下跌行情 - 持仓到期 {self.p.downtrend_max_hold} 天')
                    self.order = self.sell(size=self.position.size)
                    return
            
            return

        # --- 3. 买入逻辑 ---
        if not self.position or self.position.size <= 0:
            # 计算买入数量，并确保是整数
            available_cash = self.broker.get_cash() * self.p.order_percentage
            if available_cash > 0:
                price = self.datas[0].close[0]
                if price > 0:
                    size = int(available_cash / price)
                    
                    if size <= 0:
                        return
                        
                    if is_uptrend:
                        if self.datas[0].close[0] < self.ma_short[0] and self.rsi[0] < self.p.uptrend_rsi_buy:
                            self.log(f'买入信号: 上升行情 - 回调至短期均线. RSI: {self.rsi[0]:.2f}')
                            self.order = self.buy(size=size)

                    elif is_ranging:
                        if self.datas[0].pct_chg[0] < self.p.ranging_buy_pct_chg and self.rsi[0] < self.p.ranging_rsi_buy:
                            self.log(f'买入信号: 震荡行情 - 逢低买入. RSI: {self.rsi[0]:.2f}')
                            self.order = self.buy(size=size)

                    elif is_downtrend:
                        bias = (self.datas[0].close[0] - self.ma_long[0]) / self.ma_long[0]
                        if bias < self.p.downtrend_bias_buy:
                            self.log(f'买入信号: 下跌行情 - 超卖, BIAS: {bias:.2f}')
                            self.order = self.buy(size=size)