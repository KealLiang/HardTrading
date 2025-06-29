import logging
from .breakout_strategy import BreakoutStrategy

class ScannableBreakoutStrategy(BreakoutStrategy):
    """
    一个可供扫描器使用的BreakoutStrategy版本。
    通过继承扩展了原始策略，增加了信号发射和静默日志功能，
    而无需修改原始策略代码。
    """
    params = (
        # 继承并新增参数
        ('signal_callback', None),  # 用于发射信号的回调函数
        ('silent', False),          # 是否在扫描模式下关闭日志
    )

    def __init__(self):
        # 首先调用父类的__init__来构建所有基础指标
        super().__init__()
        # 从新的params中获取我们添加的参数
        self.signal_callback = self.p.signal_callback
        self.silent = self.p.silent

    def log(self, txt, dt=None):
        """重写log方法以支持静默模式"""
        if self.silent:
            return  # 在静默模式下，不记录日志
        # 调用父类的log方法，保持原有打印行为
        super().log(txt, dt=dt)

    def _emit_signal(self, signal_type, signal_data=None):
        """统一的信号发射器"""
        if self.signal_callback:
            full_signal = {
                'code': self.data._name,
                'datetime': self.data.datetime.date(0),
                'signal_type': signal_type,
                'close': self.data.close[0],
            }
            if signal_data:
                full_signal.update(signal_data)
            self.signal_callback(full_signal)

    def notify_order(self, order):
        """重写以在订单成交时发射信号"""
        super().notify_order(order)  # 先执行父类的逻辑
        if order.status in [order.Completed]:
            if order.isbuy():
                self._emit_signal('BUY_EXEC', {'size': order.executed.size, 'price': order.executed.price})
            elif order.issell():
                self._emit_signal('SELL_EXEC', {'size': abs(order.executed.size), 'price': order.executed.price})

    def next(self):
        """
        重写next方法以在进入观察模式时发射信号。
        由于原始逻辑复杂且未分解，这里需要复制大部分代码。
        """
        if self.order:
            return

        # --- 1. 持仓时：逻辑与父类完全相同，直接复制 ---
        if self.position:
            # A. 如果在"蓄势待发"的考察期内
            if self.in_coiled_spring_probation:
                self.probation_counter -= 1
                if self.data.high[0] > self.bband.lines.top[0]:
                    self.log('*** 考察期成功通过！切换为ATR跟踪止损 ***')
                    self.in_coiled_spring_probation = False
                    self.highest_high_since_buy = self.data.high[0]
                    self.stop_price = self.highest_high_since_buy - self.p.atr_multiplier * self.atr[0]
                    return
                elif self.data.close[0] < self.bband.lines.mid[0]:
                    self.log('卖出信号: 考察期内跌破中轨，清仓')
                    self.order = self.close()
                elif self.probation_counter <= 0:
                    self.log('卖出信号: 考察期结束，未能突破上轨，清仓')
                    self.order = self.close()
                return
            # B. 不在考察期内，执行ATR跟踪止损
            else:
                if self.highest_high_since_buy == 0:
                    self.highest_high_since_buy = self.data.high[0]
                    self.stop_price = self.data.close[0] - self.p.atr_multiplier * self.atr[0]
                    self.log(
                        f'入场首日，设置初始ATR止损 @ {self.stop_price:.2f} '
                        f'(基于收盘价: {self.data.close[0]:.2f} 和 ATR: {self.atr[0]:.2f})'
                    )
                    return
                self.highest_high_since_buy = max(self.highest_high_since_buy, self.data.high[0])
                new_stop_price = self.highest_high_since_buy - self.p.atr_multiplier * self.atr[0]
                self.stop_price = max(self.stop_price, new_stop_price)
                if self.data.close[0] < self.stop_price:
                    self.log(
                        f'卖出信号: 触发ATR跟踪止损 @ {self.stop_price:.2f} '
                        f'(最高点: {self.highest_high_since_buy:.2f}, ATR: {self.atr[0]:.2f})'
                    )
                    self.order = self.close()
                return

        # --- 2. 空仓时：逻辑大部分与父类相同，但在关键点插入信号发射 ---
        if self.observation_mode:
            self.sentry_highest_high = max(self.sentry_highest_high, self.data.high[0])
            self._check_confirmation_signals() # 调用重写后的版本
            if not self.order and self.observation_counter > 0:
                self.observation_counter -= 1
                if self.observation_counter <= 0:
                    self.log('*** 观察期结束，未出现二次确认信号，解除观察模式 ***')
                    self.observation_mode = False
                    self._emit_signal('OBSERVE_EXIT_TIMEOUT') # 新增：发射信号
        else:
            is_volume_up = self.data.volume[0] > self.volume_ma[0]
            is_strict_breakout = self.data.close[0] > self.bband.lines.top[0]
            is_quasi_breakout = (
                    self.data.high[0] > self.bband.lines.top[0] and
                    self.data.close[0] >= self.bband.lines.top[0] * (1 - self.p.breakout_proximity_pct)
            )
            if is_volume_up and (is_strict_breakout or is_quasi_breakout):
                upper_band_macro = self.ma_macro[0] * (1 + self.p.macro_ranging_pct)
                lower_band_macro = self.ma_macro[0] * (1 - self.p.macro_ranging_pct)
                if self.data.close[0] > upper_band_macro: env_grade, env_score = '牛市', 3
                elif self.data.close[0] < lower_band_macro: env_grade, env_score = '熊市', 1
                else: env_grade, env_score = '震荡市', 2
                bbw_range = self.highest_bbw[-1] - self.lowest_bbw[-1]
                squeeze_pct = (self.bb_width[-1] - self.lowest_bbw[-1]) / bbw_range if bbw_range > 1e-9 else 0
                if squeeze_pct < 0.10: squeeze_grade, squeeze_score = 'A级', 3
                elif squeeze_pct < 0.25: squeeze_grade, squeeze_score = 'B级', 2
                elif squeeze_pct < 0.40: squeeze_grade, squeeze_score = 'C级', 1
                else: squeeze_grade, squeeze_score = 'D级', 0
                volume_ratio = self.data.volume[0] / self.volume_ma[0]
                if 2.0 < volume_ratio <= 5.0: volume_grade, volume_score = 'A级(理想)', 3
                elif 1.5 < volume_ratio <= 2.0: volume_grade, volume_score = 'B级(优秀)', 2
                elif 1.1 < volume_ratio <= 1.5: volume_grade, volume_score = 'C级(合格)', 1
                else:
                    grade_reason = "过高" if volume_ratio > 4.0 else "过低"
                    volume_grade, volume_score = f'D级({grade_reason})', 0
                total_score = env_score + squeeze_score + volume_score
                trigger_observation = False
                breakout_type = ""
                if total_score >= 6:
                    if is_strict_breakout:
                        trigger_observation = True
                        breakout_type = "标准突破"
                    elif is_quasi_breakout:
                        if squeeze_score == 3 or volume_score == 3:
                            trigger_observation = True
                            breakout_type = "准突破(已补偿)"
                if trigger_observation:
                    if total_score >= 8: overall_grade = '【A+级】'
                    elif total_score >= 6: overall_grade = '【B级】'
                    else: overall_grade = '【C级】'
                    log_msg = (
                        f'突破信号: {overall_grade} - {breakout_type} '
                        f'(环境:{env_grade}, 压缩:{squeeze_grade}({squeeze_pct:.0%}), '
                        f'量能:{volume_grade}({volume_ratio:.1f}x))'
                    )
                    self.log(log_msg)
                    self.log(f'*** 触发【突破观察哨】模式，观察期 {self.p.observation_period} 天 ***')
                    self.observation_mode = True
                    self.observation_counter = self.p.observation_period
                    self.sentry_source_signal = f"{overall_grade} @ {self.datas[0].datetime.date(0)}"
                    self.sentry_base_price = self.data.open[0]
                    self.sentry_highest_high = self.data.high[0]
                    # --- 新增: 发射进入观察模式的信号 ---
                    self._emit_signal('OBSERVE_ENTER', {
                        'score': total_score,
                        'breakout_type': breakout_type,
                        'details': f"Env:{env_grade}, Squeeze:{squeeze_grade}, Vol:{volume_grade}"
                    })

    def _check_confirmation_signals(self):
        """重写以在找到买点时发射信号"""
        for signal_name, check_function in self.confirmation_signals:
            if check_function():
                price_floor = self.sentry_base_price
                price_ceiling_from_base = price_floor * (1 + self.p.price_acceptance_pct)
                price_ceiling_from_peak = self.sentry_highest_high * (1 - self.p.pullback_from_peak_pct)
                current_price = self.data.close[0]
                if current_price > price_ceiling_from_base:
                    self.log(f"信号拒绝({signal_name}): 价格 {current_price:.2f} 过高, > 基准价 {price_floor:.2f} 的 {self.p.price_acceptance_pct:.0%}")
                    self._emit_signal('OBSERVE_EXIT_PRICE_LIMIT') # 新增
                    continue
                if current_price < price_ceiling_from_peak:
                    self.log(f"信号拒绝({signal_name}): 价格 {current_price:.2f} 从观察期高点 {self.sentry_highest_high:.2f} 回撤过深")
                    self._emit_signal('OBSERVE_EXIT_PULLBACK_LIMIT') # 新增
                    continue
                
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
                    # --- 新增: 发射买入信号 ---
                    self._emit_signal('BUY_SIGNAL', {
                         'buy_type': signal_name,
                         'details': self.sentry_source_signal
                    })
                    if signal_name == 'coiled_spring':
                        self.coiled_spring_buy_pending = True
                
                self.observation_mode = False
                log_suffix = "发出" if signal_name == 'coiled_spring' else "执行"
                self.log(f'*** 二次确认信号已{log_suffix}，解除观察模式 ***')
                return 