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
        # ========== 第一部分：选股逻辑参数 ==========
        # -- 调试开关 --
        ('debug', False),  # 是否开启信号评级的详细日志
        
        # -- 核心指标 --
        ('bband_period', 20),  # 布林带周期
        ('bband_devfactor', 1.8),  # 布林带标准差
        ('volume_ma_period', 22),  # 成交量移动平均周期
        ('ma_macro_period', 60),  # 定义宏观环境的长周期均线
        
        # -- 前高突破维度 --
        ('enable_prior_high_score', True),  # 是否启用前高突破评分
        ('prior_high_lookback', 80),  # 前高回看期（交易日）
        ('prior_high_upper_threshold', 0.04),  # 突破压力位的阈值（+4%）
        ('prior_high_lower_threshold', 0.04),  # 压力位下方的阈值（-4%）
        ('prior_high_exclude_recent', 5),  # 计算前高时排除最近N天
        
        # -- 高位盘整识别 --
        ('consolidation_lookback', 5),  # 短期均线盘整的回看期
        ('consolidation_ma_proximity_pct', 0.02),  # 短期均线接近度阈值 (2%)
        ('consolidation_ma_max_slope', 1.05),  # 盘整期间MA最大斜率 (5日涨5%)
        
        # -- 波动性压缩与观察期 --
        ('squeeze_period', 60),  # 波动性压缩回顾期
        ('observation_period', 15),  # 触发观察模式后的持续天数
        
        # -- 三速档位系统 --
        ('enable_fast_track', True),  # 是否启用快速通道
        ('fast_track_ma5_ma10_ratio', 1.03),  # 快速通道：MA5/MA10强势标准
        ('optimal_entry_zone_lower', -0.03),  # 最优买入区间：MA5下限-3%
        ('optimal_entry_zone_upper', 0.09),  # 最优买入区间：MA5上限+9%
        ('pullback_wait_period', 1),  # 回踩等待期限（天）
        
        # -- 止损纠错系统 --
        ('enable_stop_loss_correction', True),  # 是否启用止损纠错机制
        ('stop_loss_correction_window', 7),  # 止损后的纠错观察窗口（自然日，含周末）
        ('correction_trend_min_strength', 1.0),  # 纠错触发的最小趋势强度（MA5近N日涨幅%）
        ('correction_max_gain_pct', 20.0),  # 纠错前的最大涨幅阈值（%），超过则视为正常获利回吐，不纠错
        
        # -- 二次确认信号参数 --
        ('confirmation_lookback', 5),  # "蓄势待发"信号的回看周期
        ('pocket_pivot_lookback', 11),  # 口袋支点信号的回看期
        ('breakout_proximity_pct', 0.03),  # "准突破"价格接近上轨容忍度(3%)
        ('pullback_from_peak_pct', 0.09),  # 从观察期高点可接受的最大回撤(9%)
        ('confirmation_min_trend_strength', 5.0),  # 二次确认的最小趋势强度（MA5近15日涨幅%）
        
        # ========== 第二部分：卖出与风险管理参数 ==========
        ('probation_period', 5),  # "蓄势待发"买入后的考察期天数
        ('initial_stake_pct', 0.90),  # 初始仓位（占总资金）
        ('atr_period', 14),  # ATR周期
        ('atr_multiplier', 2.2),  # ATR止损乘数
        ('atr_ceiling_multiplier', 3.6),  # 基于ATR的价格窗口乘数
        
        # ========== 第三部分：评分系统参数（不影响买卖决策） ==========
        # -- PSQ评分参数 --
        ('context_period', 7),  # PSQ情景定位的回看周期
        ('psq_pattern_weight', 1.0),  # PSQ形态分权重
        ('psq_momentum_weight', 1.0),  # PSQ动能分权重
        ('overheat_threshold', 2.10),  # 过热分数阈值
        ('psq_summary_period', 3),  # 持仓期初期分析的天数
        
        # -- VCP评分参数 --
        ('vcp_lookback', 60),  # VCP总回看期
        ('vcp_macro_ma_period', 90),  # VCP宏观环境MA周期
        ('vcp_absorption_lookback', 20),  # VCP供给吸收回看期
        ('vcp_absorption_zone_pct', 0.07),  # 供给区价格范围(7%)
        ('vcp_macro_roc_period', 20),  # 计算宏观MA斜率的回看期
        ('vcp_optimal_ma_roc', 1.03),  # 宏观MA最优斜率 (20日涨3%)
        ('vcp_max_ma_roc', 1.15),  # 宏观MA斜率上限
        ('vcp_optimal_price_pos', 1.05),  # 价格与MA最优位置 (高5%)
        ('vcp_max_price_pos', 1.30),  # 价格与MA位置上限
        ('vcp_squeeze_exponent', 1.5),  # 波动压缩分的非线性指数
        ('vcp_weight_macro', 0.35),  # 宏观环境分权重
        ('vcp_weight_squeeze', 0.40),  # 波动状态分权重
        ('vcp_weight_absorption', 0.25),  # 供给吸收分权重
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
        # VCP 4.0: 布林带宽度历史值，用于计算分位
        self.bbw_rank = bt.indicators.PctRank(self.bb_width, period=self.p.vcp_lookback)
        
        # V4.0: 前高指标（用于突破压力位评分）
        self.prior_high = bt.indicators.Highest(self.data.high, period=self.p.prior_high_lookback)

        # PSQ 3.1 指标: 动态高低点通道
        self.recent_high = bt.indicators.Highest(self.data.high, period=self.p.context_period)
        self.recent_low = bt.indicators.Lowest(self.data.low, period=self.p.context_period)
        # "蓄势待发"信号需要用到的近期最高价
        self.highest_close_confirm = bt.indicators.Highest(self.data.close, period=self.p.confirmation_lookback)

        # ATR指标，用于动态止损
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)

        # 新增：宏观环境判断均线
        self.ma_macro = bt.indicators.SMA(self.data, period=self.p.ma_macro_period)
        # VCP 4.0: 宏观趋势判断的长期均线
        self.vcp_macro_ma = bt.indicators.SMA(self.data, period=self.p.vcp_macro_ma_period)

        # 成交量均线
        self.volume_ma = bt.indicators.SMA(self.data.volume, period=self.p.volume_ma_period)

        # --- PSQ 2.0 辅助指标 ---
        self.ma5 = bt.indicators.SMA(self.data.close, period=5)
        self.ma10 = bt.indicators.SMA(self.data.close, period=10)

        # --- K线形态指标 (TA-Lib) - PSQ 4.1 扩展版 ---
        self.cdl_engulfing = bt.talib.CDLENGULFING(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_harami = bt.talib.CDLHARAMI(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_hammer = bt.talib.CDLHAMMER(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_shootingstar = bt.talib.CDLSHOOTINGSTAR(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_morningstar = bt.talib.CDLMORNINGSTAR(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_eveningstar = bt.talib.CDLEVENINGSTAR(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_piercing = bt.talib.CDLPIERCING(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_darkcloudcover = bt.talib.CDLDARKCLOUDCOVER(self.data.open, self.data.high, self.data.low,
                                                             self.data.close)
        self.cdl_doji = bt.talib.CDLDOJI(self.data.open, self.data.high, self.data.low, self.data.close)

        # --- 信号检查的配置 ---
        self.confirmation_signals = [
            ('coiled_spring', self.check_coiled_spring_conditions),
            ('pocket_pivot', self.check_pocket_pivot_conditions),
        ]

        # 状态跟踪
        self.order = None
        self.stop_price = 0
        self.highest_high_since_buy = 0
        self.buy_price = 0.0  # 记录买入价，用于计算涨幅
        # 新增：观察哨模式状态
        self.observation_mode = False
        self.observation_counter = 0
        self.sentry_source_signal = ""
        # 新增：价格接受度过滤器所需的状态
        self.sentry_base_price = 0
        self.sentry_highest_high = 0
        # 新增：用于精确计算信号日偏移量的索引
        self.signal_day_index = -1
        # 新增：蓄势待发信号的考察期状态
        self.coiled_spring_buy_pending = False
        self.in_coiled_spring_probation = False
        self.probation_counter = 0
        # --- 三速档位系统状态 ---
        self.pullback_wait_mode = False  # 是否在回踩等待模式
        self.pullback_wait_counter = 0  # 回踩等待计数器
        self.pullback_wait_signal = ""  # 记录触发回踩等待的信号名称
        # --- 止损纠错系统状态 ---
        self.recent_stop_loss_date = None  # 最近一次止损日期
        self.recent_stop_loss_price = 0.0  # 最近一次止损价格
        self.recent_stop_loss_gain_pct = 0.0  # 最近一次止损时的最大涨幅（%）
        self.is_correction_opportunity = False  # 是否识别为纠错机会
        self.correction_monitoring = False  # 是否在纠错监控模式
        self.correction_monitor_days = 0  # 纠错监控天数计数器
        # --- PSQ 2.0 状态 ---
        self.psq_scores = []
        self.psq_tracking_reason = None
        self.psq_signal_day_context = {}  # 存储信号日的关键数据
        self.last_overheat_score = 0.0  # 存储最近一次计算的过热分
        # -- 新增：PSQ分析数据存储 --
        self.all_trades_data = []
        self.current_observation_scores = []

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()} - {txt}')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                # 结束观察期评分，开始持仓期评分
                if self.psq_tracking_reason == '观察期':
                    self._stop_and_log_psq()
                self._start_psq_tracking('持仓期', self.datas[0])

                # 记录买入价（用于止损纠错判断）
                self.buy_price = order.executed.price
                
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
            # -- 新增：为PSQ分析报告收集数据 --
            trade_data = {
                'pnl': trade.pnlcomm,
                'obs_scores': self.current_observation_scores,
                'pos_scores': self.psq_scores.copy()  # 必须用copy，因为下面马上要清空
            }
            self.all_trades_data.append(trade_data)
            self.current_observation_scores = []  # 重置

            # 结束持仓期评分
            self._stop_and_log_psq()
            # 重置所有交易相关的状态
            self.stop_price = 0
            self.highest_high_since_buy = 0
            self.buy_price = 0.0  # 重置买入价
            self.in_coiled_spring_probation = False
            self.probation_counter = 0

    def next(self):
        # --- PSQ 2.0 评分 (每日) ---
        # 仅在信号日之后进行每日评分
        is_after_signal_day = self.psq_signal_day_context and \
                              self.datas[0].datetime.date(0) > self.psq_signal_day_context.get('date')

        if self.psq_tracking_reason and is_after_signal_day:
            psq_score = self._calculate_psq_score(self.datas[0])
            self.psq_scores.append(psq_score)
            # 可选：如果需要详细的每日日志，可以取消下面的注释
            # self.log(f"PSQ({self.psq_tracking_reason}) Day Score: {psq_score:.2f}")

        # 如果有挂单，不操作
        if self.order:
            return

        # --- 1. 持仓时：根据是否在考察期，执行不同的卖出逻辑 ---
        if self.position:
            # A. 如果在"蓄势待发"的考察期内
            if self.in_coiled_spring_probation:
                self.probation_counter -= 1

                # 检查是否通过考察: 最高价站上布林带上轨
                if self.data.high[0] > self.bband.lines.top[0]:
                    self.log('*** 考察期成功通过！切换为ATR跟踪止损 ***')
                    self.in_coiled_spring_probation = False
                    # 通过后，立即为ATR止损设置初始值
                    self.highest_high_since_buy = self.data.high[0]
                    self.stop_price = self.highest_high_since_buy - self.p.atr_multiplier * self.atr[0]
                    return  # 通过后，本轮逻辑结束，等待下一根K线

                # 检查是否考察失败(1): 跌破中轨生命线
                elif self.data.close[0] < self.bband.lines.mid[0]:
                    self.log('卖出信号: 考察期内跌破中轨，清仓')
                    self.order = self.close()

                # 检查是否考察失败(2): 考察期结束仍未突破
                elif self.probation_counter <= 0:
                    self.log('卖出信号: 考察期结束，未能突破上轨，清仓')
                    self.order = self.close()

                return  # 考察期内的逻辑结束

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
                    # 记录止损信息并启动纠错监控
                    if self.p.enable_stop_loss_correction:
                        self.recent_stop_loss_date = self.datas[0].datetime.date(0)
                        self.recent_stop_loss_price = self.stop_price  # 记录止损位，而不是当前收盘价
                        # 计算并记录最大涨幅（用于判断是否高位）
                        if self.buy_price > 0:
                            self.recent_stop_loss_gain_pct = ((self.highest_high_since_buy - self.buy_price) / self.buy_price) * 100
                        else:
                            self.recent_stop_loss_gain_pct = 0.0
                        self.correction_monitoring = True  # 启动纠错监控
                        self.correction_monitor_days = 0
                        self.log(f'*** 启动【止损纠错监控】模式（买入后最大涨幅: {self.recent_stop_loss_gain_pct:.1f}%） ***')
                    self.order = self.close()
                return  # 持仓时，完成止损检查后即可结束

        # --- 2. 空仓时：根据模式决定买入逻辑 ---
        # 最高优先级：纠错监控模式
        if self.correction_monitoring:
            self.correction_monitor_days += 1
            
            # 检查纠错条件
            if self._check_correction_opportunity_fast():
                # 满足纠错条件，立即买入
                current_price = self.data.close[0]
                vcp_score, vcp_grade = self._calculate_vcp_score()
                
                # 检查价格是否在合理区间
                if self.ma5[0] > 0:
                    ma5_lower_bound = self.ma5[0] * (1 + self.p.optimal_entry_zone_lower)
                    ma5_upper_bound = self.ma5[0] * (1 + self.p.optimal_entry_zone_upper)
                    
                    if ma5_lower_bound <= current_price <= ma5_upper_bound:
                        # 价格合理，直接买入
                        stake = self.broker.getvalue() * self.p.initial_stake_pct
                        size = int(stake / self.data.close[0])
                        if size > 0:
                            self.order = self.buy(size=size)
                            price_to_ma5_ratio = (current_price - self.ma5[0]) / self.ma5[0]
                            self.log(
                                f'买入信号: 止损纠错 (价格={current_price:.2f} 在MA5±区间内 ({price_to_ma5_ratio:+.1%}), '
                                f'VCP: {vcp_grade}, Score: {vcp_score:.2f})'
                            )
                            self.correction_monitoring = False
                            return
                    else:
                        # 价格过高，进入回踩等待
                        self.log(
                            f'*** 纠错确认但价格过高，进入【回踩等待】模式（{self.p.pullback_wait_period}天） [止损纠错] ***'
                        )
                        self.pullback_wait_mode = True
                        self.pullback_wait_counter = self.p.pullback_wait_period
                        self.pullback_wait_signal = '止损纠错'
                        self.correction_monitoring = False
                        return
            
            # 检查超时
            if self.correction_monitor_days > self.p.stop_loss_correction_window:
                self.log('*** 止损纠错监控期结束，未发现纠错机会 ***')
                self.correction_monitoring = False
            return
        
        if self.pullback_wait_mode:
            # --- 回踩等待模式 ---
            # 检查1：MA5是否掉头向下
            if self.ma5[0] < self.ma5[-1]:
                self.log(f'*** 回踩等待期内MA5掉头向下，放弃信号 ({self.pullback_wait_signal}) ***')
                self.pullback_wait_mode = False
                self._stop_and_log_psq()  # 结束观察期评分
                return
            
            # 检查2：是否出现回调
            if self.data.close[0] < self.data.close[-1]:
                # 回踩确认也需要检查最优买入区间（四舍五入避免浮点数精度问题）
                current_price = round(self.data.close[0], 2)
                if self.ma5[0] > 0:
                    ma5_lower_bound = round(self.ma5[0] * (1 + self.p.optimal_entry_zone_lower), 2)
                    ma5_upper_bound = round(self.ma5[0] * (1 + self.p.optimal_entry_zone_upper), 2)
                    
                    if current_price < ma5_lower_bound or current_price > ma5_upper_bound:
                        price_to_ma5_ratio = (current_price - self.ma5[0]) / self.ma5[0]
                        self.log(
                            f'回踩确认拒绝: 价格 {current_price:.2f} 不在MA5±区间内 '
                            f'({price_to_ma5_ratio:+.1%})，继续等待'
                        )
                        return  # 不买入，继续等待
                
                self.log(f'*** 回踩等待期内出现回调，发出买入信号 ({self.pullback_wait_signal}) ***')
                # 执行买入逻辑（使用标准仓位计算）
                vcp_score, vcp_grade = self._calculate_vcp_score()
                stake = self.broker.getvalue() * self.p.initial_stake_pct
                size = int(stake / self.data.close[0])
                if size > 0:
                    self.current_observation_scores = self.psq_scores.copy()
                    self.order = self.buy(size=size)
                    price_to_ma5_ratio = (current_price - self.ma5[0]) / self.ma5[0] if self.ma5[0] > 0 else 0
                    self.log(
                        f'买入信号: 回踩确认 (价格={current_price:.2f} 在MA5±区间内 ({price_to_ma5_ratio:+.1%}), '
                        f'VCP: {vcp_grade}, Score: {vcp_score:.2f})'
                    )
                self.pullback_wait_mode = False
                return
            
            # 检查3：超时
            self.pullback_wait_counter -= 1
            if self.pullback_wait_counter <= 0:
                self.log(f'*** 回踩等待期结束（{self.p.pullback_wait_period}天），未出现回调，放弃信号 ***')
                self.pullback_wait_mode = False
                self._stop_and_log_psq()  # 结束观察期评分
            return
        
        elif self.observation_mode:
            # 更新观察期内的最高价
            self.sentry_highest_high = max(self.sentry_highest_high, self.data.high[0])

            self._check_confirmation_signals()

            # 如果没有触发任何信号，则递减观察期计数器
            if not self.order and self.observation_counter > 0:
                self.observation_counter -= 1
                if self.observation_counter <= 0:
                    self.log('*** 观察期结束，未出现二次确认信号，解除观察模式 ***')
                    self._stop_and_log_psq()  # 结束观察期评分
                    self.observation_mode = False
        else:
            # --- 寻找初始突破信号(重构) ---
            is_volume_up = self.data.volume[0] > self.volume_ma[0]

            # 1. 定义两种突破形态
            is_strict_breakout = self.data.close[0] > self.bband.lines.top[0]

            is_quasi_breakout = (
                    self.data.high[0] > self.bband.lines.top[0] and
                    self.data.close[0] >= self.bband.lines.top[0] * (1 - self.p.breakout_proximity_pct)
            )

            # 必须放量，且至少满足一种突破形态
            if is_volume_up and (is_strict_breakout or is_quasi_breakout):

                # --- 环境分 V3.0: 双路径评估 ---
                # 路径一: 优先识别高质量的"盘整突破"
                is_consolidation = self._check_short_term_consolidation()
                if is_consolidation:
                    # 识别为盘整突破，直接给予B级，认可其形态价值
                    env_grade, env_score = 'B级(盘整突破)', 2
                else:
                    # 路径二: 对于其他"动能突破"，沿用严格的距离评分
                    # 价格相对长周期均线的比率
                    price_pos_ratio = self.data.close[0] / self.ma_macro[0] if self.ma_macro[0] > 0 else 0

                    if 1.0 < price_pos_ratio <= 1.10:
                        env_grade, env_score = 'A级(理想)', 3
                    elif 1.10 < price_pos_ratio <= 1.25:
                        env_grade, env_score = 'B级(趋势)', 2
                    elif 1.25 < price_pos_ratio <= 1.45:
                        env_grade, env_score = 'C级(追高)', 1
                    else:
                        env_grade, env_score = 'D级(超限)', 0

                bbw_range = self.highest_bbw[-1] - self.lowest_bbw[-1]
                squeeze_pct = (self.bb_width[-1] - self.lowest_bbw[-1]) / bbw_range if bbw_range > 1e-9 else 0
                if 0.05 < squeeze_pct <= 0.20:
                    squeeze_grade, squeeze_score = 'A级', 3
                elif squeeze_pct <= 0.05:
                    squeeze_grade, squeeze_score = 'B级', 2
                elif 0.20 < squeeze_pct <= 1.00:
                    squeeze_grade, squeeze_score = 'C级', 1
                else:
                    squeeze_grade, squeeze_score = 'D级', 0

                # --- 量能评分 V2.0: 引入"口袋支点"逻辑 ---
                # 1. 检查是否存在'口袋支点'特征：成交量能吸收近期所有抛压
                lookback = self.p.pocket_pivot_lookback
                highest_down_volume = 0
                is_pocket_pivot_volume = False
                if len(self.data.close) > lookback + 1:
                    for i in range(1, lookback + 1):
                        if self.data.close[-i] < self.data.close[-i - 1]:
                            highest_down_volume = max(highest_down_volume, self.data.volume[-i])
                    if self.data.volume[0] > highest_down_volume and highest_down_volume > 0:
                        is_pocket_pivot_volume = True

                # 2. 基于传统量比和口袋支点特征进行综合评分
                volume_ratio = self.data.volume[0] / self.volume_ma[0]

                if is_pocket_pivot_volume:
                    # 口袋支点是高质量信号，至少B级。如果量比也优秀，则为A级。
                    if volume_ratio > 2.5:
                        volume_grade, volume_score = 'A级(口袋支点+)', 3
                    else:
                        volume_grade, volume_score = 'B级(口袋支点)', 2
                elif 3.0 < volume_ratio <= 5.0:
                    volume_grade, volume_score = 'A级(理想)', 3
                elif 1.5 < volume_ratio <= 3.0:
                    volume_grade, volume_score = 'B级(优秀)', 2
                elif 1.1 < volume_ratio <= 1.5:
                    volume_grade, volume_score = 'C级(合格)', 1
                else:
                    grade_reason = "过高" if volume_ratio > 5.0 else "过低"
                    volume_grade, volume_score = f'D级({grade_reason})', 0

                # --- V4.0: 前高突破评分（可选） ---
                prior_high_score = 0
                prior_high_grade = 'N/A'
                prior_high_info = ''
                
                if self.p.enable_prior_high_score:
                    # 使用"往前推N天"的前高，避免刚突破立即成为新前高
                    # 例如：排除最近5天，则使用6天前的"过去80天最高价"
                    offset = self.p.prior_high_exclude_recent + 1
                    
                    # 边界检查：确保有足够的历史数据
                    if len(self.prior_high) > offset and len(self.data.high) > offset + self.p.prior_high_lookback:
                        prior_high_value = self.prior_high[-offset]
                        current_price = self.data.close[0]
                        
                        # 查找前高实际发生的日期（在过去80天内找到最高价对应的日期）
                        prior_high_date = None
                        for i in range(offset, offset + self.p.prior_high_lookback):
                            if self.data.high[-i] == prior_high_value:
                                prior_high_date = self.data.datetime.date(-i)
                                break
                        
                        if prior_high_value > 0:
                            price_to_high_ratio = current_price / prior_high_value
                            
                            # 判断是否突破压力位
                            if price_to_high_ratio > (1 + self.p.prior_high_upper_threshold):
                                prior_high_grade = '突破'
                                prior_high_score = 1
                            elif price_to_high_ratio < (1 - self.p.prior_high_lower_threshold):
                                prior_high_grade = '受阻'
                                prior_high_score = -1
                            else:
                                prior_high_grade = '临界'
                                prior_high_score = 0
                            
                            # 生成日志信息
                            if prior_high_date:
                                prior_high_info = f"距前高:{(price_to_high_ratio-1)*100:+.1f}%,基准:{prior_high_date.strftime('%m-%d')}"
                            else:
                                prior_high_info = f"距前高:{(price_to_high_ratio-1)*100:+.1f}%"

                total_score = env_score + squeeze_score + volume_score + prior_high_score

                # --- 调试日志 ---
                if self.p.debug:
                    debug_msg = (
                        f"[debug]信号候选日: "
                        f"环境(分:{env_score},级:{env_grade}), "
                        f"压缩(分:{squeeze_score},级:{squeeze_grade},pct:{squeeze_pct:.0%}), "
                        f"量能(分:{volume_score},级:{volume_grade},rat:{volume_ratio:.1f}x)"
                    )
                    if self.p.enable_prior_high_score:
                        debug_msg += f", 前高(分:{prior_high_score:+d},级:{prior_high_grade},{prior_high_info})"
                    debug_msg += f" | 总分: {total_score}"
                    self.log(debug_msg)

                # --- 决策逻辑：结合补偿机制 ---
                trigger_observation = False
                breakout_type = ""

                if total_score >= 6:  # 至少是B级信号
                    if is_strict_breakout:
                        trigger_observation = True
                        breakout_type = "标准突破"
                    elif is_quasi_breakout:
                        # 对于"准突破"，需要额外的补偿条件
                        if squeeze_score == 3 or volume_score == 3:
                            trigger_observation = True
                            breakout_type = "准突破(已补偿)"

                if trigger_observation:
                    if total_score >= 8:
                        overall_grade = '【A+级】'
                    elif total_score >= 6:
                        overall_grade = '【B级】'
                    else:
                        overall_grade = '【C级】'  # 理论上不会到这里

                    log_msg = (
                        f'突破信号: {overall_grade} - {breakout_type} '
                        f'(环境:{env_grade}, '
                        f'压缩:{squeeze_grade}({squeeze_pct:.0%}), '
                        f'量能:{volume_grade}({volume_ratio:.1f}x)'
                    )
                    if self.p.enable_prior_high_score and prior_high_info:
                        log_msg += f', 前高:{prior_high_grade}({prior_high_info})'
                    log_msg += ')'
                    self.log(log_msg)

                    # --- 三速档位系统：检查是否走快速通道 ---
                    is_fast_track = False
                    if self.p.enable_fast_track and self.ma10[0] > 0 and self.ma5[0] > 0:
                        ma5_ma10_ratio = self.ma5[0] / self.ma10[0]
                        is_strong_trend = ma5_ma10_ratio > self.p.fast_track_ma5_ma10_ratio
                        
                        # 快速通道也需要检查最优买入区间（四舍五入避免浮点数精度问题）
                        current_price = round(self.data.close[0], 2)
                        ma5_lower_bound = round(self.ma5[0] * (1 + self.p.optimal_entry_zone_lower), 2)
                        ma5_upper_bound = round(self.ma5[0] * (1 + self.p.optimal_entry_zone_upper), 2)
                        is_price_in_zone = ma5_lower_bound <= current_price <= ma5_upper_bound
                        
                        # 调试日志
                        if self.p.debug:
                            self.log(
                                f'[快速通道] MA5/MA10={ma5_ma10_ratio:.3f}(需>{self.p.fast_track_ma5_ma10_ratio}), '
                                f'价格={current_price:.2f}, 区间=[{ma5_lower_bound:.2f}, {ma5_upper_bound:.2f}], '
                                f'强势={is_strong_trend}, 价格合理={is_price_in_zone}'
                            )
                        
                        if is_strong_trend and is_price_in_zone:
                            is_fast_track = True
                            price_to_ma5_ratio = (current_price - self.ma5[0]) / self.ma5[0]
                            self.log(
                                f'*** 快速通道触发 (MA5/MA10={ma5_ma10_ratio:.3f}, '
                                f'价格={current_price:.2f} 在MA5±区间内 ({price_to_ma5_ratio:+.1%})) ***'
                            )
                            
                            # 记录信号日索引（用于VCP计算）
                            self.signal_day_index = len(self.data) - 1
                            # 开始PSQ评分
                            self._start_psq_tracking('观察期', self.datas[0])
                            
                            # 立即发出买入信号
                            vcp_score, vcp_grade = self._calculate_vcp_score()
                            stake = self.broker.getvalue() * self.p.initial_stake_pct
                            size = int(stake / self.data.close[0])
                            if size > 0:
                                self.current_observation_scores = self.psq_scores.copy()
                                self.order = self.buy(size=size)
                                self.log(f'买入信号: 快速通道{overall_grade} (VCP: {vcp_grade}, Score: {vcp_score:.2f})')
                    
                    # 如果不走快速通道，则进入标准观察期
                    if not is_fast_track:
                        self.log(f'*** 触发【突破观察哨】模式，观察期 {self.p.observation_period} 天 ***')
                        self.observation_mode = True
                        self.observation_counter = self.p.observation_period
                        self.sentry_source_signal = f"{overall_grade} @ {self.datas[0].datetime.date(0)}"
                        # 记录价格过滤器所需的状态
                        self.sentry_base_price = self.data.open[0]
                        self.sentry_highest_high = self.data.high[0]
                        # 新增: 精确记录信号日的索引
                        self.signal_day_index = len(self.data) - 1
                        # 开始PSQ评分 - 从信号日当天开始
                        self._start_psq_tracking('观察期', self.datas[0])

    def _check_confirmation_signals(self):
        """
        统一检查所有二次确认信号。 V2.0 优化日志逻辑
        1. 先找出当天所有满足条件的信号。
        2. 再对这些信号统一应用过滤器。
        3. 如果通过，则按优先级（coiled_spring > pocket_pivot）执行交易。
        """
        # 步骤1: 找出当天所有活跃的信号
        active_signals = [
            signal_name for signal_name, check_function in self.confirmation_signals
            if check_function()
        ]

        if not active_signals:
            return

        # 步骤2: 对活跃信号统一应用过滤器
        signal_names_str = ", ".join(active_signals)

        # 过滤器1: 动态价格接受窗口
        price_ceiling_from_peak_atr = self.sentry_highest_high + (self.p.atr_ceiling_multiplier * self.atr[0])
        price_floor_from_peak_pct = self.sentry_highest_high * (1 - self.p.pullback_from_peak_pct)
        current_price = self.data.close[0]

        if current_price > price_ceiling_from_peak_atr:
            self.log(
                f"信号拒绝({signal_names_str}): 价格 {current_price:.2f} 过高, "
                f"> 观察期高点 {self.sentry_highest_high:.2f} + {self.p.atr_ceiling_multiplier}*ATR "
                f"({price_ceiling_from_peak_atr:.2f})"
            )
            return

        if current_price < price_floor_from_peak_pct:
            self.log(
                f"信号拒绝({signal_names_str}): 价格 {current_price:.2f} 从观察期高点 {self.sentry_highest_high:.2f} 回撤过深, "
                f"< 止损线 {price_floor_from_peak_pct:.2f}"
            )
            return

        # 过滤器2: 过热分数
        if self.last_overheat_score > self.p.overheat_threshold:
            self.log(
                f"信号拒绝({signal_names_str}): 过热分数 {self.last_overheat_score:.2f} "
                f"> 阈值 {self.p.overheat_threshold}"
            )
            return

        # 过滤器3: 趋势强度 - 过滤横盘震荡的二次确认信号
        lookback = min(15, len(self.ma5))  # 检查MA5近15日涨幅
        if lookback > 1:
            ma5_trend_pct = ((self.ma5[0] - self.ma5[-lookback+1]) / self.ma5[-lookback+1]) * 100
            if ma5_trend_pct < self.p.confirmation_min_trend_strength:
                self.log(
                    f"信号拒绝({signal_names_str}): MA5趋势不足 {ma5_trend_pct:.1f}% "
                    f"< 阈值 {self.p.confirmation_min_trend_strength:.1f}%，属于横盘震荡"
                )
                return

        # 所有前置过滤器通过，计算VCP分数作为参考，不作为决策依据
        vcp_score, vcp_grade = self._calculate_vcp_score()

        # 步骤3: 所有过滤器通过，按优先级执行交易
        # active_signals中的顺序由self.confirmation_signals定义，默认coiled_spring优先
        signal_to_execute = active_signals[0]

        log_msg_map = {
            'coiled_spring': f'突破信号:【蓄势待发】(源信号: {self.sentry_source_signal})',
            'pocket_pivot': f'突破信号:【口袋支点】(源信号: {self.sentry_source_signal})'
        }
        log_msg_base = log_msg_map.get(signal_to_execute, '未知确认信号')
        # 信号日志回归简洁，不再包含结构分
        self.log(log_msg_base)

        # --- 止损纠错判断：检查是否是纠错机会 ---
        self.is_correction_opportunity = self._check_stop_loss_correction_opportunity()
        
        # --- 三速档位系统：检查价格位置，决定标准通道还是缓冲通道 ---
        if self.ma5[0] > 0:
            # 四舍五入避免浮点数精度问题
            current_price = round(current_price, 2)
            price_to_ma5_ratio = (current_price - self.ma5[0]) / self.ma5[0]
            ma5_lower_bound = round(self.ma5[0] * (1 + self.p.optimal_entry_zone_lower), 2)
            ma5_upper_bound = round(self.ma5[0] * (1 + self.p.optimal_entry_zone_upper), 2)
            
            # 价格过高，进入缓冲通道（纠错机会也适用）
            if current_price > ma5_upper_bound or self.is_correction_opportunity:
                # 纠错机会标记
                correction_tag = ' [止损纠错]' if self.is_correction_opportunity else ''
                self.log(
                    f'*** 价格 {current_price:.2f} 距MA5 {self.ma5[0]:.2f} 过高 ({price_to_ma5_ratio:+.1%})，'
                    f'进入【回踩等待】模式（{self.p.pullback_wait_period}天）{correction_tag} ***'
                )
                self.pullback_wait_mode = True
                self.pullback_wait_counter = self.p.pullback_wait_period
                self.pullback_wait_signal = log_msg_base
                # 注意：不停止PSQ评分，继续跟踪
                self.observation_mode = False
                return
            # 价格过低（理论上不太可能，但也做判断）
            elif current_price < ma5_lower_bound:
                self.log(
                    f'信号拒绝({signal_names_str}): 价格 {current_price:.2f} '
                    f'距MA5 {self.ma5[0]:.2f} 过低 ({price_to_ma5_ratio:+.1%})'
                )
                return
            else:
                # 价格在最优区间内，正常买入
                self.log(f'价格位置合理：{current_price:.2f} 在MA5±区间内 ({price_to_ma5_ratio:+.1%})')

        stake = self.broker.getvalue() * self.p.initial_stake_pct
        size = int(stake / self.data.close[0])
        if size > 0:
            # -- 新增：为PSQ分析报告捕获观察期分数 --
            self.current_observation_scores = self.psq_scores.copy()
            self.order = self.buy(size=size)
            # 只有"蓄势待发"信号需要进入考察期
            if signal_to_execute == 'coiled_spring':
                self.coiled_spring_buy_pending = True

        # 注意：此处不停止PSQ，因为买单可能不会立即成交。
        # 评分的停止和切换将在notify_order中处理
        self.observation_mode = False
        log_suffix = "发出" if signal_to_execute == 'coiled_spring' else "执行"
        # 按要求将VCP信息添加到此日志行
        self.log(
            f'*** 二次确认信号已{log_suffix}，解除观察模式，'
            f'当前过热分: {self.last_overheat_score:.2f} '
            f'(VCP 参考: {vcp_grade}, Score: {vcp_score:.2f}) ***'
        )

    def _check_correction_opportunity_fast(self):
        """
        快速纠错检查（用于纠错监控模式，每日执行）
        
        判断标准：
        1. 收盘价重新站上止损价（证明止损错了）
        2. 均线形态完好（MA5 > MA10，收盘价 > MA10）
        3. MA5有上涨趋势
        4. 止损前涨幅不能过大（避免高位回调）
        
        Returns:
            bool: True表示应该立即纠错买入
        """
        if not self.p.enable_stop_loss_correction:
            return False
        
        current_price = self.data.close[0]
        
        # 关键条件：收盘价重新站上止损价
        if current_price < self.recent_stop_loss_price:
            return False
        
        # 新增：高位过滤 - 如果止损前涨幅过大，不应纠错
        if self.recent_stop_loss_gain_pct > self.p.correction_max_gain_pct:
            if self.p.debug:
                self.log(
                    f'[纠错检查] 止损前已大涨 {self.recent_stop_loss_gain_pct:.1f}%，'
                    f'超过阈值 {self.p.correction_max_gain_pct:.1f}%，属于高位回调不应纠错'
                )
            return False
        
        # 检查均线形态
        if self.ma5[0] <= self.ma10[0]:
            if self.p.debug:
                self.log(f'[纠错检查] 均线死叉: MA5={self.ma5[0]:.2f} <= MA10={self.ma10[0]:.2f}')
            return False
        
        if current_price <= self.ma10[0]:
            if self.p.debug:
                self.log(f'[纠错检查] 收盘跌破MA10: {current_price:.2f} <= {self.ma10[0]:.2f}')
            return False
        
        # 检查MA5上涨趋势
        lookback = min(3, len(self.ma5))  # 快速检查，只看3天
        if lookback > 1:
            ma5_change_pct = ((self.ma5[0] - self.ma5[-lookback+1]) / self.ma5[-lookback+1]) * 100
            if ma5_change_pct < self.p.correction_trend_min_strength:
                if self.p.debug:
                    self.log(f'[纠错检查] MA5涨幅不足: {ma5_change_pct:.1f}% < {self.p.correction_trend_min_strength:.1f}%')
                return False
        
        # 所有条件满足
        self.log(
            f'*** 识别止损纠错机会（快速）：收盘{current_price:.2f}站上止损位{self.recent_stop_loss_price:.2f}，'
            f'均线形态完好(MA5/MA10={self.ma5[0]/self.ma10[0]:.3f})，止损前涨幅{self.recent_stop_loss_gain_pct:.1f}% ***'
        )
        return True
    
    def _check_stop_loss_correction_opportunity(self):
        """
        检查是否是止损纠错机会（用于二次确认信号时的判断）
        
        判断标准：
        1. 近N天内有过止损
        2. 均线形态未破坏（MA5 > MA10，收盘价 > MA10）
        3. MA5有上涨趋势（最小涨幅阈值）
        
        Returns:
            bool: True表示识别为纠错机会
        """
        if not self.p.enable_stop_loss_correction:
            return False
        
        if self.recent_stop_loss_date is None:
            return False
        
        # 检查止损日期是否在窗口内
        current_date = self.datas[0].datetime.date(0)
        days_since_stop = (current_date - self.recent_stop_loss_date).days
        
        if days_since_stop > self.p.stop_loss_correction_window:
            if self.p.debug:
                self.log(f'[纠错检查] 时间窗口超限: 止损后{days_since_stop}天 > {self.p.stop_loss_correction_window}天')
            return False
        
        # 检查均线形态是否完好
        if self.ma5[0] <= self.ma10[0]:
            if self.p.debug:
                self.log(f'[纠错检查] 均线死叉: MA5={self.ma5[0]:.2f} <= MA10={self.ma10[0]:.2f}')
            return False  # MA5死叉MA10，趋势破坏
        
        if self.data.close[0] <= self.ma10[0]:
            if self.p.debug:
                self.log(f'[纠错检查] 收盘跌破MA10: {self.data.close[0]:.2f} <= {self.ma10[0]:.2f}')
            return False  # 收盘价跌破MA10，中期支撑破坏
        
        # 检查MA5上涨趋势强度（近N日涨幅）
        lookback = min(self.p.stop_loss_correction_window, len(self.ma5))
        if lookback > 1:
            ma5_change_pct = ((self.ma5[0] - self.ma5[-lookback+1]) / self.ma5[-lookback+1]) * 100
            if ma5_change_pct < self.p.correction_trend_min_strength:
                if self.p.debug:
                    self.log(f'[纠错检查] MA5涨幅不足: {ma5_change_pct:.1f}% < {self.p.correction_trend_min_strength:.1f}%')
                return False  # MA5上涨趋势不足
        
        # 新增：高位过滤 - 如果止损前涨幅过大，不应纠错
        if self.recent_stop_loss_gain_pct > self.p.correction_max_gain_pct:
            self.log(
                f'信号拒绝(止损纠错): 止损前已大涨 {self.recent_stop_loss_gain_pct:.1f}%，'
                f'超过阈值 {self.p.correction_max_gain_pct:.1f}%，属于高位回调不应纠错'
            )
            return False
        
        # 所有条件满足，识别为纠错机会
        self.log(
            f'*** 识别止损纠错机会：近期止损({self.recent_stop_loss_date.strftime("%m-%d")})，'
            f'均线形态完好(MA5/MA10={self.ma5[0]/self.ma10[0]:.3f}，MA5上涨{ma5_change_pct:.1f}%)，'
            f'止损前涨幅{self.recent_stop_loss_gain_pct:.1f}% ***'
        )
        return True

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

    def check_pocket_pivot_conditions(self):
        """
        检查"口袋支点"信号。
        这是一种基于成交量的早期信号，用于识别机构吸筹。
        它寻找成交量远超近期所有抛售压力的一天。
        """
        # 条件1: 价格必须处于布林带中轨之上，表明处于短期强势区
        if self.data.close[0] < self.bband.lines.mid[0]:
            return False

        # 条件2: 必须是上涨日 (收盘价高于前一日收盘价)
        if self.data.close[0] <= self.data.close[-1]:
            return False

        # 条件3: 当日成交量必须大于过去N日内所有下跌日的成交量最大值
        lookback = self.p.pocket_pivot_lookback
        highest_down_volume = 0
        # The loop goes from bar t-1 to t-lookback
        for i in range(1, lookback + 1):
            # If it was a down day (close < previous close)
            if self.data.close[-i] < self.data.close[-i - 1]:
                highest_down_volume = max(highest_down_volume, self.data.volume[-i])

        return self.data.volume[0] > highest_down_volume

    def _check_short_term_consolidation(self):
        """检查是否存在高位横盘/微升的"蓄势"形态。"""
        lookback = self.p.consolidation_lookback

        # 确保有足够的数据
        if len(self.ma10) < lookback + 1 or len(self.ma5) < lookback + 1:
            return False

        # 检查1: 盘整期内，短期均线(ma10)不能过快上涨
        if self.ma10[-lookback] <= 0:  # 避免除零
            return False
        ma_slope = self.ma10[0] / self.ma10[-lookback]
        if ma_slope > self.p.consolidation_ma_max_slope:
            return False

        # 检查2: 盘整期内，5日线和10日线必须高度贴合
        for i in range(1, lookback + 1):
            if self.ma10[-i] <= 0:  # 避免除零
                return False
            proximity = abs(self.ma5[-i] - self.ma10[-i]) / self.ma10[-i]
            if proximity > self.p.consolidation_ma_proximity_pct:
                return False

        return True

    def _calculate_vcp_score(self):
        """
        VCP 4.1 "中庸之道": 计算VCP分数。
        - 核心逻辑: 引入"过犹不及"的平衡思想，对各维度进行非线性评分。
          分数在"最优状态"达到顶峰，在过高或过低时均会衰减。
        """

        def _get_balanced_score(current_val, optimal_val, lower_bound, upper_bound):
            """
            计算一个0-100的平衡分数。
            - 在 optimal_val 处得分为 100。
            - 在 lower_bound 和 upper_bound 处得分为 0。
            - 在区间之间线性递减。
            """
            if not (lower_bound <= optimal_val <= upper_bound): return 0
            if current_val < lower_bound or current_val > upper_bound: return 0

            if current_val >= optimal_val:
                # 在 optimal 和 upper_bound 之间
                range_size = upper_bound - optimal_val
                if range_size <= 1e-9: return 100 if current_val == optimal_val else 0
                score = 100 * (1 - (current_val - optimal_val) / range_size)
            else:
                # 在 lower_bound 和 optimal 之间
                range_size = optimal_val - lower_bound
                if range_size <= 1e-9: return 100 if current_val == optimal_val else 0
                score = 100 * (1 - (optimal_val - current_val) / range_size)

            return score

        if self.signal_day_index == -1: return 0, "N/A"

        # --- 维度1: 宏观环境分 (0-100分) ---
        macro_score = 0
        ma_value = self.vcp_macro_ma[0]
        if ma_value > 0 and len(self.vcp_macro_ma) > self.p.vcp_macro_roc_period:
            # a. 价格位置 vs MA (过高则危险)
            price_pos_ratio = self.data.close[0] / ma_value
            pos_score = _get_balanced_score(
                price_pos_ratio,
                self.p.vcp_optimal_price_pos,
                1.0,  # lower bound: 价格至少要在MA之上
                self.p.vcp_max_price_pos
            )

            # b. MA斜率 (Rate of Change) (过陡则危险)
            ma_prev = self.vcp_macro_ma[-self.p.vcp_macro_roc_period]
            ma_roc = ma_value / ma_prev if ma_prev > 0 else 1.0
            trend_score = _get_balanced_score(
                ma_roc,
                self.p.vcp_optimal_ma_roc,
                1.0,  # lower bound: 趋势至少要持平
                self.p.vcp_max_ma_roc
            )

            # c. 结合位置和趋势
            macro_score = pos_score * 0.5 + trend_score * 0.5

        macro_str = f"Macro({int(macro_score)})"

        # --- 维度2: 波动状态分 (0-100分) ---
        # 使用布林带宽度百分比排名(PctRank)指标
        bbw_percentile = self.bbw_rank[0]  # 值在0.0到1.0之间
        # 使用指数使曲线非线性，更奖励极端的压缩
        squeeze_score = ((1.0 - bbw_percentile) ** self.p.vcp_squeeze_exponent) * 100
        squeeze_score = max(0, min(100, squeeze_score))  # 确保在0-100范围内
        squeeze_str = f"Sqz({int(squeeze_score)})"

        # --- 维度3: 供给吸收分 (0-100分) - 逻辑保持不变 ---
        absorption_score = 50  # 中性分50
        try:
            days_since_signal = (len(self.data) - 1) - self.signal_day_index
            lookback = self.p.vcp_absorption_lookback
            start_offset = days_since_signal + 1
            end_offset = start_offset + lookback

            if len(self.data) < end_offset:
                raise IndexError

            recent_highs = [self.data.high[-j] for j in range(start_offset, end_offset)]

            if recent_highs:
                high_water_mark = max(recent_highs)
                absorption_zone_floor = high_water_mark * (1 - self.p.vcp_absorption_zone_pct)

                test_events = []
                for i in range(start_offset, end_offset):
                    if self.data.high[-i] >= absorption_zone_floor:
                        day_open = self.data.open[-i]
                        day_close = self.data.close[-i]
                        day_high = self.data.high[-i]
                        day_low = self.data.low[-i]
                        day_vol = self.data.volume[-i]
                        vol_ma = self.volume_ma[-i]

                        candle_range = day_high - day_low if (day_high - day_low) > 1e-9 else 1
                        close_pos = ((day_close - day_low) / candle_range) * 2 - 1
                        vol_ratio = day_vol / vol_ma if vol_ma > 0 else 1

                        event_score = 0
                        if close_pos > 0.5:  # 收阳
                            event_score += 2 if vol_ratio < 0.8 else 1  # 缩量收阳加分更多
                        elif close_pos < -0.5:  # 收阴
                            event_score -= 2 if vol_ratio > 1.2 else 1  # 放量收阴减分更多
                        test_events.append(event_score)

                if test_events:
                    raw_score = sum(test_events) / len(test_events)
                    # 将平均事件分(-2到+2)映射到0-100分
                    absorption_score = 50 + (raw_score / 2) * 50
                    absorption_score = max(0, min(100, absorption_score))

        except (IndexError, ValueError):
            absorption_score = 50  # 出错则给中性分

        absorp_str = f"Abs({int(absorption_score)})"

        # --- 最终加权总分 ---
        final_score = (macro_score * self.p.vcp_weight_macro +
                       squeeze_score * self.p.vcp_weight_squeeze +
                       absorption_score * self.p.vcp_weight_absorption)

        # 转换为0-5的范围，以便与旧版兼容和日志统一
        final_score_scaled = (final_score / 100) * 5
        details_str = f"{macro_str},{squeeze_str},{absorp_str}"

        if self.p.debug:
            self.log(
                f"[vcp_debug] VCP Analysis: {details_str} | "
                f"Scores: macro({macro_score:.0f}), sqz({squeeze_score:.0f}), abs({absorption_score:.0f}) | "
                f"Weighted Final: {final_score:.2f} (Scaled: {final_score_scaled:.2f})"
            )

        grade_map = {5: "A+", 4: "A", 3: "B", 2: "C", 1: "D"}
        grade = grade_map.get(round(final_score_scaled), "F")

        return final_score_scaled, f"VCP-{grade}"

    # --- PSQ 评分系统 ---
    def _start_psq_tracking(self, reason, data):
        """开始一个新的PSQ评分周期，并立即对当天（信号日/入场日）评分。"""
        self.psq_scores = []
        self.psq_tracking_reason = reason

        # 捕获信号日/入场日的上下文
        self.psq_signal_day_context = {
            'date': data.datetime.date(0),
            'open': data.open[0],
            'high': data.high[0],
            'low': data.low[0],
            'close': data.close[0],
            'volume': data.volume[0],
            'mid_price': (data.open[0] + data.close[0]) / 2
        }
        self.log(f'*** PSQ评分系统已激活，原因: {reason} ***')

        # 立即对激活当天进行评分
        day_0_score = self._calculate_psq_score(data)
        self.psq_scores.append(day_0_score)
        self.log(f"PSQ({reason})激活日得分: {day_0_score:.2f}")

    def _stop_and_log_psq(self):
        """结束当前的PSQ评分周期并记录聚合日志"""
        if not self.psq_tracking_reason:
            return

        total_score = sum(self.psq_scores)
        avg_score = total_score / len(self.psq_scores) if self.psq_scores else 0
        psq_scores_formatted = [round(s, 2) for s in self.psq_scores]

        log_msg = (
            f"PSQ报告({self.psq_tracking_reason}): "
            f"累计总分: {total_score:.2f}, "
            f"日均分: {avg_score:.2f}, "
            f"持续天数: {len(self.psq_scores)}, "
            f"每日得分: {psq_scores_formatted}"
        )
        self.log(log_msg)
        # 重置状态
        self.psq_scores = []
        self.psq_tracking_reason = None
        self.psq_signal_day_context = {}

    def _get_kline_pattern_score(self, data):
        """
        PSQ 4.1: 形态优先 - 识别关键的反转形态并给予分级权重分。
        核心逻辑: 在什么趋势下，出现了什么形态。
        """
        # 定义近期趋势 (基于过去2天的收盘价)
        is_recent_up_trend = data.close[0] > data.close[-2]
        is_recent_down_trend = data.close[0] < data.close[-2]

        # --- 看跌形态 (Bearish Patterns) ---
        if is_recent_up_trend:
            # 强反转: -3.0
            if self.cdl_eveningstar[0] != 0 or self.cdl_engulfing[0] < 0:
                return -3.0
            # 中反转: -2.0
            if self.cdl_darkcloudcover[0] != 0 or self.cdl_harami[0] < 0 or self.cdl_shootingstar[0] != 0:
                return -2.0
            # 弱/警告信号: -1.0
            if self.cdl_doji[0] != 0:
                return -1.0

        # --- 看涨形态 (Bullish Patterns) ---
        elif is_recent_down_trend:
            # 强反转: +3.0
            if self.cdl_morningstar[0] != 0 or self.cdl_engulfing[0] > 0:
                return 3.0
            # 中反转: +2.0
            if self.cdl_piercing[0] != 0 or self.cdl_harami[0] > 0 or self.cdl_hammer[0] != 0:
                return 2.0
            # 弱/警告信号: +1.0
            if self.cdl_doji[0] != 0:
                return 1.0

        return 0.0  # 无趋势或无形态

    def _calculate_psq_score(self, data):
        """
        计算当日的PSQ总分。
        - 形态分: 来自 _get_kline_pattern_score。
        - 动能分: 代表当日价格与成交量的综合表现。
        - 新增：过热分，用于识别观察期内的追高风险。
        """
        # --- 1. 形态分 (Pattern Score) ---
        pattern_score = self._get_kline_pattern_score(data)

        # --- 2. 动能分 (PSQ 3.1: Context-aware Momentum Score) ---
        # a. 计算基础K线特征
        candle_range = data.high[0] - data.low[0]
        if candle_range < 1e-9: candle_range = 1e-9
        entity_ratio = (data.close[0] - data.open[0]) / candle_range
        lower_shadow = (min(data.open[0], data.close[0]) - data.low[0]) / candle_range
        upper_shadow = (data.high[0] - max(data.open[0], data.close[0])) / candle_range

        # b. 情景定位 (Context Positioning)
        channel_range = self.recent_high[0] - self.recent_low[0]
        price_position_pct = (data.close[0] - self.recent_low[0]) / channel_range if channel_range > 1e-9 else 1.0

        # c. 结合情景计算日内力量
        # 实体分是基础
        power = entity_ratio * 2.0
        # 下影线：在低位是强支撑信号，在高位意义不大
        power += lower_shadow * (2.0 * (1 - price_position_pct))  # 低位时权重接近2, 高位时接近0
        # 上影线：在高位是强阻力信号，在低位可能是试探，惩罚较轻
        power -= upper_shadow * (1.0 + price_position_pct)  # 低位时权重接近-1, 高位时接近-2
        intraday_power = power

        # d. 量能强度
        volume_strength = (data.volume[0] / self.volume_ma[0] - 1) if self.volume_ma[0] > 0 else 0

        momentum_score = intraday_power + volume_strength

        # --- 3. 新增：过热分 (Overheat Score) ---
        overheat_score = 0.0
        # 只在观察期内计算
        if self.psq_tracking_reason == '观察期':
            signal_context = self.psq_signal_day_context
            days_since_signal = len(self.psq_scores)

            if signal_context and days_since_signal > 0:
                # a. 计算涨速指标 (Velocity Metric), 综合考虑"日均涨速"和"单日涨速"
                total_rise_pct = (data.close[0] - signal_context['close']) / signal_context['close']
                avg_velocity = total_rise_pct / days_since_signal
                single_day_rise_pct = (data.close[0] - data.close[-1]) / data.close[-1] if data.close[-1] > 0 else 0

                # 取两者中更快的速度作为风险衡量的基础，并放大10倍
                velocity_metric = max(avg_velocity, single_day_rise_pct) * 10

                # b. 结合犹豫信号(上影线)进行放大，计算最终过热分
                # 只有当存在上涨时才计算过热分
                if velocity_metric > 0:
                    # 上影线越长(0~1)，放大效应越强(1~3倍)
                    overheat_score = velocity_metric * (1 + upper_shadow * 3)

        # --- 合计总分 (PSQ 4.2: 应用权重) ---
        total_score = (pattern_score * self.p.psq_pattern_weight) + \
                      (momentum_score * self.p.psq_momentum_weight)

        # --- 调试日志 ---
        # 仅在观察期时，打印详细的PSQ分数构成
        if self.p.debug and self.psq_tracking_reason == '观察期':
            self.log(
                f"[psq_debug] "
                f"pat:{pattern_score:.2f}, "
                f"power:{intraday_power:.2f}, "
                f"vol:{volume_strength:.2f}, "
                f"overheat:{overheat_score:.2f} "
                f"-> total:{total_score:.2f}"
            )

        self.last_overheat_score = overheat_score  # 存储过热分，供过滤器使用
        return total_score

    def stop(self):
        """在回测结束时调用，用于最终的统计分析。"""
        if self.p.debug:
            self._analyze_and_log_psq_summary()

    def _analyze_and_log_psq_summary(self):
        """
        在回测结束后，分析所有交易的PSQ数据，并生成一份指导性报告。
        """
        if not self.all_trades_data:
            return

        print('\n' + '=' * 60)
        print(f'PSQ 特征分析报告: {self.data._name}')
        print('=' * 60)

        all_pnls = [t['pnl'] for t in self.all_trades_data]

        # 动态计算"平庸"交易的界限
        if len(all_pnls) >= 3:
            pnl_mean = sum(all_pnls) / len(all_pnls)
            pnl_variance = sum([(p - pnl_mean) ** 2 for p in all_pnls]) / len(all_pnls)
            pnl_std_dev = pnl_variance ** 0.5
            significance_threshold = 0.25 * pnl_std_dev
        else:
            significance_threshold = 0  # 交易太少，无法计算有意义的统计，退化为简单盈亏

        winners = [t for t in self.all_trades_data if t['pnl'] > significance_threshold]
        losers = [t for t in self.all_trades_data if t['pnl'] < -significance_threshold]
        mediocre = [t for t in self.all_trades_data if -significance_threshold <= t['pnl'] <= significance_threshold]

        def _calculate_stats(trades):
            if not trades:
                return {'avg_obs_psq': 0, 'avg_obs_end_psq': 0, 'avg_pos_psq': 0, 'avg_pos_first_n_psq': 0, 'count': 0,
                        'avg_pnl': 0}

            def safe_avg(data_list):
                return sum(data_list) / len(data_list) if data_list else 0

            obs_psq_avgs = [safe_avg(t['obs_scores']) for t in trades if t['obs_scores']]
            obs_end_psqs = [t['obs_scores'][-1] for t in trades if t['obs_scores']]
            pos_psq_avgs = [safe_avg(t['pos_scores']) for t in trades if t['pos_scores']]

            n = self.p.psq_summary_period
            pos_first_n_avgs = [safe_avg(t['pos_scores'][:n]) for t in trades if t['pos_scores']]

            pnl_values = [t['pnl'] for t in trades]

            return {
                'avg_obs_psq': safe_avg(obs_psq_avgs),
                'avg_obs_end_psq': safe_avg(obs_end_psqs),
                'avg_pos_psq': safe_avg(pos_psq_avgs),
                'avg_pos_first_n_psq': safe_avg(pos_first_n_avgs),
                'count': len(trades),
                'avg_pnl': safe_avg(pnl_values)
            }

        winner_stats = _calculate_stats(winners)
        loser_stats = _calculate_stats(losers)
        mediocre_stats = _calculate_stats(mediocre)

        print(f"\n--- 盈利交易特征 ({winner_stats['count']} 笔, 平均盈利: {winner_stats['avg_pnl']:.2f}) ---")
        if winner_stats['count'] > 0:
            print(f"  - 观察期平均PSQ: {winner_stats['avg_obs_psq']:.2f}")
            print(f"  - 入场日PSQ (观察期终值): {winner_stats['avg_obs_end_psq']:.2f}")
            print(f"  - 持仓期平均PSQ: {winner_stats['avg_pos_psq']:.2f}")
            print(f"  - 持仓期前 {self.p.psq_summary_period} 日平均PSQ: {winner_stats['avg_pos_first_n_psq']:.2f}")

        print(f"\n--- 平庸交易特征 ({mediocre_stats['count']} 笔, 平均盈亏: {mediocre_stats['avg_pnl']:.2f}) ---")
        if mediocre_stats['count'] > 0:
            print(f"  - 观察期平均PSQ: {mediocre_stats['avg_obs_psq']:.2f}")
            print(f"  - 入场日PSQ (观察期终值): {mediocre_stats['avg_obs_end_psq']:.2f}")
            print(f"  - 持仓期平均PSQ: {mediocre_stats['avg_pos_psq']:.2f}")
            print(f"  - 持仓期前 {self.p.psq_summary_period} 日平均PSQ: {mediocre_stats['avg_pos_first_n_psq']:.2f}")

        print(f"\n--- 亏损交易特征 ({loser_stats['count']} 笔, 平均亏损: {loser_stats['avg_pnl']:.2f}) ---")
        if loser_stats['count'] > 0:
            print(f"  - 观察期平均PSQ: {loser_stats['avg_obs_psq']:.2f}")
            print(f"  - 入场日PSQ (观察期终值): {loser_stats['avg_obs_end_psq']:.2f}")
            print(f"  - 持仓期平均PSQ: {loser_stats['avg_pos_psq']:.2f}")
            print(f"  - 持仓期前 {self.p.psq_summary_period} 日平均PSQ: {loser_stats['avg_pos_first_n_psq']:.2f}")

        print('=' * 60 + '\n')
