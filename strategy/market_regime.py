import backtrader as bt
import backtrader.talib as talib


class MarketRegimeStrategy(bt.Strategy):
    """
    最终策略：动态火力调配与金字塔式增兵
    - 初始试探仓位 + 盈利后分批加仓，让利润奔跑
    - 宏观状态决定火力上限和战术
    - 统一卖出逻辑，确保纪律
    """
    params = (
        # -- 宏观状态定义 --
        ('ma_macro_period', 60),
        ('adx_threshold', 19),

        # -- 微观择时定义 --
        ('ma_short_period', 20),
        ('breakout_period', 10),
        ('rsi_oversold', 25),  # 用于熊市/震荡市的极端超卖阈值
        ('uptrend_rsi_panic', 40),  # 新增：牛市中"恐慌买点"的RSI阈值，更灵敏
        ('bb_proximity_pct', 0.01),  # 新增：判断价格"接近"布林带下轨的容忍度

        # -- 顶部盘整模式参数 --
        ('adx_high_level', 30),  # ADX高位水平，用于判断动能衰减
        ('topping_target_pct', 0.40),  # 顶部盘整模式下的目标仓位
        ('topping_rebalance_band_pct', 0.10),  # 仓位再平衡的触发带宽(10% -> 目标仓位的90%和110%)

        # -- 仓位与风险管理 --
        ('max_portfolio_allocation', 0.90),  # 允许投入的总资金比例上限
        ('initial_tranche_pct', 0.10),  # 初始/单次加仓的仓位（占总资金）

        # 不同宏观状态下的【最大】仓位系数（乘以 max_portfolio_allocation）
        ('sizing_macro_up', 1.0),  # 牛市，可将仓位加满到上限
        ('sizing_macro_range', 0.5),  # 震荡市，仓位上限减半
        ('sizing_macro_down', 0.25),  # 熊市，仓位上限最低

        # 止盈止损
        ('trailing_stop_pct', 0.07),  # 牛市跟踪止损
        ('ranging_profit_target', 0.08),  # 震荡市止盈
        ('ranging_stop_loss_pct', 0.05),  # 震荡市止损
        ('downtrend_profit_target', 0.05),  # 熊市止盈
        ('downtrend_stop_loss_pct', 0.03),  # 熊市止损

        # 时间止损
        ('hold_period_base', 15),  # 时间止损基准天数
        ('hold_period_window', 3),  # 时间止损窗口范围
        ('downtrend_max_hold', 3),
        ('volume_long_period', 20),  # 用于判断成交量趋势的长周期
        ('partial_sell_pct', 0.33),  # 每次分批卖出的比例

        # -- 恐慌反弹模式专属参数 --
        ('panic_secondary_stop_pct', 0.03),  # 二次恐慌的灵活止损百分比
        ('panic_rebound_hold_days', 14),  # 恐慌反弹模式最大持有天数
        ('panic_rebound_partial_sell_pct', 0.5),  # 恐慌反弹模式高抛减仓比例
    )

    def __init__(self):
        # --- 指标 ---
        self.ma_macro = bt.indicators.SMA(self.data.close, period=self.p.ma_macro_period)
        self.adx = bt.indicators.ADX(self.data, period=14)
        self.ma_short = bt.indicators.SMA(self.data.close, period=self.p.ma_short_period)
        self.bbands = bt.indicators.BollingerBands(self.data, period=20)
        self.rsi = bt.indicators.RSI(self.data, period=14)
        self.highest_close = bt.indicators.Highest(self.data.close, period=self.p.breakout_period)
        self.volume_ma = bt.indicators.SMA(self.data.volume, period=5)
        self.volume_ma_long = bt.indicators.SMA(self.data.volume, period=self.p.volume_long_period)

        self.cdl_hammer = talib.CDLHAMMER(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_engulfing = talib.CDLENGULFING(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_shooting_star = talib.CDLSHOOTINGSTAR(self.data.open, self.data.high, self.data.low, self.data.close)

        # --- 状态跟踪 ---
        self.order = None
        self.buy_tick = 0  # 首次买入的bar
        self.buy_regime = None  # 首次买入时的宏观状态
        self.highest_high_since_buy = 0  # 用于牛市跟踪止损

        # -- 模式状态 --
        self.is_topping_phase = False  # 是否处于顶部盘整模式
        self.is_panic_rebound_trade = False  # 是否处于恐慌反弹交易中

        # --- 恐慌反弹模式状态 ---
        self.pending_buy_signal = None  # 待成交的买入信号类型
        self.panic_buy_low_price = 0.0  # 首次恐慌买入日的最低价，用作止损
        self.panic_buy_counter = 0  # 恐慌交易计数器

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()} - {txt}')

    # --- 辅助函数 ---
    def _get_macro_regime(self):
        ma_macro_slope = self.ma_macro[0] - self.ma_macro[-5]
        adx_is_trending = self.adx.adx[0] > self.p.adx_threshold
        if self.data.close[0] > self.ma_macro[0] and ma_macro_slope > 0 and adx_is_trending:
            return 'MACRO_UP'
        if self.data.close[0] < self.ma_macro[0] and ma_macro_slope < 0 and adx_is_trending:
            return 'MACRO_DOWN'
        return 'MACRO_RANGE'

    def _get_kline_signal(self):
        try:
            if self.cdl_hammer[0] != 0 or self.cdl_engulfing[0] == 100:
                return 'BULLISH_REVERSAL'
            if self.cdl_shooting_star[0] != 0 or self.cdl_engulfing[0] == -100:
                return 'BEARISH_REVERSAL'
        except IndexError:
            return None
        return None

    def _get_buy_signal(self, regime):
        # --- 1. 机会雷达：捕捉恐慌性买点 (最高优先级) ---
        # 核心逻辑：价格跌破布林带下轨，且RSI进入超卖区
        # 智能调整：牛市中，RSI不必极度超卖就可认为是机会
        rsi_panic_threshold = self.p.rsi_oversold  # 默认使用审慎阈值
        if regime == 'MACRO_UP':
            rsi_panic_threshold = self.p.uptrend_rsi_panic  # 牛市中使用更灵敏的阈值

        # "接近"布林带下轨，我们用当日最低价触及来判断，这样更灵敏
        is_panic_B = self.rsi[0] < self.p.rsi_oversold and self.data.low[0] <= self.bbands.bot[0] * (
                1 + self.p.bb_proximity_pct)

        if is_panic_B:
            return '恐慌性买点'

        # --- 2. 常规买点 (若无恐慌信号) ---
        kline_signal = self._get_kline_signal()
        if regime == 'MACRO_UP':
            if self.data.close[0] < self.ma_short[0]:
                return '回调低吸'
            if self.data.close[0] > self.highest_close[-1] and self.data.volume[0] > self.volume_ma[0]:
                return '放量突破'
        elif regime == 'MACRO_RANGE':
            if self.data.close[0] < self.bbands.bot[0] and kline_signal == 'BULLISH_REVERSAL':
                return '下轨看涨'
        # 熊市的买点已完全被上面的"恐慌性买点"逻辑所覆盖，此处不再重复判断
        return None

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]: return
        if order.status in [order.Completed]:
            # Calculate position percentage
            pos_value = self.position.size * self.data.close[0]
            total_value = self.broker.getvalue()
            pos_pct = (pos_value / total_value) * 100 if total_value > 0 else 0

            if order.isbuy():
                self.log(
                    f'买入/加仓成交: {order.executed.size}股 @ {order.executed.price:.2f}, 当前均价: {self.position.price:.2f}, 当前持仓: {self.position.size}股 ({pos_pct:.2f}%)')
                if not self.buy_regime:  # 首次建仓
                    self.buy_tick = len(self)
                    self.buy_regime = self._get_macro_regime()
                    self.highest_high_since_buy = self.data.high[0]

                    if self.pending_buy_signal == '恐慌性买点':
                        self.is_panic_rebound_trade = True
                        self.panic_buy_low_price = self.data.low[0]

                        # 恐慌计数器+1
                        self.panic_buy_counter += 1

                        if self.panic_buy_counter > 1:
                            self.log(f'*** 进入二次恐慌反弹模式 (第{self.panic_buy_counter}次), 止损切换为灵活模式 ***')
                        else:
                            self.log(f'*** 进入首次恐慌反弹模式, 硬止损位于 {self.panic_buy_low_price:.2f} ***')

                self.pending_buy_signal = None  # 重置信号

            elif order.issell():
                self.log(
                    f'卖出成交: {abs(order.executed.size)}股 @ {order.executed.price:.2f}, 剩余持仓: {self.position.size}股 ({pos_pct:.2f}%)')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('订单未能成交')
        self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f'交易关闭, 净盈亏: {trade.pnlcomm:.2f}, 当前总资产: {self.broker.getvalue():.2f}')
            # 重置所有持仓状态
            self.buy_tick = 0;
            self.highest_high_since_buy = 0;
            self.buy_regime = None
            self.is_panic_rebound_trade = False
            self.panic_buy_low_price = 0.0
            # 注意：panic_buy_counter 不在这里重置，它由市场状态恢复时在next()中重置
            self.is_topping_phase = False  # 关闭交易时，重置顶部模式

    def _handle_entry_signal(self, current_macro_regime):
        # --- 检查是否首次建仓 ---
        buy_signal = self._get_buy_signal(current_macro_regime)
        if buy_signal:
            initial_tranche_value = self.broker.getvalue() * self.p.initial_tranche_pct
            size = int(initial_tranche_value / self.data.close[0])
            if size > 0:
                self.log(f'建仓信号: ({current_macro_regime}) - {buy_signal}, 建立试探仓位.')
                self.pending_buy_signal = buy_signal
                self.order = self.buy(size=size)

    def _handle_panic_rebound_trade(self, current_macro_regime):
        hold_days = len(self) - self.buy_tick

        # --- A. 止损逻辑 (区分首次/二次) ---
        if self.panic_buy_counter == 1:  # 首次试探，使用硬止损
            if self.data.low[0] < self.panic_buy_low_price:
                self.log(
                    f'卖出信号: (首次恐慌) 创下新低 {self.data.low[0]:.2f} < {self.panic_buy_low_price:.2f}, 立即止损.')
                self.order = self.close()
                return
        else:  # 二次及以上，使用灵活的百分比止损
            flexible_stop_price = self.position.price * (1 - self.p.panic_secondary_stop_pct)
            if self.data.close[0] < flexible_stop_price:
                self.log(f'卖出信号: (二次恐慌) 触发 {self.p.panic_secondary_stop_pct * 100:.0f}% 灵活止损.')
                self.order = self.close()
                return

        # --- B. 时间止损 ---
        if hold_days >= self.p.panic_rebound_hold_days:
            self.log(f'卖出信号: (恐慌模式) 持有超过 {self.p.panic_rebound_hold_days} 天, 时间止损.')
            self.order = self.close()
            return

        # --- C. 盈利加仓逻辑 (仅在二次恐慌盈利时) ---
        is_profitable = self.data.close[0] > self.position.price
        if self.panic_buy_counter > 1 and is_profitable:
            # 复用常规的仓位控制逻辑
            sizing_map = {'MACRO_UP': self.p.sizing_macro_up, 'MACRO_RANGE': self.p.sizing_macro_range,
                          'MACRO_DOWN': self.p.sizing_macro_down}
            max_pos_value = self.broker.getvalue() * self.p.max_portfolio_allocation * sizing_map.get(
                current_macro_regime, 0.25)
            current_pos_value = self.position.size * self.data.close[0]
            initial_tranche_value = self.broker.getvalue() * self.p.initial_tranche_pct
            can_add_position = current_pos_value + initial_tranche_value <= max_pos_value

            add_signal = self._get_buy_signal(current_macro_regime)
            if add_signal == '恐慌性买点' and can_add_position:
                size = int(initial_tranche_value / self.data.close[0])
                if size > 0:
                    self.log(f'加仓信号: (二次恐慌盈利中) 出现加仓机会 {add_signal}.')
                    self.order = self.buy(size=size)
                    return

        # --- D. 高抛止盈逻辑 ---
        if self.data.close[0] > self.bbands.mid[0]:
            sell_pct = self.p.panic_rebound_partial_sell_pct
            sell_size = int(self.position.size * sell_pct)
            if sell_size > 0:
                self.log(f'卖出信号: (恐慌模式) 触及布林带中轨, 高抛减仓 {sell_pct * 100:.0f}%.')
                self.order = self.sell(size=sell_size)
                # 减仓后，退出恐慌模式，将剩余仓位交由常规逻辑管理
                self.is_panic_rebound_trade = False
                return

    def _handle_topping_phase_trade(self, current_macro_regime):
        # --- 1. 执行动态再平衡 (只高抛，不低吸) ---
        target_value = self.broker.getvalue() * self.p.topping_target_pct
        upper_band_value = target_value * (1 + self.p.topping_rebalance_band_pct)
        current_pos_value = self.position.size * self.data.close[0]

        # 高抛: 如果仓位价值超过了目标区间的上轨，则卖出多余部分，回归目标
        if current_pos_value > upper_band_value:
            value_to_sell = current_pos_value - target_value
            size_to_sell = int(value_to_sell / self.data.close[0])
            if size_to_sell > 0:
                self.log(f'交易信号: (顶部模式) 高抛, 卖出 {size_to_sell} 股以回归目标仓位.')
                self.order = self.sell(size=size_to_sell)
                return

        # 低吸逻辑被移除，以防止在顶部区域错误地加仓

        # --- 2. 如果不进行再平衡，则检查常规卖出条件 ---
        #    (这部分代码与 _handle_regular_trade 中的卖出逻辑重复，未来可优化)
        hold_days = len(self) - self.buy_tick
        is_regime_degraded = (self.buy_regime == 'MACRO_UP' and current_macro_regime != 'MACRO_UP') or \
                             (self.buy_regime == 'MACRO_RANGE' and current_macro_regime == 'MACRO_DOWN')
        if is_regime_degraded:
            self.log(f'卖出信号: 宏观状态从 {self.buy_regime} 恶化为 {current_macro_regime}, 清仓')
            self.order = self.close()
            return

        # 顶部模式只可能在牛市持仓中出现
        if self.buy_regime == 'MACRO_UP':
            self.highest_high_since_buy = max(self.highest_high_since_buy, self.data.high[0])
            trailing_stop_price = self.highest_high_since_buy * (1 - self.p.trailing_stop_pct)
            if self.data.close[0] < trailing_stop_price:
                self.log(f'卖出信号: (顶部模式) 触发跟踪止损')
                self.order = self.close()
                return

        # 动态时间窗口卖出逻辑
        if self.buy_regime == 'MACRO_UP' and self.position.size > 0:
            time_window_start = self.p.hold_period_base - self.p.hold_period_window
            if hold_days >= time_window_start:
                is_volume_shrinking = self.volume_ma[0] < self.volume_ma_long[0]
                if is_volume_shrinking:
                    sell_size = int(self.position.size * self.p.partial_sell_pct)
                    if sell_size > 0:
                        self.log(
                            f'卖出信号: (顶部模式) 持仓{hold_days}天, 成交量萎缩, 分批卖出 {self.p.partial_sell_pct * 100:.0f}%.')
                        self.order = self.sell(size=sell_size)
                        return

        hard_stop_days = self.p.hold_period_base + self.p.hold_period_window
        if hold_days >= hard_stop_days:
            self.log(f'卖出信号: ({self.buy_regime}) 持仓超过 {hard_stop_days} 天, 硬止损清仓')
            self.order = self.close()
            return

    def _handle_regular_trade(self, current_macro_regime):
        # --- 1. 检查是否加仓 (金字塔) ---
        is_profitable = self.data.close[0] > self.position.price
        add_signal = self._get_buy_signal(current_macro_regime)

        sizing_map = {'MACRO_UP': self.p.sizing_macro_up, 'MACRO_RANGE': self.p.sizing_macro_range,
                      'MACRO_DOWN': self.p.sizing_macro_down}
        max_pos_value = self.broker.getvalue() * self.p.max_portfolio_allocation * sizing_map.get(current_macro_regime,
                                                                                                  0)

        current_pos_value = self.position.size * self.data.close[0]
        initial_tranche_value = self.broker.getvalue() * self.p.initial_tranche_pct
        can_add_position = current_pos_value + initial_tranche_value <= max_pos_value

        if is_profitable and add_signal and can_add_position:
            profit_pct = (self.data.close[0] - self.position.price) / self.position.price * 100
            size = int(initial_tranche_value / self.data.close[0])
            if size > 0:
                self.log(f'加仓信号: ({current_macro_regime}) - {add_signal}, 浮盈中({profit_pct:.2f}%), 继续加仓.')
                self.order = self.buy(size=size)
                return

        # --- 2. 检查是否卖出 ---
        hold_days = len(self) - self.buy_tick
        is_regime_degraded = (self.buy_regime == 'MACRO_UP' and current_macro_regime != 'MACRO_UP') or \
                             (self.buy_regime == 'MACRO_RANGE' and current_macro_regime == 'MACRO_DOWN')
        if is_regime_degraded:
            self.log(f'卖出信号: 宏观状态从 {self.buy_regime} 恶化为 {current_macro_regime}, 清仓')
            self.order = self.close()
            return

        if self.buy_regime == 'MACRO_UP':
            self.highest_high_since_buy = max(self.highest_high_since_buy, self.data.high[0])
            trailing_stop_price = self.highest_high_since_buy * (1 - self.p.trailing_stop_pct)
            if self.data.close[0] < trailing_stop_price:
                self.log(f'卖出信号: (牛市) 触发跟踪止损')
                self.order = self.close()
                return

        elif self.buy_regime == 'MACRO_RANGE':
            profit_pct = (self.data.close[0] - self.position.price) / self.position.price
            if profit_pct > self.p.ranging_profit_target:
                self.log(f'卖出信号: (震荡市) 达到止盈目标')
                self.order = self.close()
                return
            if self.data.close[0] < self.position.price * (1 - self.p.ranging_stop_loss_pct):
                self.log(f'卖出信号: (震荡市) 触发止损')
                self.order = self.close()
                return

        elif self.buy_regime == 'MACRO_DOWN':
            profit_pct = (self.data.close[0] - self.position.price) / self.position.price
            if profit_pct > self.p.downtrend_profit_target:
                self.log(f'卖出信号: (熊市) 快速止盈')
                self.order = self.close()
                return
            if self.data.close[0] < self.position.price * (1 - self.p.downtrend_stop_loss_pct):
                self.log(f'卖出信号: (熊市) 快速止损')
                self.order = self.close()
                return
            if hold_days >= self.p.downtrend_max_hold:
                self.log(f'卖出信号: (熊市) 持仓到期')
                self.order = self.close()
                return

        # --- 动态时间窗口卖出 (新逻辑) ---
        if self.buy_regime == 'MACRO_UP' and self.position.size > 0:
            time_window_start = self.p.hold_period_base - self.p.hold_period_window
            if hold_days >= time_window_start:
                is_volume_shrinking = self.volume_ma[0] < self.volume_ma_long[0]
                if is_volume_shrinking:
                    sell_size = int(self.position.size * self.p.partial_sell_pct)
                    if sell_size > 0:
                        self.log(
                            f'卖出信号: ({self.buy_regime}) 持仓{hold_days}天, 成交量萎缩, 分批卖出 {self.p.partial_sell_pct * 100:.0f}%.')
                        self.order = self.sell(size=sell_size)
                        return

        # 硬时间止损使用基准+窗口
        hard_stop_days = self.p.hold_period_base + self.p.hold_period_window
        if hold_days >= hard_stop_days:
            self.log(f'卖出信号: ({self.buy_regime}) 持仓超过 {hard_stop_days} 天, 硬止损清仓')
            self.order = self.close()
            return

    def next(self):
        if self.order: return

        current_macro_regime = self._get_macro_regime()

        # --- 1. 市场状态驱动的全局状态重置 ---
        # 如果市场恢复，重置恐慌计数器
        if self.data.close[0] > self.ma_macro[0] and self.panic_buy_counter > 0:
            self.log('*** 市场恢复至60日均线上方，恐慌序列计数器重置 ***')
            self.panic_buy_counter = 0

        # 如果市场脱离牛市，强制退出顶部盘整模式
        if self.is_topping_phase and current_macro_regime != 'MACRO_UP':
            self.is_topping_phase = False
            self.log('*** 市场脱离牛市, 退出顶部盘整模式 ***')

        # --- 2. 核心逻辑调度 ---
        if self.position:
            # --- 持仓中逻辑 ---

            # A. 检查是否需要从常规模式【切换】到顶部盘整模式
            # 条件：非恐慌交易、处于牛市、持仓盈利、且动能与成交量同步衰退
            if not self.is_topping_phase and not self.is_panic_rebound_trade and \
                    self.buy_regime == 'MACRO_UP' and self.data.close[0] > self.position.price:

                # 新逻辑: 动能和成交量同时出现衰退迹象
                adx_is_falling_from_high = self.adx.adx[0] < self.adx.adx[-1] and self.adx.adx[
                    -1] > self.p.adx_high_level
                volume_is_fading = self.volume_ma[0] < self.volume_ma_long[0]

                if adx_is_falling_from_high and volume_is_fading:
                    self.is_topping_phase = True
                    self.log('*** 动能与成交量衰退, 切换为顶部盘整模式 ***')

            # B. 调度到具体的持仓管理函数
            if self.is_panic_rebound_trade:
                self._handle_panic_rebound_trade(current_macro_regime)
            elif self.is_topping_phase:
                self._handle_topping_phase_trade(current_macro_regime)
            else:
                self._handle_regular_trade(current_macro_regime)
        else:
            # --- 空仓时逻辑 ---
            # 主要负责处理建仓信号
            self._handle_entry_signal(current_macro_regime)
