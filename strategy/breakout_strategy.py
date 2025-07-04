import backtrader as bt
import talib


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
        ('bband_period', 20),  # 布林带周期
        ('bband_devfactor', 2.0),  # 布林带标准差
        ('volume_ma_period', 20),  # 成交量移动平均周期
        # -- 信号评级与观察模式参数 --
        ('ma_macro_period', 60),  # 定义宏观环境的长周期均线
        ('macro_ranging_pct', 0.05),  # 定义震荡市的均线上下浮动范围
        ('squeeze_period', 90),  # 波动性压缩回顾期
        ('observation_period', 15),  # 触发观察模式后的持续天数
        ('confirmation_lookback', 5),  # "蓄势待发"信号的回看周期
        ('probation_period', 5),  # "蓄势待发"买入后的考察期天数
        ('pocket_pivot_lookback', 10),  # 口袋支点信号的回看期
        ('breakout_proximity_pct', 0.01),  # "准突破"价格接近上轨的容忍度(1%)
        ('price_acceptance_pct', 0.25),  # 从观察期基准价上涨的最大可接受百分比(20%)
        ('pullback_from_peak_pct', 0.07),  # 从观察期高点可接受的最大回撤(7%)
        # -- 风险管理 --
        ('initial_stake_pct', 0.90),  # 初始仓位（占总资金）
        ('atr_period', 14),  # ATR周期
        ('atr_multiplier', 2.0),  # ATR止损乘数
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

        # --- PSQ 2.0 辅助指标 ---
        self.ma5 = bt.indicators.SMA(self.data.close, period=5)
        self.ma10 = bt.indicators.SMA(self.data.close, period=10)

        # --- K线形态指标 (TA-Lib) ---
        self.cdl_engulfing = bt.talib.CDLENGULFING(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_morningstar = bt.talib.CDLMORNINGSTAR(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_3whitesoldiers = bt.talib.CDL3WHITESOLDIERS(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_hammer = bt.talib.CDLHAMMER(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_piercing = bt.talib.CDLPIERCING(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_eveningstar = bt.talib.CDLEVENINGSTAR(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_3blackcrows = bt.talib.CDL3BLACKCROWS(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_shootingstar = bt.talib.CDLSHOOTINGSTAR(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_darkcloudcover = bt.talib.CDLDARKCLOUDCOVER(self.data.open, self.data.high, self.data.low, self.data.close)
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
        # 新增：观察哨模式状态
        self.observation_mode = False
        self.observation_counter = 0
        self.sentry_source_signal = ""
        # 新增：价格接受度过滤器所需的状态
        self.sentry_base_price = 0
        self.sentry_highest_high = 0
        # 新增：蓄势待发信号的考察期状态
        self.coiled_spring_buy_pending = False
        self.in_coiled_spring_probation = False
        self.probation_counter = 0
        # --- PSQ 2.0 状态 ---
        self.psq_scores = []
        self.psq_tracking_reason = None
        self.psq_signal_day_context = {}  # 存储信号日的关键数据

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
            # 结束持仓期评分
            self._stop_and_log_psq()
            # 重置所有交易相关的状态
            self.stop_price = 0
            self.highest_high_since_buy = 0
            self.in_coiled_spring_probation = False
            self.probation_counter = 0

    def next(self):
        # --- PSQ 2.0 评分 (每日) ---
        # 仅在信号日之后进行每日评分
        is_after_signal_day = self.psq_signal_day_context and \
                              self.datas[0].datetime.date(0) > self.psq_signal_day_context.get('date')

        if self.psq_tracking_reason and is_after_signal_day:
            psq_score = self._calculate_psq_score(self.psq_tracking_reason, self.datas[0])
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
                    self.order = self.close()
                return  # 持仓时，完成止损检查后即可结束

        # --- 2. 空仓时：根据模式决定买入逻辑 ---
        if self.observation_mode:
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

                # --- 信号评级系统 ---
                # (评级逻辑保持不变)
                upper_band_macro = self.ma_macro[0] * (1 + self.p.macro_ranging_pct)
                lower_band_macro = self.ma_macro[0] * (1 - self.p.macro_ranging_pct)
                if self.data.close[0] > upper_band_macro:
                    env_grade, env_score = '牛市', 3
                elif self.data.close[0] < lower_band_macro:
                    env_grade, env_score = '熊市', 1
                else:
                    env_grade, env_score = '震荡市', 2

                bbw_range = self.highest_bbw[-1] - self.lowest_bbw[-1]
                squeeze_pct = (self.bb_width[-1] - self.lowest_bbw[-1]) / bbw_range if bbw_range > 1e-9 else 0
                if 0.05 < squeeze_pct <= 0.20:
                    squeeze_grade, squeeze_score = 'A级', 3
                elif squeeze_pct <= 0.05:
                    squeeze_grade, squeeze_score = 'B级', 2
                elif 0.20 < squeeze_pct <= 0.60:
                    squeeze_grade, squeeze_score = 'C级', 1
                else:
                    squeeze_grade, squeeze_score = 'D级', 0

                volume_ratio = self.data.volume[0] / self.volume_ma[0]
                if 3.0 < volume_ratio <= 5.0:
                    volume_grade, volume_score = 'A级(理想)', 3
                elif 1.5 < volume_ratio <= 3.0:
                    volume_grade, volume_score = 'B级(优秀)', 2
                elif 1.1 < volume_ratio <= 1.5:
                    volume_grade, volume_score = 'C级(合格)', 1
                else:
                    grade_reason = "过高" if volume_ratio > 5.0 else "过低"
                    volume_grade, volume_score = f'D级({grade_reason})', 0

                total_score = env_score + squeeze_score + volume_score

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
                        f'量能:{volume_grade}({volume_ratio:.1f}x))'
                    )
                    self.log(log_msg)

                    self.log(f'*** 触发【突破观察哨】模式，观察期 {self.p.observation_period} 天 ***')
                    self.observation_mode = True
                    self.observation_counter = self.p.observation_period
                    self.sentry_source_signal = f"{overall_grade} @ {self.datas[0].datetime.date(0)}"
                    # 记录价格过滤器所需的状态
                    self.sentry_base_price = self.data.open[0]
                    self.sentry_highest_high = self.data.high[0]
                    # 开始PSQ评分 - 从信号日当天开始
                    self._start_psq_tracking('观察期', self.datas[0])

    def _check_confirmation_signals(self):
        """
        统一检查所有二次确认信号。
        """
        for signal_name, check_function in self.confirmation_signals:
            if check_function():
                # --- 新增：动态价格接受窗口过滤器 ---
                price_floor = self.sentry_base_price
                price_ceiling_from_base = price_floor * (1 + self.p.price_acceptance_pct)
                price_ceiling_from_peak = self.sentry_highest_high * (1 - self.p.pullback_from_peak_pct)
                current_price = self.data.close[0]

                if current_price > price_ceiling_from_base:
                    self.log(
                        f"信号拒绝({signal_name}): 价格 {current_price:.2f} 过高, > 基准价 {price_floor:.2f} 的 {self.p.price_acceptance_pct:.0%}")
                    continue  # 继续检查下一个信号，或者结束本轮

                if current_price < price_ceiling_from_peak:
                    self.log(
                        f"信号拒绝({signal_name}): 价格 {current_price:.2f} 从观察期高点 {self.sentry_highest_high:.2f} 回撤过深")
                    continue  # 继续检查下一个信号，或者结束本轮
                # --- 过滤器结束 ---

                log_msg_map = {
                    'coiled_spring': f'突破信号:【蓄势待发】(源信号: {self.sentry_source_signal})',
                    'pocket_pivot': f'突破信号:【口袋支点】(源信号: {self.sentry_source_signal})'
                }
                log_msg = log_msg_map.get(signal_name, '未知确认信号')
                self.log(log_msg)

                stake = self.broker.getvalue() * self.p.initial_stake_pct
                size = int(stake / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
                    # 只有"蓄势待发"信号需要进入考察期
                    if signal_name == 'coiled_spring':
                        self.coiled_spring_buy_pending = True

                # 注意：此处不停止PSQ，因为买单可能不会立即成交。
                # 评分的停止和切换将在notify_order中处理
                self.observation_mode = False
                log_suffix = "发出" if signal_name == 'coiled_spring' else "执行"
                self.log(f'*** 二次确认信号已{log_suffix}，解除观察模式 ***')
                return  # 找到一个信号后就停止检查

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

    # --- PSQ 2.0 评分系统 ---
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
        day_0_score = self._calculate_psq_score(reason, data)
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

    def _get_kline_pattern_score(self):
        """使用TA-Lib识别K线形态并评分"""
        score = 0
        # 强势看涨形态
        if self.cdl_engulfing[0] > 0: score += 2.0
        if self.cdl_morningstar[0] != 0: score += 2.0
        if self.cdl_3whitesoldiers[0] != 0: score += 3.0
        # 弱势看涨/反转形态
        if self.cdl_hammer[0] != 0: score += 1.0
        if self.cdl_piercing[0] != 0: score += 1.5

        # 强势看跌形态
        if self.cdl_engulfing[0] < 0: score -= 2.0
        if self.cdl_eveningstar[0] != 0: score -= 2.0
        if self.cdl_3blackcrows[0] != 0: score -= 3.0
        # 弱势看跌/反转形态
        if self.cdl_shootingstar[0] != 0: score -= 1.0
        if self.cdl_darkcloudcover[0] != 0: score -= 1.5

        # 十字星等中性形态
        if self.cdl_doji[0] != 0: score -= 0.5  # 通常代表犹豫

        return score

    def _calculate_psq_score(self, period_type, data):
        """计算当日的PSQ 2.0总分"""
        # --- 1. K线形态分 ---
        pattern_score = self._get_kline_pattern_score()

        # --- 2. 价格行为分 ---
        gap_pct = (data.open[0] / data.close[-1] - 1) * 100
        gap_score = min(max(gap_pct, -2), 2)  # 将跳空得分限制在[-2, 2]

        candle_range = data.high[0] - data.low[0]
        intraday_strength = 0
        if candle_range > 1e-9:
            intraday_strength = (data.close[0] - data.open[0]) / candle_range
        price_action_score = gap_score + intraday_strength * 2 # 日内强度权重为2

        # --- 3. 量能匹配分 ---
        volume_ratio_ma = data.volume[0] / self.volume_ma[0] if self.volume_ma[0] > 0 else 1
        signal_vol = self.psq_signal_day_context.get('volume', 0)
        volume_ratio_signal = data.volume[0] / signal_vol if signal_vol > 0 else 1

        is_price_up = data.close[0] > data.close[-1]
        is_volume_up_ma = volume_ratio_ma > 1.1

        # 基础量价关系
        if (is_price_up and is_volume_up_ma) or (not is_price_up and not is_volume_up_ma):
            volume_score = 1  # 健康
        else:
            volume_score = -1 # 不健康

        # 对比信号日成交量进行修正
        if period_type == '观察期' and data.datetime.date(0) > self.psq_signal_day_context['date']:
            if is_price_up and volume_ratio_signal < 0.7:
                volume_score -= 1 # 上涨但量能相比信号日萎缩太多
            if not is_price_up and volume_ratio_signal > 1.2:
                volume_score -= 1.5 # 下跌但量能比信号日还大，非常危险

        # --- 4. 位置结构分 ---
        positional_score = 0
        # 相对于均线的位置
        if data.close[0] > self.ma5[0]: positional_score += 0.5
        if data.close[0] > self.ma10[0]: positional_score += 0.5

        # 相对于信号日关键位置
        signal_mid_price = self.psq_signal_day_context.get('mid_price', data.close[0])
        if data.close[0] < signal_mid_price:
            positional_score -= 1 # 跌破信号日中点，警示信号

        # --- 5. 情景化调整 (核心) ---
        scenario_adjustment = 0
        if period_type == '观察期':
            # 拒绝过热: 首次突破布林带上轨是好事，但持续过高则不好
            if data.close[0] > self.bband.lines.top[0] and data.close[-1] > self.bband.lines.top[-1]:
                scenario_adjustment -= 1 # 连续两天在上轨之上，可能过热
            # 拒绝深跌
            pullback_from_high = (data.high[0] - data.close[0]) / (data.high[0] - data.low[0]) if (data.high[0] - data.low[0]) > 1e-9 else 0
            if pullback_from_high > 0.7:
                 scenario_adjustment -= 1 # 长上影线，抛压沉重

        elif period_type == '持仓期':
            # 奖励强势
            if data.close[0] > self.highest_high_since_buy:
                scenario_adjustment += 1.5 # 创持仓新高，强力加分

        total_score = pattern_score + price_action_score + volume_score + positional_score + scenario_adjustment
        return total_score
