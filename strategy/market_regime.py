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
        ('adx_threshold', 20),

        # -- 微观择时定义 --
        ('ma_short_period', 20),
        ('breakout_period', 10),
        ('rsi_oversold', 25),            # 用于熊市/震荡市的极端超卖阈值
        ('uptrend_rsi_panic', 40),        # 新增：牛市中"恐慌买点"的RSI阈值，更灵敏

        # -- 仓位与风险管理 --
        ('max_portfolio_allocation', 0.90), # 允许投入的总资金比例上限
        ('initial_tranche_pct', 0.10),    # 初始/单次加仓的仓位（占总资金）
        
        # 不同宏观状态下的【最大】仓位系数（乘以 max_portfolio_allocation）
        ('sizing_macro_up', 1.0),         # 牛市，可将仓位加满到上限
        ('sizing_macro_range', 0.5),      # 震荡市，仓位上限减半
        ('sizing_macro_down', 0.25),      # 熊市，仓位上限最低

        # 止盈止损
        ('trailing_stop_pct', 0.07),      # 牛市跟踪止损
        ('ranging_profit_target', 0.08),  # 震荡市止盈
        ('ranging_stop_loss_pct', 0.05),  # 震荡市止损
        ('downtrend_profit_target', 0.05),# 熊市止盈
        ('downtrend_stop_loss_pct', 0.03),# 熊市止损
        
        # 时间止损
        ('max_hold_period', 15),
        ('downtrend_max_hold', 3),
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
        
        self.cdl_hammer = talib.CDLHAMMER(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_engulfing = talib.CDLENGULFING(self.data.open, self.data.high, self.data.low, self.data.close)
        self.cdl_shooting_star = talib.CDLSHOOTINGSTAR(self.data.open, self.data.high, self.data.low, self.data.close)

        # --- 状态跟踪 ---
        self.order = None
        self.buy_tick = 0                  # 首次买入的bar
        self.buy_regime = None             # 首次买入时的宏观状态
        self.highest_high_since_buy = 0    # 用于牛市跟踪止损

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
        
        if self.data.close[0] < self.bbands.bot[0] and self.rsi[0] < rsi_panic_threshold:
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
                self.log(f'买入/加仓成交: {order.executed.size}股 @ {order.executed.price:.2f}, 当前均价: {self.position.price:.2f}, 当前持仓: {self.position.size}股 ({pos_pct:.2f}%)')
                if not self.buy_regime: # 首次建仓
                    self.buy_tick = len(self)
                    self.buy_regime = self._get_macro_regime()
                    self.highest_high_since_buy = self.data.high[0]
            elif order.issell():
                self.log(f'卖出成交: {abs(order.executed.size)}股 @ {order.executed.price:.2f}, 剩余持仓: {self.position.size}股 ({pos_pct:.2f}%)')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]: self.log('订单未能成交')
        self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f'交易关闭, 净盈亏: {trade.pnlcomm:.2f}, 当前总资产: {self.broker.getvalue():.2f}')
            # 重置所有持仓状态
            self.buy_tick = 0; self.highest_high_since_buy = 0; self.buy_regime = None

    def next(self):
        if self.order: return

        current_macro_regime = self._get_macro_regime()

        if self.position:
            # --- 1. 检查是否加仓 (金字塔) ---
            is_profitable = self.data.close[0] > self.position.price
            add_signal = self._get_buy_signal(current_macro_regime)
            
            sizing_map = {'MACRO_UP': self.p.sizing_macro_up, 'MACRO_RANGE': self.p.sizing_macro_range, 'MACRO_DOWN': self.p.sizing_macro_down}
            max_pos_value = self.broker.getvalue() * self.p.max_portfolio_allocation * sizing_map.get(current_macro_regime, 0)
            
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
                self.order = self.close(); return

            if self.buy_regime == 'MACRO_UP':
                self.highest_high_since_buy = max(self.highest_high_since_buy, self.data.high[0])
                trailing_stop_price = self.highest_high_since_buy * (1 - self.p.trailing_stop_pct)
                if self.data.close[0] < trailing_stop_price:
                    self.log(f'卖出信号: (牛市) 触发跟踪止损'); self.order = self.close(); return
            
            elif self.buy_regime == 'MACRO_RANGE':
                profit_pct = (self.data.close[0] - self.position.price) / self.position.price
                if profit_pct > self.p.ranging_profit_target:
                    self.log(f'卖出信号: (震荡市) 达到止盈目标'); self.order = self.close(); return
                if self.data.close[0] < self.position.price * (1 - self.p.ranging_stop_loss_pct):
                    self.log(f'卖出信号: (震荡市) 触发止损'); self.order = self.close(); return

            elif self.buy_regime == 'MACRO_DOWN':
                profit_pct = (self.data.close[0] - self.position.price) / self.position.price
                if profit_pct > self.p.downtrend_profit_target:
                    self.log(f'卖出信号: (熊市) 快速止盈'); self.order = self.close(); return
                if self.data.close[0] < self.position.price * (1 - self.p.downtrend_stop_loss_pct):
                    self.log(f'卖出信号: (熊市) 快速止损'); self.order = self.close(); return
                if hold_days >= self.p.downtrend_max_hold:
                    self.log(f'卖出信号: (熊市) 持仓到期'); self.order = self.close(); return

            if hold_days >= self.p.max_hold_period:
                self.log(f'卖出信号: ({self.buy_regime}) 持仓超过 {self.p.max_hold_period} 天'); self.order = self.close(); return
            return

        else: # not self.position
            # --- 3. 检查是否首次建仓 ---
            buy_signal = self._get_buy_signal(current_macro_regime)
            if buy_signal:
                initial_tranche_value = self.broker.getvalue() * self.p.initial_tranche_pct
                size = int(initial_tranche_value / self.data.close[0])
                if size > 0:
                    self.log(f'建仓信号: ({current_macro_regime}) - {buy_signal}, 建立试探仓位.')
                    self.order = self.buy(size=size)