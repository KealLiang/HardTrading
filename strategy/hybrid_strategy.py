import backtrader as bt


class HybridStrategy(bt.Strategy):
    """
    一个融合了"趋势突破"与"恐慌反弹"的混合策略。

    - 核心引擎 (Breakout Engine):
      继承自BreakoutStrategy，负责捕捉"波动性压缩-突破"后的趋势性机会。
      采用"观察哨"模式来过滤初次突破的噪音，并通过二次确认信号提高胜率。
      使用ATR跟踪止损来让利润奔跑。

    - 卫星战术 (Panic Rebound Module):
      从MarketRegimeStrategy中引入，作为独立的"机会主义"模块。
      专门用于捕捉市场因极端超卖而产生的V型反弹机会（左侧交易）。
      使用独立的、更激进的止损和持仓周期规则。
    """
    params = (
        # ===== 核心引擎: 突破策略参数 =====
        # -- 核心指标 --
        ('bband_period', 20),  # 布林带周期
        ('bband_devfactor', 2.0),  # 布林带标准差
        ('volume_ma_period', 20),  # 成交量移动平均周期
        # -- 信号评级与观察模式参数 --
        ('ma_macro_period', 60),  # 定义宏观环境的长周期均线
        ('squeeze_period', 60),  # 波动性压缩回顾期
        ('observation_period', 15),  # 触发观察模式后的持续天数
        ('confirmation_lookback', 5),  # "蓄势待发"信号的回看周期
        ('probation_period', 5),  # "蓄势待发"买入后的考察期天数
        # -- 风险管理 --
        ('initial_stake_pct', 0.90),  # 初始仓位（占总资金）
        ('atr_period', 14),  # ATR周期
        ('atr_multiplier', 2.0),  # ATR止损乘数

        # ===== 卫星战术: 恐慌反弹参数 =====
        ('rsi_period', 14),
        ('rsi_oversold', 30),  # 恐慌买点的RSI阈值
        ('panic_rebound_hold_days', 10),  # 恐慌反弹模式最大持有天数
    )

    def __init__(self):
        # --- 核心引擎指标 ---
        self.bband = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bband_period, devfactor=self.p.bband_devfactor
        )
        self.bb_width = (self.bband.lines.top - self.bband.lines.bot) / self.bband.lines.mid
        self.highest_bbw = bt.indicators.Highest(self.bb_width, period=self.p.squeeze_period)
        self.lowest_bbw = bt.indicators.Lowest(self.bb_width, period=self.p.squeeze_period)
        self.highest_close_confirm = bt.indicators.Highest(self.data.close, period=self.p.confirmation_lookback)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.ma_macro = bt.indicators.SMA(self.data, period=self.p.ma_macro_period)
        self.volume_ma = bt.indicators.SMA(self.data.volume, period=self.p.volume_ma_period)

        # --- 卫星战术指标 ---
        self.rsi = bt.indicators.RSI(self.data, period=self.p.rsi_period)

        # --- 核心引擎状态跟踪 ---
        self.order = None
        self.stop_price = 0
        self.highest_high_since_buy = 0
        self.observation_mode = False
        self.observation_counter = 0
        self.sentry_source_signal = ""
        self.coiled_spring_buy_pending = False
        self.in_coiled_spring_probation = False
        self.probation_counter = 0
        self.confirmation_signals = [
            ('coiled_spring', self.check_coiled_spring_conditions),
            ('v_reversal', self.check_v_reversal_conditions),
        ]

        # --- 卫星战术状态跟踪 ---
        self.is_panic_rebound_trade = False
        self.pending_buy_signal_type = None
        self.buy_tick = 0  # 记录买入时的bar，用于时间止损

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
                    f'买入成交 ({self.pending_buy_signal_type}): {order.executed.size}股 @ {order.executed.price:.2f}, '
                    f'花费: {order.executed.value:.2f}, '
                    f'仓位: {position_pct:.2f}%'
                )

                # 根据买入信号类型，设置不同的初始状态
                if self.pending_buy_signal_type == '恐慌反弹':
                    self.is_panic_rebound_trade = True
                    self.buy_tick = len(self)  # 记录入场时间
                    self.stop_price = self.data.low[0]  # 使用当日最低价作为硬止损
                    self.log(f'*** 进入【恐慌反弹】模式, 硬止损位于 {self.stop_price:.2f} ***')

                elif self.pending_buy_signal_type == '蓄势待发':
                    self.in_coiled_spring_probation = True
                    self.probation_counter = self.p.probation_period
                    self.log(f'*** 进入【蓄势待发】考察期, 为期 {self.p.probation_period} 天 ***')

                # 常规突破和V型反转，直接由后续next中的ATR逻辑管理

                self.pending_buy_signal_type = None  # 重置待处理信号

            elif order.issell():
                self.log(
                    f'卖出成交: {abs(order.executed.size)}股 @ {order.executed.price:.2f}, '
                    f'获得: {order.executed.value:.2f}'
                )
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('订单未能成交')

        self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f'交易关闭, 净盈亏: {trade.pnlcomm:.2f}, 当前总资产: {self.broker.getvalue():.2f}')
            # 重置所有交易相关的状态
            self.stop_price = 0
            self.highest_high_since_buy = 0
            self.in_coiled_spring_probation = False
            self.probation_counter = 0
            self.is_panic_rebound_trade = False
            self.buy_tick = 0

    def next(self):
        if self.order:
            return

        # --- 1. 持仓时：根据交易类型分发到不同的风控逻辑 ---
        if self.position:
            if self.is_panic_rebound_trade:
                self._handle_panic_rebound_trade()
            else:
                self._handle_breakout_trade()
            return

        # --- 2. 空仓时：机会扫描与信号捕捉 ---

        # 扫描1 (最高优先级): 恐慌反弹机会
        if self._check_panic_buy_signal():
            self.log('机会信号:【恐慌反弹】(RSI超卖 & 触及下轨)')
            stake = self.broker.getvalue() * self.p.initial_stake_pct
            size = int(stake / self.data.close[0])
            if size > 0:
                self.order = self.buy(size=size)
                self.pending_buy_signal_type = '恐慌反弹'
            return

        # 扫描2: 突破引擎机会
        if self.observation_mode:
            self._check_confirmation_signals()
            if not self.order and self.observation_counter > 0:
                self.observation_counter -= 1
                if self.observation_counter <= 0:
                    self.log('*** 观察期结束，未出现二次确认信号，解除观察模式 ***')
                    self.observation_mode = False
        else:
            self._check_initial_breakout()

    # --- 交易处理模块 ---

    def _handle_panic_rebound_trade(self):
        """处理恐慌反弹持仓的风控逻辑"""
        # A. 硬止损：如果价格创下买入日以来的新低
        if self.data.low[0] < self.stop_price:
            self.log(f'卖出信号: (恐慌模式) 创下新低, 触发硬止损 @ {self.stop_price:.2f}')
            self.order = self.close()
            return

        # B. 时间止损：如果持有时间过长
        hold_days = len(self) - self.buy_tick
        if hold_days >= self.p.panic_rebound_hold_days:
            self.log(f'卖出信号: (恐慌模式) 持有 {hold_days} 天, 时间止损')
            self.order = self.close()
            return

        # C. 止盈逻辑：反弹到布林带中轨
        if self.data.close[0] > self.bband.lines.mid[0]:
            self.log(f'卖出信号: (恐慌模式) 价格反弹至中轨, 止盈')
            self.order = self.close()
            return

    def _handle_breakout_trade(self):
        """处理突破引擎持仓的风控逻辑(原BreakoutStrategy逻辑)"""
        # A. "蓄势待发"考察期逻辑
        if self.in_coiled_spring_probation:
            self.probation_counter -= 1
            if self.data.close[0] > self.bband.lines.top[0]:
                self.log('*** 考察期成功通过！切换为ATR跟踪止损 ***')
                self.in_coiled_spring_probation = False
                self.highest_high_since_buy = self.data.high[0]
                self.stop_price = self.highest_high_since_buy - self.p.atr_multiplier * self.atr[0]
            elif self.data.close[0] < self.bband.lines.mid[0]:
                self.log('卖出信号: 考察期内跌破中轨，清仓')
                self.order = self.close()
            elif self.probation_counter <= 0:
                self.log('卖出信号: 考察期结束，未能突破上轨，清仓')
                self.order = self.close()
            return

        # B. ATR跟踪止损逻辑
        if self.highest_high_since_buy == 0:  # 入场首日
            self.highest_high_since_buy = self.data.high[0]
            self.stop_price = self.data.close[0] - self.p.atr_multiplier * self.atr[0]
            self.log(f'入场首日，设置初始ATR止损 @ {self.stop_price:.2f}')
            return

        self.highest_high_since_buy = max(self.highest_high_since_buy, self.data.high[0])
        new_stop_price = self.highest_high_since_buy - self.p.atr_multiplier * self.atr[0]
        self.stop_price = max(self.stop_price, new_stop_price)

        if self.data.close[0] < self.stop_price:
            self.log(f'卖出信号: 触发ATR跟踪止损 @ {self.stop_price:.2f}')
            self.order = self.close()

    # --- 信号扫描模块 ---

    def _check_panic_buy_signal(self):
        """检查恐慌反弹信号"""
        return self.rsi[0] < self.p.rsi_oversold and self.data.low[0] <= self.bband.lines.bot[0]

    def _check_initial_breakout(self):
        """检查初始突破信号"""
        is_breakout = self.data.close[0] > self.bband.lines.top[0]
        is_volume_up = self.data.volume[0] > self.volume_ma[0]

        if not (is_breakout and is_volume_up):
            return

        # --- 信号评级系统 ---
        env_grade, env_score = ('牛市', 3) if self.data.close[0] > self.ma_macro[0] else ('熊市', 1)
        bbw_range = self.highest_bbw[-1] - self.lowest_bbw[-1]
        squeeze_pct = (self.bb_width[-1] - self.lowest_bbw[-1]) / bbw_range if bbw_range > 1e-9 else 0
        if squeeze_pct < 0.10:
            squeeze_grade, squeeze_score = 'A级', 3
        elif squeeze_pct < 0.25:
            squeeze_grade, squeeze_score = 'B级', 2
        elif squeeze_pct < 0.40:
            squeeze_grade, squeeze_score = 'C级', 1
        else:
            squeeze_grade, squeeze_score = 'D级', 0

        volume_ratio = self.data.volume[0] / self.volume_ma[0]
        if volume_ratio > 2.0:
            volume_grade, volume_score = 'A级', 3
        elif volume_ratio > 1.5:
            volume_grade, volume_score = 'B级', 2
        else:
            volume_grade, volume_score = 'C级', 1

        total_score = env_score + squeeze_score + volume_score
        if total_score >= 8:
            overall_grade = '【A+级】'
        elif total_score >= 6:
            overall_grade = '【B级】'
        else:
            overall_grade = '【C级】'

        log_msg = f'突破信号: {overall_grade} (环境:{env_grade}, 压缩:{squeeze_grade}({squeeze_pct:.0%}), 量能:{volume_grade}({volume_ratio:.1f}x))'
        self.log(log_msg)

        # --- 核心改动：触发观察模式或直接买入 ---
        if total_score >= 6:
            self.log(f'*** 触发【突破观察哨】模式，观察期 {self.p.observation_period} 天 ***')
            self.observation_mode = True
            self.observation_counter = self.p.observation_period
            self.sentry_source_signal = f"{overall_grade} @ {self.datas[0].datetime.date(0)}"

        if squeeze_score > 0:
            stake = self.broker.getvalue() * self.p.initial_stake_pct
            size = int(stake / self.data.close[0])
            if size > 0:
                self.order = self.buy(size=size)
                self.pending_buy_signal_type = '初始突破'

    def _check_confirmation_signals(self):
        """统一检查所有二次确认信号"""
        for signal_name, check_function in self.confirmation_signals:
            if check_function():
                signal_map = {
                    'coiled_spring': ('【蓄势待发】', '发出', '蓄势待发'),
                    'v_reversal': ('【V型反转】', '执行', 'V型反转')
                }
                log_name, log_suffix, pending_type = signal_map.get(signal_name)

                self.log(f'突破信号:{log_name}(源信号: {self.sentry_source_signal})')
                stake = self.broker.getvalue() * self.p.initial_stake_pct
                size = int(stake / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
                    self.pending_buy_signal_type = pending_type

                self.observation_mode = False
                self.log(f'*** 二次确认信号已{log_suffix}，解除观察模式 ***')
                return

    def check_coiled_spring_conditions(self):
        """检查"蓄势待发"信号条件"""
        if not (self.data.close[0] > self.data.open[0] and self.data.volume[0] > self.volume_ma[0]):
            return False
        if self.data.close[0] < self.highest_close_confirm[-1]:
            return False
        for i in range(1, self.p.confirmation_lookback + 1):
            if self.data.close[-i] < self.bband.lines.mid[-i] or self.data.low[-i] < self.bband.lines.bot[-i]:
                return False
        return True

    def check_v_reversal_conditions(self):
        """检查"V型反转"信号条件"""
        is_cross_mid = self.data.close[-1] < self.bband.lines.mid[-1] and self.data.close[0] > self.bband.lines.mid[0]
        is_volume_ok = self.data.volume[0] > self.volume_ma[0]
        return is_cross_mid and is_volume_ok
