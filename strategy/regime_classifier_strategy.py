import backtrader as bt


class RegimeIndicator(bt.Indicator):
    """
    一个将市场宏观状态数值化的指标，用于绘图。
    - 输出值：
        - 1: 牛市 (MACRO_UP)
        - 0: 震荡市 (MACRO_RANGE)
        - -1: 熊市 (MACRO_DOWN)
    """
    lines = ('regime',)
    params = (
        ('ma_macro_period', 60),
        ('adx_threshold', 19),
        ('slope_period', 5),  # 用来计算均线斜率的回看周期
    )

    def __init__(self):
        # 使用与主策略完全相同的指标
        self.ma_macro = bt.indicators.SMA(self.data.close, period=self.p.ma_macro_period)
        self.adx = bt.indicators.ADX(self.data, period=14)

    def next(self):
        # 使用与主策略完全相同的判断逻辑
        ma_macro_slope = self.ma_macro[0] - self.ma_macro[-self.p.slope_period]
        adx_is_trending = self.adx.adx[0] > self.p.adx_threshold

        if self.data.close[0] > self.ma_macro[0] and ma_macro_slope > 0 and adx_is_trending:
            self.lines.regime[0] = 1  # 牛市
        elif self.data.close[0] < self.ma_macro[0] and ma_macro_slope < 0 and adx_is_trending:
            self.lines.regime[0] = -1  # 熊市
        else:
            self.lines.regime[0] = 0  # 震荡市


class LargeScaleRegimeIndicator(bt.Indicator):
    """
    一个将市场【大级别】宏观状态数值化的指标，用于对比。
    - 核心思想：使用长、中周期均线的关系来定义趋势，更稳定。
    - 输出值：
        - 1: 大级别牛市
        - 0: 大级别震荡/过渡
        - -1: 大级别熊市
    """
    lines = ('large_regime',)
    params = (
        ('long_ma_period', 200),
        ('medium_ma_period', 60),
        ('slope_period', 20),  # 使用更长的周期来判断长期均线的斜率
    )

    def __init__(self):
        self.ma_long = bt.indicators.SMA(self.data.close, period=self.p.long_ma_period)
        self.ma_medium = bt.indicators.SMA(self.data.close, period=self.p.medium_ma_period)

    def next(self):
        long_ma_slope = self.ma_long[0] - self.ma_long[-self.p.slope_period]

        # 中期均线在长期均线上方，且长期均线向上，视为大牛市
        if self.ma_medium[0] > self.ma_long[0] and long_ma_slope > 0:
            self.lines.large_regime[0] = 1
        # 中期均线在长期均线下方，且长期均线向下，视为大熊市
        elif self.ma_medium[0] < self.ma_long[0] and long_ma_slope < 0:
            self.lines.large_regime[0] = -1
        # 其他情况视为震荡或趋势转换期
        else:
            self.lines.large_regime[0] = 0


class RegimeClassifierStrategy(bt.Strategy):
    """
    一个专门用于识别和可视化市场宏观状态的策略。
    - 核心逻辑：基于长周期均线和ADX指标，判断市场处于牛市、熊市还是震荡市。
    - 目标：不执行任何交易，仅在日志和图表中清晰地展示每日的市场状态，
      用于验证和调试`MarketRegimeStrategy`中的核心环境判断逻辑。
    """
    params = (
        ('ma_macro_period', 60),
        ('adx_threshold', 19),
    )

    def __init__(self):
        # 实例化我们自定义的诊断指标
        self.regime_indicator = RegimeIndicator(
            ma_macro_period=self.p.ma_macro_period,
            adx_threshold=self.p.adx_threshold
        )
        # 新增：实例化大级别诊断指标
        self.large_regime_indicator = LargeScaleRegimeIndicator()

        # 用于在日志中跟踪状态变化
        self.previous_regime_val = None
        self.previous_large_regime_val = None  # 新增

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()} - {txt}')

    def next(self):
        # --- 原始指标状态 ---
        current_regime_val = self.regime_indicator.regime[0]
        if current_regime_val != self.previous_regime_val:
            regime_map = {1.0: '牛市', 0.0: '震荡', -1.0: '熊市'}
            self.log(f'[标准模式] 状态切换为: {regime_map.get(current_regime_val, "未知")}')
            self.previous_regime_val = current_regime_val

        # --- 新增：大级别指标状态 ---
        current_large_regime_val = self.large_regime_indicator.large_regime[0]
        if current_large_regime_val != self.previous_large_regime_val:
            regime_map = {1.0: '大牛市', 0.0: '大震荡', -1.0: '大熊市'}
            self.log(f'[大级别模式] 状态切换为: {regime_map.get(current_large_regime_val, "未知")}')
            self.previous_large_regime_val = current_large_regime_val 