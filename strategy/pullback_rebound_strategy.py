import backtrader as bt


class PullbackReboundStrategy(bt.Strategy):
    """
    止跌反弹策略 - 专门用于捕捉主升浪后回调企稳的反弹机会
    
    策略逻辑：
    1. 识别经历量价齐升主升浪后的回调
    2. 在回调过程中寻找企稳信号：
       a. 量价背离：下跌中出现上涨并缩量
       b. 量窒息：进一步缩量
       c. 收红K线：开始上涨，尾盘买入
    3. 简单止盈止损，主要吃反弹段利润
    """
    
    params = (
        # -- 主升浪识别参数 --
        ('uptrend_period', 20),          # 主升浪判断周期
        ('uptrend_min_gain', 0.30),      # 主升浪最小涨幅30%
        ('volume_ma_period', 20),        # 成交量均线周期
        ('volume_surge_ratio', 1.5),     # 主升浪期间放量倍数
        
        # -- 回调识别参数 --
        ('pullback_max_ratio', 0.15),    # 最大回调幅度15%
        ('pullback_max_days', 15),       # 最大回调天数（调整为15天）
        ('pullback_min_days', 3),        # 最小回调天数
        
        # -- 企稳信号参数 --
        ('volume_dry_ratio', 0.6),       # 量窒息阈值（相对均量）
        ('stabilization_days', 4),       # 企稳信号观察期
        ('divergence_days', 3),          # 量价背离观察期
        
        # -- 交易参数 --
        ('initial_stake_pct', 0.8),      # 初始仓位比例
        ('profit_target', 0.12),         # 止盈目标12%
        ('stop_loss', 0.05),             # 止损比例5%
        ('max_hold_days', 10),           # 最大持有天数
        
        # -- 调试参数 --
        ('debug', False),                # 是否开启详细日志
    )
    
    def __init__(self):
        # -- 技术指标 --
        self.sma = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.uptrend_period
        )
        self.volume_ma = bt.indicators.SimpleMovingAverage(
            self.data.volume, period=self.p.volume_ma_period
        )
        
        # -- 状态变量 --
        self.strategy_state = 'SCANNING'  # SCANNING, WAITING_PULLBACK, MONITORING_STABILIZATION, POSITION_HELD
        self.uptrend_high_price = 0.0     # 主升浪高点价格
        self.uptrend_high_date = None     # 主升浪高点日期
        self.pullback_start_date = None   # 回调开始日期
        self.pullback_low_price = float('inf')  # 回调期间最低价
        
        # -- 交易状态 --
        self.order = None
        self.buy_price = 0.0
        self.buy_date = None
        self.hold_days = 0
        
        # -- 企稳信号跟踪 --
        self.recent_lows = []             # 最近几日的最低价
        self.recent_volumes = []          # 最近几日的成交量

        # -- 参数检查 --
        self.param_logged = False         # 是否已记录参数
        
    def log(self, txt, dt=None):
        """日志输出"""
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()} - {txt}')
    
    def notify_order(self, order):
        """订单状态通知"""
        if order.status in [order.Submitted, order.Accepted]:
            return
        
        if order.status in [order.Completed]:
            if order.isbuy():
                self.buy_price = order.executed.price
                self.buy_date = self.datas[0].datetime.date(0)
                self.hold_days = 0
                self.strategy_state = 'POSITION_HELD'
                position_pct = order.executed.value / self.broker.getvalue() * 100
                self.log(
                    f'买入成交 (止跌反弹): {order.executed.size}股 @ {order.executed.price:.2f}, '
                    f'仓位: {position_pct:.2f}%'
                )
            elif order.issell():
                # 详细卖出日志
                sell_price = order.executed.price
                sell_size = abs(order.executed.size)
                if hasattr(self, 'buy_price') and self.buy_price > 0:
                    profit_loss = (sell_price - self.buy_price) / self.buy_price
                    if profit_loss > 0:
                        self.log(f'止盈卖出: 盈利 {profit_loss:.2%}')
                    else:
                        self.log(f'止损卖出: 亏损 {profit_loss:.2%}')

                self.log(f'卖出成交: {sell_size}股 @ {sell_price:.2f}')
                self._reset_strategy_state()
                
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('订单未能成交')
        
        self.order = None
    
    def notify_trade(self, trade):
        """交易完成通知"""
        if trade.isclosed:
            self.log(f'交易关闭, 净盈亏: {trade.pnlcomm:.2f}, 当前总资产: {self.broker.getvalue():.2f}')
    
    def next(self):
        """策略主逻辑"""
        if self.order:
            return

        # 测试日志输出
        if len(self) == 1:  # 第一天
            self.log("策略开始运行")

        # 更新持有天数
        if self.position:
            self.hold_days += 1
        
        # 根据当前状态执行不同逻辑
        if self.strategy_state == 'SCANNING':
            self._scan_for_uptrend()
        elif self.strategy_state == 'WAITING_PULLBACK':
            self._wait_for_pullback()
        elif self.strategy_state == 'MONITORING_STABILIZATION':
            self._monitor_stabilization()
        elif self.strategy_state == 'POSITION_HELD':
            self._handle_position()
    
    def _scan_for_uptrend(self):
        """扫描主升浪"""
        # 需要足够的历史数据
        if len(self) < self.p.uptrend_period:
            return
        
        # 计算最近period天的复利涨幅
        period_start_price = self.data.close[-self.p.uptrend_period]
        current_price = self.data.close[0]

        # 使用复利计算：考虑期间的波动
        # 计算期间的最低点，确保是从真正的低点开始计算
        period_prices = [self.data.close[-i] for i in range(self.p.uptrend_period, 0, -1)]
        period_low = min(period_prices)

        # 如果当前价格比期间最低点的涨幅更大，使用最低点作为起点
        gain_from_start = (current_price - period_start_price) / period_start_price
        gain_from_low = (current_price - period_low) / period_low
        period_gain = max(gain_from_start, gain_from_low)
        
        # 检查趋势质量：确保是真正的主升浪而不是反弹
        # 1. 价格应该创近期新高（更严格的条件）
        recent_high = max([self.data.high[-i] for i in range(min(40, len(self)), 0, -1)])
        current_high = self.data.high[0]
        # 要求当日最高价创新高，且收盘价不能离最高价太远
        is_new_high = (current_high > recent_high and
                      current_price >= current_high * 0.95)  # 收盘价不能离当日最高价太远

        # 2. 均线多头排列：短期均线在长期均线之上
        sma_short = sum([self.data.close[-i] for i in range(10, 0, -1)]) / 10
        sma_long = sum([self.data.close[-i] for i in range(20, 0, -1)]) / 20
        is_bullish_alignment = sma_short > sma_long

        # 3. 趋势持续性检查：确保不是短期反弹
        # 检查最近5天是否有连续上涨趋势
        recent_closes = [self.data.close[-i] for i in range(5, 0, -1)]
        uptrend_days = sum(1 for i in range(1, len(recent_closes))
                          if recent_closes[i] > recent_closes[i-1])
        is_sustained_uptrend = uptrend_days >= 3  # 至少3天上涨

        # 4. 价格位置检查：确保不是在下跌趋势中的反弹
        # 当前价格应该明显高于更长期的均线
        sma_long_term = sum([self.data.close[-i] for i in range(40, 0, -1)]) / 40
        is_above_long_term_trend = current_price > sma_long_term * 1.1  # 高于长期均线10%

        # 调试信息
        if self.p.debug and period_gain >= self.p.uptrend_min_gain:
            debug_msg = (
                f'[debug]主升浪检查 - 涨幅: {period_gain:.2%}, '
                f'创新高: {is_new_high}, 多头排列: {is_bullish_alignment}, '
                f'持续上涨: {is_sustained_uptrend}, 长期趋势: {is_above_long_term_trend}, '
                f'放量: {self.data.volume[0] > self.volume_ma[0] * self.p.volume_surge_ratio}'
            )
            self.log(debug_msg)

        # 检查是否满足主升浪条件（更严格的条件）
        is_strong_uptrend = (
            period_gain >= self.p.uptrend_min_gain and  # 涨幅足够
            current_price > self.sma[0] and             # 价格在均线之上
            self.data.volume[0] > self.volume_ma[0] * self.p.volume_surge_ratio and  # 放量
            is_new_high and                             # 创近期新高
            is_bullish_alignment and                    # 均线多头排列
            is_sustained_uptrend and                    # 持续上涨趋势
            is_above_long_term_trend                    # 明显高于长期趋势
        )

        if is_strong_uptrend:
            self.uptrend_high_price = current_price
            self.uptrend_high_date = self.datas[0].datetime.date(0)
            self.strategy_state = 'WAITING_PULLBACK'
            self.log(f'*** 检测到主升浪，高点: {self.uptrend_high_price:.2f}, 涨幅: {period_gain:.2%} ***')
    
    def _wait_for_pullback(self):
        """等待回调"""
        current_price = self.data.close[0]
        
        # 更新主升浪高点
        if current_price > self.uptrend_high_price:
            self.uptrend_high_price = current_price
            self.uptrend_high_date = self.datas[0].datetime.date(0)
            return
        
        # 检查是否开始回调
        pullback_ratio = (self.uptrend_high_price - current_price) / self.uptrend_high_price
        
        if pullback_ratio >= 0.03:  # 回调超过3%认为开始回调
            self.pullback_start_date = self.datas[0].datetime.date(0)
            self.pullback_low_price = current_price
            self.strategy_state = 'MONITORING_STABILIZATION'
            self.log(f'*** 开始回调，从 {self.uptrend_high_price:.2f} 回调至 {current_price:.2f} ({pullback_ratio:.2%}) ***')
    
    def _monitor_stabilization(self):
        """监控企稳信号"""
        current_price = self.data.close[0]
        current_volume = self.data.volume[0]
        
        # 更新回调最低价
        if current_price < self.pullback_low_price:
            self.pullback_low_price = current_price
        
        # 检查回调是否过度或时间过长
        pullback_ratio = (self.uptrend_high_price - current_price) / self.uptrend_high_price
        days_since_pullback = (self.datas[0].datetime.date(0) - self.pullback_start_date).days
        
        if pullback_ratio > self.p.pullback_max_ratio or days_since_pullback > self.p.pullback_max_days:
            self.log(f'回调过度或时间过长，重新扫描。回调幅度: {pullback_ratio:.2%}, 天数: {days_since_pullback}')
            self._reset_strategy_state()
            return
        
        # 检查企稳信号
        if days_since_pullback >= self.p.pullback_min_days:
            if self._check_stabilization_signals():
                # 当天收盘买入（模拟尾盘买入）
                self._execute_buy_signal_eod()
            elif self._check_pre_stabilization_signals():
                # 预警信号：明天可能出现买点
                self._log_warning_signal()
    
    def _check_stabilization_signals(self):
        """检查企稳信号abc"""
        if len(self) < self.p.stabilization_days:
            return False
        
        # a. 量价背离：最近几日价格新低但成交量萎缩
        volume_divergence = self._check_volume_price_divergence()
        
        # b. 量窒息：成交量低于均量阈值
        volume_dry = self.data.volume[0] < self.volume_ma[0] * self.p.volume_dry_ratio
        
        # c. 收红K线：当日收盘价高于开盘价
        red_candle = self.data.close[0] > self.data.open[0]
        
        if volume_divergence and volume_dry and red_candle:
            # 正常交易日志（非debug）
            self.log(f'*** 企稳信号确认: 量价背离={volume_divergence}, 量窒息={volume_dry}, 红K线={red_candle} ***')
            return True
        else:
            # 总是显示企稳信号检查结果（用于调试）
            self.log(f'企稳信号检查 - 量价背离: {volume_divergence}, 量窒息: {volume_dry}, 红K线: {red_candle}')
        
        return False
    
    def _check_volume_price_divergence(self):
        """检查量价背离"""
        if len(self) < self.p.divergence_days:
            return False

        # 检查最近几日是否出现价格相对低位但成交量萎缩
        recent_prices = [self.data.close[-i] for i in range(self.p.divergence_days)]
        recent_volumes = [self.data.volume[-i] for i in range(self.p.divergence_days)]

        # 价格在相对低位（放宽条件：在最近几日的下半部分）
        current_price = self.data.close[0]
        recent_min = min(recent_prices)
        recent_max = max(recent_prices)
        price_range = recent_max - recent_min

        # 如果价格在最近几日的下65%区间内，认为是相对低位
        is_relative_low = current_price <= recent_min + price_range * 0.65

        # 成交量萎缩（放宽条件）
        current_volume = self.data.volume[0]
        avg_recent_volume = sum(recent_volumes) / len(recent_volumes)
        is_volume_shrinking = current_volume < avg_recent_volume * 0.9

        return is_relative_low and is_volume_shrinking

    def _check_pre_stabilization_signals(self):
        """检查预警信号：接近企稳但还差一点"""
        if len(self) < self.p.stabilization_days:
            return False

        # 检查是否接近企稳条件
        volume_divergence = self._check_volume_price_divergence()
        volume_dry = self.data.volume[0] < self.volume_ma[0] * (self.p.volume_dry_ratio + 0.1)  # 放宽10%

        # 如果量价背离已满足，且成交量接近窒息，就发出预警
        return volume_divergence and volume_dry

    def _log_warning_signal(self):
        """记录预警信号"""
        self.log(f'⚠️ 预警信号：接近企稳条件，明日关注是否收红K线 @ {self.data.close[0]:.2f}')

    def _execute_buy_signal_eod(self):
        """执行尾盘买入信号（当天收盘价买入）"""
        stake = self.broker.getvalue() * self.p.initial_stake_pct
        size = int(stake / self.data.close[0])

        if size > 0:
            # 简单买入（下一个bar开盘）
            self.order = self.buy(size=size)
            self.log(f'*** 止跌反弹买入信号触发 @ {self.data.close[0]:.2f} ***')
    
    def _handle_position(self):
        """处理持仓的止盈止损"""
        current_price = self.data.close[0]
        
        # 计算盈亏比例
        pnl_ratio = (current_price - self.buy_price) / self.buy_price
        
        # 止盈
        if pnl_ratio >= self.p.profit_target:
            self.log(f'止盈卖出: 盈利 {pnl_ratio:.2%}')
            self.order = self.close()
            return
        
        # 止损
        if pnl_ratio <= -self.p.stop_loss:
            self.log(f'止损卖出: 亏损 {pnl_ratio:.2%}')
            self.order = self.close()
            return
        
        # 时间止损
        if self.hold_days >= self.p.max_hold_days:
            self.log(f'时间止损: 持有 {self.hold_days} 天')
            self.order = self.close()
            return
    
    def _reset_strategy_state(self):
        """重置策略状态"""
        self.strategy_state = 'SCANNING'
        self.uptrend_high_price = 0.0
        self.uptrend_high_date = None
        self.pullback_start_date = None
        self.pullback_low_price = float('inf')
        self.buy_price = 0.0
        self.buy_date = None
        self.hold_days = 0
