import backtrader as bt


class WeeklyVolumeMomentumStrategy(bt.Strategy):
    """
    周量能放大 + 短期温和上行 的动量策略（A股）
    策略和同花顺动态板逻辑有区别，待完善

    选股/建仓信号（发生在日线bar收盘时，次日开盘买入）：
    1) 非ST股（需在外部过滤）；
    2) 周成交量环比增长率 > 100%（用5日均量对比5日前的5日均量近似）；
    3) 近3个月（约60个交易日）区间涨跌幅 < 40.1%；
    4) 排除高开≥5%；
    5) 当日收盘 > 昨收 且 当日涨幅 < 4.5%。

    交易规则：
    - 次日开盘满仓买入；
    - 基础持股周期2天；
    - 止损：收益率 ≤ -5% 立即卖出；
    - 止盈：一旦收益率 ≥ 9%，启动“坚定持有”模式，记录买入后最高价；
      当从最高价回撤1%时卖出（忽略2天持仓限制）。
    """

    params = (
        # 近似周度窗口与阈值
        ('week_window', 5),                   # 5交易日近似一周
        ('week_growth_ratio', 2.0),           # 周量环比 > 100% => 当前5日均量/5日前5日均量 > 2
        # 三个月窗口与阈值
        ('three_month_lookback_days', 60),    # 约3个月
        ('three_month_max_change', 0.401),    # 40.1%
        # 当日开盘/涨幅限制
        ('gap_open_exclude_pct', 0.05),       # 排除高开≥5%
        ('daily_gain_upper_pct', 0.045),      # 当日涨幅 < 4.5%
        # 交易参数
        ('initial_stake_pct', 1.0),           # 满仓
        ('base_hold_days', 2),                # 基础持有2天
        ('stop_loss_pct', 0.05),              # 硬止损5%
        ('trigger_trailing_profit_pct', 0.09),# 达到9%后启用回撤止盈
        ('trailing_drawdown_pct', 0.01),      # 从最高价回撤1%卖出
        # 调试
        ('debug', False),
    )

    def __init__(self):
        # 5日均量，用于近似“周成交量”比较
        self.vol_ma_5 = bt.indicators.SimpleMovingAverage(self.data.volume, period=self.p.week_window)

        # 交易状态
        self.order = None
        self.entry_price = 0.0
        self.entry_day_index = None
        self.hold_days = 0
        self.trailing_active = False
        self.peak_price_since_entry = 0.0

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()} - {txt}')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.entry_price = order.executed.price
                self.entry_day_index = len(self)
                self.hold_days = 0
                self.trailing_active = False
                self.peak_price_since_entry = self.entry_price
                position_pct = order.executed.value / self.broker.getvalue() * 100
                self.log(
                    f'买入成交: {order.executed.size}股 @ {order.executed.price:.2f}, '
                    f'仓位: {position_pct:.2f}%'
                )
            elif order.issell():
                self.log(
                    f'卖出成交: {abs(order.executed.size)}股 @ {order.executed.price:.2f}'
                )
                # 重置
                self.entry_price = 0.0
                self.entry_day_index = None
                self.hold_days = 0
                self.trailing_active = False
                self.peak_price_since_entry = 0.0
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('订单未能成交')

        self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f'交易关闭, 净盈亏: {trade.pnlcomm:.2f}, 当前总资产: {self.broker.getvalue():.2f}')

    def next(self):
        if self.order:
            return

        # 持仓管理
        if self.position:
            self._handle_position()
            return

        # 建仓信号检测
        if self._check_entry_signal():
            # 次日开盘买入（市价单）
            stake = self.broker.getvalue() * self.p.initial_stake_pct
            size = int(stake / max(self.data.close[0], 1e-6))
            if size > 0:
                self.log('买入信号出现：次日开盘满仓买入')
                self.order = self.buy(size=size)

    def _check_entry_signal(self) -> bool:
        # 数据充足性检查：至少需要 5*2 + 60 条，且有昨日收盘
        min_len = max(self.p.week_window * 2 + 1, self.p.three_month_lookback_days + 1)
        if len(self) < min_len:
            return False

        prev_close = self.data.close[-1]
        today_open = self.data.open[0]
        today_close = self.data.close[0]

        # 2) 周成交量环比 > 100%（用5日均量对比5日前的5日均量）
        try:
            cur_avg5 = float(self.vol_ma_5[0])
            prev_avg5 = float(self.vol_ma_5[-self.p.week_window])
        except IndexError:
            return False
        if prev_avg5 <= 0:
            return False
        week_ratio = cur_avg5 / prev_avg5

        # 3) 近3个月涨跌幅 < 40.1%
        price_3m_ago = self.data.close[-self.p.three_month_lookback_days]
        three_month_change = (today_close / price_3m_ago - 1.0)

        # 4) 排除高开≥5%
        gap_open = (today_open / prev_close - 1.0)
        if gap_open >= self.p.gap_open_exclude_pct:
            if self.p.debug:
                self.log(f'[debug] 排除高开 {gap_open:.2%} ≥ {self.p.gap_open_exclude_pct:.2%}')
            return False

        # 5) 当日涨幅在 (0, 4.5%)
        daily_gain = (today_close / prev_close - 1.0)

        cond_week_vol = week_ratio > self.p.week_growth_ratio
        cond_3m = three_month_change < self.p.three_month_max_change
        cond_daily = 0.0 < daily_gain < self.p.daily_gain_upper_pct

        if self.p.debug:
            self.log(
                f'[debug] 条件: 周量比={week_ratio:.2f}(>{self.p.week_growth_ratio:.2f}), '
                f'3月涨幅={three_month_change:.2%}(<{self.p.three_month_max_change:.2%}), '
                f'日涨幅={daily_gain:.2%}(<{self.p.daily_gain_upper_pct:.2%})'
            )

        return cond_week_vol and cond_3m and cond_daily

    def _handle_position(self):
        # 更新持有天数
        if self.entry_day_index is not None:
            self.hold_days = len(self) - self.entry_day_index
        price = self.data.close[0]

        # 更新峰值价格
        if price > self.peak_price_since_entry:
            self.peak_price_since_entry = price

        pnl_ratio = (price / self.entry_price - 1.0)

        # 硬止损优先
        if pnl_ratio <= -self.p.stop_loss_pct:
            self.log(f'止损卖出: 亏损 {pnl_ratio:.2%} ≤ {(-self.p.stop_loss_pct):.2%}')
            self.order = self.close()
            return

        # 触发坚定持有模式
        if not self.trailing_active and pnl_ratio >= self.p.trigger_trailing_profit_pct:
            self.trailing_active = True
            self.peak_price_since_entry = max(self.peak_price_since_entry, price)
            self.log(f'达到止盈阈值 {self.p.trigger_trailing_profit_pct:.2%}，进入坚定持有模式')

        # 坚定持有模式：从最高价回撤1%卖出
        if self.trailing_active:
            if price <= self.peak_price_since_entry * (1.0 - self.p.trailing_drawdown_pct):
                drop = (price / self.peak_price_since_entry - 1.0)
                self.log(f'回撤止盈卖出: 距峰值回落 {drop:.2%} ≤ {-self.p.trailing_drawdown_pct:.2%}')
                self.order = self.close()
                return
            return  # 忽略基础持有周期

        # 未触发坚定持有：基础持有2天后卖出
        if self.hold_days >= self.p.base_hold_days:
            self.log(f'时间到期卖出: 已持有 {self.hold_days} 天')
            self.order = self.close()
            return 