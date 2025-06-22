import backtrader as bt

class BreakoutStrategy(bt.Strategy):
    """
    一个多维度分析"波动性压缩后突破"的信号评级策略。
    - 核心逻辑：捕捉放量突破布林带上轨的信号，并对其进行评级。
    - 评级维度：宏观环境、压缩程度、成交量力度。
    - 目标：生成详细的信号日志，用于分析和辅助主策略决策，而非追求自身盈利。
    - 卖出逻辑：使用ATR跟踪止损来管理风险。
    """
    params = (
        # -- 核心指标 --
        ('bband_period', 20),         # 布林带周期
        ('bband_devfactor', 2.0),     # 布林带标准差
        ('volume_ma_period', 20),     # 成交量移动平均周期
        # -- 信号评级与观察模式参数 --
        ('ma_macro_period', 60),      # 定义宏观环境的长周期均线
        ('squeeze_period', 60),       # 波动性压缩回顾期
        ('observation_period', 15),   # 触发观察模式后的持续天数
        ('confirmation_lookback', 5), # "蓄势待发"信号的回看周期
        ('probation_period', 5),      # "蓄势待发"买入后的考察期天数
        # -- 风险管理 --
        ('initial_stake_pct', 0.90),  # 初始仓位（占总资金）
        ('atr_period', 14),           # ATR周期
        ('atr_multiplier', 2.0),      # ATR止损乘数
    )

    def __init__(self):
        # 布林带指标
        self.bband = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bband_period, devfactor=self.p.bband_devfactor
        )
        # 布林带宽度 (BBW = (UpperBand - LowerBand) / MiddleBand)
        self.bb_width = (self.bband.lines.top - self.bband.lines.bot) / self.bband.lines.mid
        # 计算布林带宽度在过去N期的范围，用于判断"压缩"
        self.highest_bbw = bt.indicators.Highest(self.bb_width, period=self.p.squeeze_period)
        self.lowest_bbw = bt.indicators.Lowest(self.bb_width, period=self.p.squeeze_period)
        # "蓄势待发"信号需要用到的近期最高价
        self.highest_close_confirm = bt.indicators.Highest(self.data.close, period=self.p.confirmation_lookback)

        # ATR指标，用于动态止损
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)

        # 新增：宏观环境判断均线
        self.ma_macro = bt.indicators.SMA(self.data, period=self.p.ma_macro_period)

        # 成交量均线
        self.volume_ma = bt.indicators.SMA(self.data.volume, period=self.p.volume_ma_period)

        # 状态跟踪
        self.order = None
        self.stop_price = 0
        self.highest_high_since_buy = 0
        # 新增：观察哨模式状态
        self.observation_mode = False
        self.observation_counter = 0
        self.sentry_source_signal = ""
        # 新增：蓄势待发信号的考察期状态
        self.coiled_spring_buy_pending = False
        self.in_coiled_spring_probation = False
        self.probation_counter = 0

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
                    f'买入成交: {order.executed.size}股 @ {order.executed.price:.2f}, '
                    f'花费: {order.executed.value:.2f}, '
                    f'仓位占总资产: {position_pct:.2f}%'
                )
                # 如果这是一个待处理的"蓄势待发"买单，则激活考察期
                if self.coiled_spring_buy_pending:
                    self.in_coiled_spring_probation = True
                    self.probation_counter = self.p.probation_period
                    self.coiled_spring_buy_pending = False
                    self.log(f'*** 进入【蓄势待发】考察期，为期 {self.p.probation_period} 天，使用中轨作为初始止损 ***')
            elif order.issell():
                self.log(
                    f'卖出成交: {abs(order.executed.size)}股 @ {order.executed.price:.2f}, '
                    f'获得: {order.executed.value:.2f}, '
                    f'仓位: 0.00%'
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

    def next(self):
        # 如果有挂单，不操作
        if self.order:
            return

        # --- 1. 持仓时：根据是否在考察期，执行不同的卖出逻辑 ---
        if self.position:
            # A. 如果在"蓄势待发"的考察期内
            if self.in_coiled_spring_probation:
                self.probation_counter -= 1

                # 检查是否通过考察: 收盘价站上布林带上轨
                if self.data.close[0] > self.bband.lines.top[0]:
                    self.log('*** 考察期成功通过！切换为ATR跟踪止损 ***')
                    self.in_coiled_spring_probation = False
                    # 通过后，立即为ATR止损设置初始值
                    self.highest_high_since_buy = self.data.high[0]
                    self.stop_price = self.highest_high_since_buy - self.p.atr_multiplier * self.atr[0]
                    return # 通过后，本轮逻辑结束，等待下一根K线

                # 检查是否考察失败(1): 跌破中轨生命线
                elif self.data.close[0] < self.bband.lines.mid[0]:
                    self.log('卖出信号: 考察期内跌破中轨，清仓')
                    self.order = self.close()
                
                # 检查是否考察失败(2): 考察期结束仍未突破
                elif self.probation_counter <= 0:
                    self.log('卖出信号: 考察期结束，未能突破上轨，清仓')
                    self.order = self.close()
                
                return # 考察期内的逻辑结束

            # B. 不在考察期内（即普通突破，或已通过考察的仓位），执行ATR跟踪止损
            else:
                # 如果是入场第一天，只设置初始止损，不操作
                if self.highest_high_since_buy == 0:
                    self.highest_high_since_buy = self.data.high[0]
                    self.stop_price = self.data.close[0] - self.p.atr_multiplier * self.atr[0]
                    self.log(
                        f'入场首日，设置初始ATR止损 @ {self.stop_price:.2f} '
                        f'(基于收盘价: {self.data.close[0]:.2f} 和 ATR: {self.atr[0]:.2f})'
                    )
                    return

                # 更新买入后的最高价
                self.highest_high_since_buy = max(self.highest_high_since_buy, self.data.high[0])
                # 计算新的跟踪止损位
                new_stop_price = self.highest_high_since_buy - self.p.atr_multiplier * self.atr[0]
                # 止损位只上不下
                self.stop_price = max(self.stop_price, new_stop_price)

                if self.data.close[0] < self.stop_price:
                    self.log(
                        f'卖出信号: 触发ATR跟踪止损 @ {self.stop_price:.2f} '
                        f'(最高点: {self.highest_high_since_buy:.2f}, ATR: {self.atr[0]:.2f})'
                    )
                    self.order = self.close()
                return # 持仓时，完成止损检查后即可结束

        # --- 2. 空仓时：根据模式决定买入逻辑 ---
        if self.observation_mode:
            # A. 观察模式：寻找二次确认信号
            self.observation_counter -= 1

            # 1. 优先检查"蓄势待发"信号
            if self.check_coiled_spring_conditions():
                log_msg = f'突破信号:【蓄势待发】(源信号: {self.sentry_source_signal})'
                self.log(log_msg)
                stake = self.broker.getvalue() * self.p.initial_stake_pct
                size = int(stake / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
                    self.coiled_spring_buy_pending = True # 标记这是一个待激活考察期的买单
                self.observation_mode = False
                self.log('*** 二次确认信号已发出，解除观察模式 ***')
                return

            # 2. 如果没有"蓄势待发"，再检查普通的"V型穿越"信号
            if self.check_v_reversal_conditions():
                log_msg = f'突破信号:【V型反转】(源信号: {self.sentry_source_signal})'
                self.log(log_msg)
                stake = self.broker.getvalue() * self.p.initial_stake_pct
                size = int(stake / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
                self.observation_mode = False
                self.log('*** 二次确认信号已执行，解除观察模式 ***')
                return

            # 3. 如果都没有，则继续观察...
            if self.observation_counter <= 0:
                self.log('*** 观察期结束，未出现二次确认信号，解除观察模式 ***')
                self.observation_mode = False
        else:
            # B. 常规模式：寻找初始突破信号
            is_breakout = self.data.close[0] > self.bband.lines.top[0]
            is_volume_up = self.data.volume[0] > self.volume_ma[0]

            if is_breakout and is_volume_up:
                # --- 信号评级系统 ---
                
                # 1. 宏观环境评级
                if self.data.close[0] > self.ma_macro[0]:
                    env_grade, env_score = '牛市', 3
                else:
                    env_grade, env_score = '熊市', 1
                
                # 2. 压缩程度评级
                bbw_range = self.highest_bbw[-1] - self.lowest_bbw[-1]
                squeeze_pct = (self.bb_width[-1] - self.lowest_bbw[-1]) / bbw_range if bbw_range > 1e-9 else 0
                if squeeze_pct < 0.10:   squeeze_grade, squeeze_score = 'A级', 3
                elif squeeze_pct < 0.25: squeeze_grade, squeeze_score = 'B级', 2
                elif squeeze_pct < 0.40: squeeze_grade, squeeze_score = 'C级', 1
                else:                    squeeze_grade, squeeze_score = 'D级', 0

                # 3. 成交量力度评级
                volume_ratio = self.data.volume[0] / self.volume_ma[0]
                if volume_ratio > 2.0:   volume_grade, volume_score = 'A级', 3
                elif volume_ratio > 1.5: volume_grade, volume_score = 'B级', 2
                else:                    volume_grade, volume_score = 'C级', 1
                
                # 综合评级
                total_score = env_score + squeeze_score + volume_score
                if total_score >= 8:     overall_grade = '【A+级】'
                elif total_score >= 6:   overall_grade = '【B级】'
                else:                    overall_grade = '【C级】'

                log_msg = (
                    f'突破信号: {overall_grade} '
                    f'(环境:{env_grade}, '
                    f'压缩:{squeeze_grade}({squeeze_pct:.0%}), '
                    f'量能:{volume_grade}({volume_ratio:.1f}x))'
                )
                self.log(log_msg)
                
                # --- 核心改动：触发观察模式 ---
                if total_score >= 6: # B级或更优的信号
                    self.log(f'*** 触发【突破观察哨】模式，观察期 {self.p.observation_period} 天 ***')
                    self.observation_mode = True
                    self.observation_counter = self.p.observation_period
                    # 记录源信号的关键部分用于后续日志
                    self.sentry_source_signal = f"{overall_grade} @ {self.datas[0].datetime.date(0)}"

                # 为了分析，我们仍然执行所有压缩评级不为D的信号
                if squeeze_score > 0:
                    stake = self.broker.getvalue() * self.p.initial_stake_pct
                    size = int(stake / self.data.close[0])
                    if size > 0:
                        self.order = self.buy(size=size)

    def check_coiled_spring_conditions(self):
        """
        检查"蓄势待发"（W型或平台整理后启动）信号条件。
        这是一个高优先级的二次确认信号。
        """
        # 条件1: 必须是阳线且放量
        if not (self.data.close[0] > self.data.open[0] and self.data.volume[0] > self.volume_ma[0]):
            return False
            
        # 条件2: 收盘价创近期新高
        # self.highest_close_confirm[-1] 获取的是截止到昨天(t-1)的N日最高收盘价
        if self.data.close[0] < self.highest_close_confirm[-1]:
            return False

        # 条件3 & 4: 在回看周期内，收盘价未破中轨，最低价未破下轨 (更严格的平台整理)
        for i in range(1, self.p.confirmation_lookback + 1):
            if self.data.close[-i] < self.bband.lines.mid[-i]:
                return False
            if self.data.low[-i] < self.bband.lines.bot[-i]:
                return False
        
        return True

    def check_v_reversal_conditions(self):
        """
        检查"V型反转"信号条件。
        这是一个普通的二次确认信号。
        """
        # 条件1: 从下向上穿越中轨
        is_cross_mid = self.data.close[-1] < self.bband.lines.mid[-1] and \
                       self.data.close[0] > self.bband.lines.mid[0]
        # 条件2: 成交量配合
        is_volume_ok = self.data.volume[0] > self.volume_ma[0]

        return is_cross_mid and is_volume_ok