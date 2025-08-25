params = (
    # -- 调试开关 --
    ('debug', False),  # 是否开启信号评级的详细日志
    # -- 核心指标 --
    ('bband_period', 20),  # 布林带周期
    ('bband_devfactor', 2.0),  # 布林带标准差
    ('volume_ma_period', 20),  # 成交量移动平均周期
    # -- 信号评级与观察模式参数 --
    ('ma_macro_period', 60),  # 定义宏观环境的长周期均线
    # -- 环境分 V2.2 新增高位盘整识别 --
    ('consolidation_lookback', 5),  # 短期均线盘整的回看期
    ('consolidation_ma_proximity_pct', 0.02),  # 短期均线接近度的阈值 (2%)
    ('consolidation_ma_max_slope', 1.05),  # 盘整期间MA最大斜率 (5日涨5%)
    ('squeeze_period', 60),  # 波动性压缩回顾期
    ('observation_period', 15),  # 触发观察模式后的持续天数
    ('confirmation_lookback', 5),  # "蓄势待发"信号的回看周期
    ('probation_period', 5),  # "蓄势待发"买入后的考察期天数
    ('pocket_pivot_lookback', 10),  # 口袋支点信号的回看期
    ('breakout_proximity_pct', 0.03),  # "准突破"价格接近上轨的容忍度(3%)
    ('pullback_from_peak_pct', 0.07),  # 从观察期高点可接受的最大回撤(7%)
    ('context_period', 7),  # PSQ 3.1: 情景定位的回看周期
    # -- PSQ 权重参数 --
    ('psq_pattern_weight', 1.0),  # PSQ 形态分权重
    ('psq_momentum_weight', 1.0),  # PSQ 动能分权重
    ('overheat_threshold', 1.99),  # 过热分数阈值，2.0相当于接20厘米涨幅的次日盘
    # -- PSQ 分析参数 --
    ('psq_summary_period', 3),  # 定义持仓期初期分析的天数
    # -- VCP 4.1 "中庸之道" 评分参数 --
    ('vcp_lookback', 60),  # VCP总回看期，用于确定波动率分位
    ('vcp_macro_ma_period', 90),  # VCP宏观环境判断的均线周期
    ('vcp_absorption_lookback', 20),  # VCP供给吸收分析的回看期
    ('vcp_absorption_zone_pct', 0.07),  # 定义供给区的价格范围(7%)
    # -- 新增: "平衡"评分参数 --
    ('vcp_macro_roc_period', 20),  # 计算宏观MA斜率的回看期
    ('vcp_optimal_ma_roc', 1.03),  # 宏观MA最优斜率 (20日涨3%)
    ('vcp_max_ma_roc', 1.15),  # 宏观MA斜率上限 (过热)
    ('vcp_optimal_price_pos', 1.05),  # 价格与MA的最优位置 (高于MA 5%)
    ('vcp_max_price_pos', 1.30),  # 价格与MA的位置上限 (过高)
    ('vcp_squeeze_exponent', 1.5),  # 波动压缩分的非线性指数

    # -- VCP 4.1 权重 --
    ('vcp_weight_macro', 0.35),  # 宏观环境分权重
    ('vcp_weight_squeeze', 0.40),  # 波动状态分权重
    ('vcp_weight_absorption', 0.25),  # 供给吸收分权重
    # -- 风险管理 --
    ('initial_stake_pct', 0.90),  # 初始仓位（占总资金）
    ('atr_period', 14),  # ATR周期
    ('atr_multiplier', 2.0),  # ATR止损乘数
    ('atr_ceiling_multiplier', 4.0),  # 新增：基于ATR的价格窗口乘数
)