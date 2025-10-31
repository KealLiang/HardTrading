import backtrader as bt


class PullbackReboundStrategy(bt.Strategy):
    """
    止跌反弹策略 - 专门用于捕捉主升浪后回调企稳的反弹机会
    
    策略逻辑：
    1. 识别经历量价齐升主升浪后的回调
    2. 在回调过程中寻找企稳信号（按顺序累积跟踪）：
       a. 量价背离：价格下跌但成交量放大（异常现象，可能是底部）
          - 正常：价升量涨、价跌量缩
          - 背离：价升量缩、价跌量增 ← 策略关注点
       b. 量窒息：满足以下任一条件
          - 波段内成交量最小（下跌波段 或 最近5~12根K线的盘整波段）
          - 成交量 < 120日均量
       c. 企稳K线：收红K线或止跌（多头开始反击）
    3. 买入信号（按顺序触发）：
       量价背离 → 量窒息 → 企稳K线
       约束：量价背离不能发生在高点后第二天（可通过enable_top_constraint关闭）
    4. 止盈止损：
       - 止盈：涨幅达到12%
       - 止损：跌幅超过5%
       - 时间止损：持有超过10天
    """

    params = (
        # -- 主升浪识别参数 --
        ('uptrend_period', 20),  # 主升浪判断周期
        ('uptrend_min_gain', 0.30),  # 主升浪最小涨幅30%
        ('volume_ma_period', 20),  # 成交量均线周期
        ('volume_surge_ratio', 1.5),  # 主升浪期间放量倍数

        # -- 回调识别参数 --
        ('pullback_max_ratio', 0.5),  # 最大回调幅度（超过则过度）
        ('pullback_max_days', 15),  # 最大回调天数（调整为15天）
        ('pullback_min_days', 3),  # 最小回调天数

        # -- 交易参数 --
        ('initial_stake_pct', 0.8),  # 初始仓位比例
        ('profit_target', 0.12),  # 止盈目标12%
        ('stop_loss', 0.05),  # 止损比例5%
        ('max_hold_days', 10),  # 最大持有天数

        # -- 信号约束参数 --
        ('enable_top_constraint', True),  # 是否启用顶部约束（背离不能在高点后第二天）

        # -- 调试参数 --
        ('debug', False),  # 是否开启详细日志
    )

    def __init__(self):
        # -- 技术指标 --
        self.sma = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.uptrend_period
        )
        self.volume_ma = bt.indicators.SimpleMovingAverage(
            self.data.volume, period=self.p.volume_ma_period
        )
        # 注意：不使用backtrader的120日均量指标，改为手动计算
        # 这样可以避免minperiod的限制，让策略在数据不足120天时仍能运行

        # -- 状态变量 --
        self.strategy_state = 'SCANNING'  # SCANNING, WAITING_PULLBACK, MONITORING_STABILIZATION, POSITION_HELD
        self.uptrend_high_price = 0.0  # 主升浪高点价格
        self.uptrend_high_date = None  # 主升浪高点日期
        self.pullback_start_date = None  # 回调开始日期
        self.pullback_low_price = float('inf')  # 回调期间最低价

        # -- 企稳信号跟踪（在回调期间累积）--
        self.signal_divergence_date = None  # 量价背离出现日期
        self.signal_volume_dry_date = None  # 量窒息出现日期
        self.signal_stabilization_date = None  # 企稳K线出现日期

        # -- 交易状态 --
        self.order = None
        self.buy_price = 0.0
        self.buy_date = None
        self.hold_days = 0

        # -- 企稳信号跟踪 --
        self.recent_lows = []  # 最近几日的最低价
        self.recent_volumes = []  # 最近几日的成交量

        # -- 参数检查 --
        self.param_logged = False  # 是否已记录参数

    def log(self, txt, dt=None):
        """日志输出"""
        dt = dt or self.datas[0].datetime.date(0)
        # 获取股票代码
        stock_code = getattr(self.data, '_name', 'UNKNOWN')
        print(f'[{stock_code}] {dt.isoformat()} - {txt}')

    def notify_order(self, order):
        """订单状态通知"""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.buy_price = order.executed.price
                self.buy_date = self.datas[0].datetime.date(0)
                self.hold_days = 0
                self.strategy_state = 'POSITION_HELD'
                position_pct = order.executed.value / self.broker.getvalue() * 100
                self.log(
                    f'买入成交 (止跌反弹): {order.executed.size}股 @ {order.executed.price:.2f}, '
                    f'仓位: {position_pct:.2f}%'
                )
            elif order.issell():
                # 详细卖出日志
                sell_price = order.executed.price
                sell_size = abs(order.executed.size)
                if hasattr(self, 'buy_price') and self.buy_price > 0:
                    profit_loss = (sell_price - self.buy_price) / self.buy_price
                    if profit_loss > 0:
                        self.log(f'止盈卖出: 盈利 {profit_loss:.2%}')
                    else:
                        self.log(f'止损卖出: 亏损 {profit_loss:.2%}')

                self.log(f'卖出成交: {sell_size}股 @ {sell_price:.2f}')
                self._reset_strategy_state()

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('订单未能成交')

        self.order = None

    def notify_trade(self, trade):
        """交易完成通知"""
        if trade.isclosed:
            self.log(f'交易关闭, 净盈亏: {trade.pnlcomm:.2f}, 当前总资产: {self.broker.getvalue():.2f}')

    def next(self):
        """策略主逻辑"""
        if self.order:
            return

        # 测试日志输出
        if len(self) == 1:  # 第一天
            self.log("策略开始运行")

        # 更新持有天数
        if self.position:
            self.hold_days += 1

        # 根据当前状态执行不同逻辑
        if self.strategy_state == 'SCANNING':
            self._scan_for_uptrend()
        elif self.strategy_state == 'WAITING_PULLBACK':
            self._wait_for_pullback()
        elif self.strategy_state == 'MONITORING_STABILIZATION':
            self._monitor_stabilization()
        elif self.strategy_state == 'POSITION_HELD':
            self._handle_position()

    def _scan_for_uptrend(self):
        """
        扫描主升浪
        
        这是策略的第一步，也是必要前提条件。
        只有识别到符合条件的主升浪，才会进入后续的回调监控阶段。
        """
        # 需要足够的历史数据
        if len(self) < self.p.uptrend_period:
            return

        # 计算最近period天的复利涨幅
        period_start_price = self.data.close[-self.p.uptrend_period]
        current_price = self.data.close[0]

        # 使用复利计算：考虑期间的波动
        # 计算期间的最低点，确保是从真正的低点开始计算
        period_prices = [self.data.close[-i] for i in range(self.p.uptrend_period, 0, -1)]
        period_low = min(period_prices)

        # 如果当前价格比期间最低点的涨幅更大，使用最低点作为起点
        gain_from_start = (current_price - period_start_price) / period_start_price
        gain_from_low = (current_price - period_low) / period_low
        period_gain = max(gain_from_start, gain_from_low)

        # 检查趋势质量：确保是真正的主升浪而不是反弹
        # 1. 价格应该创近期新高（更严格的条件）
        recent_high = max([self.data.high[-i] for i in range(min(40, len(self)), 0, -1)])
        current_high = self.data.high[0]
        # 要求当日最高价创新高，且收盘价不能离最高价太远
        is_new_high = (current_high > recent_high and
                       current_price >= current_high * 0.95)  # 收盘价不能离当日最高价太远

        # 2. 均线多头排列：短期均线在长期均线之上
        sma_short = sum([self.data.close[-i] for i in range(10, 0, -1)]) / 10
        sma_long = sum([self.data.close[-i] for i in range(20, 0, -1)]) / 20
        is_bullish_alignment = sma_short > sma_long

        # 3. 趋势持续性检查：确保不是短期反弹
        # 检查最近5天是否有连续上涨趋势
        recent_closes = [self.data.close[-i] for i in range(5, 0, -1)]
        uptrend_days = sum(1 for i in range(1, len(recent_closes))
                           if recent_closes[i] > recent_closes[i - 1])
        is_sustained_uptrend = uptrend_days >= 3  # 至少3天上涨

        # 4. 价格位置检查：确保不是在下跌趋势中的反弹
        # 当前价格应该明显高于更长期的均线
        sma_long_term = sum([self.data.close[-i] for i in range(40, 0, -1)]) / 40
        is_above_long_term_trend = current_price > sma_long_term * 1.1  # 高于长期均线10%

        # 调试信息
        if self.p.debug and period_gain >= self.p.uptrend_min_gain:
            debug_msg = (
                f'[debug]主升浪检查 - 涨幅: {period_gain:.2%}, '
                f'创新高: {is_new_high}, 多头排列: {is_bullish_alignment}, '
                f'持续上涨: {is_sustained_uptrend}, 长期趋势: {is_above_long_term_trend}, '
                f'放量: {self.data.volume[0] > self.volume_ma[0] * self.p.volume_surge_ratio}'
            )
            self.log(debug_msg)

        # 检查是否满足主升浪条件（更严格的条件）
        is_strong_uptrend = (
                period_gain >= self.p.uptrend_min_gain and  # 涨幅足够
                current_price > self.sma[0] and  # 价格在均线之上
                self.data.volume[0] > self.volume_ma[0] * self.p.volume_surge_ratio and  # 放量
                is_new_high and  # 创近期新高
                is_bullish_alignment and  # 均线多头排列
                is_sustained_uptrend and  # 持续上涨趋势
                is_above_long_term_trend  # 明显高于长期趋势
        )

        if is_strong_uptrend:
            self.uptrend_high_price = current_price
            self.uptrend_high_date = self.datas[0].datetime.date(0)
            self.strategy_state = 'WAITING_PULLBACK'
            self.log(f'*** 检测到主升浪，高点: {self.uptrend_high_price:.2f}, 涨幅: {period_gain:.2%} ***')

    def _wait_for_pullback(self):
        """
        等待回调
        
        前提条件：已经识别到主升浪（uptrend_high_price > 0）
        此阶段持续跟踪主升浪高点，直到出现回调信号
        """
        current_price = self.data.close[0]

        # 更新主升浪高点（主升浪可能继续创新高）
        if current_price > self.uptrend_high_price:
            self.uptrend_high_price = current_price
            self.uptrend_high_date = self.datas[0].datetime.date(0)
            return

        # 检查是否开始回调
        pullback_ratio = (self.uptrend_high_price - current_price) / self.uptrend_high_price

        if pullback_ratio >= 0.03:  # 回调超过3%认为开始回调
            self.pullback_start_date = self.datas[0].datetime.date(0)
            self.pullback_low_price = current_price
            self.strategy_state = 'MONITORING_STABILIZATION'

            # 重置企稳信号状态（开始新的回调监控）
            self.signal_divergence_date = None
            self.signal_volume_dry_date = None
            self.signal_stabilization_date = None

            self.log(
                f'*** 开始回调，从 {self.uptrend_high_price:.2f} 回调至 {current_price:.2f} ({pullback_ratio:.2%}) ***')

    def _monitor_stabilization(self):
        """
        监控企稳信号（累积跟踪）
        
        前提条件：
        1. 已经识别到主升浪（uptrend_high_price > 0）
        2. 已经开始回调（pullback_start_date 已设置）
        
        策略逻辑：
        - 在回调期间，持续检查三个信号：量价背离、量窒息、企稳K线
        - 这三个信号不要求同一天出现，只要在回调期间都出现过即可
        - 当三个信号都出现过后，触发买入
        """
        # 前提条件验证：必须有有效的主升浪数据
        if self.uptrend_high_price <= 0 or self.pullback_start_date is None:
            self.log('⚠️ 警告：缺少主升浪数据，重新扫描')
            self._reset_strategy_state()
            return

        current_price = self.data.close[0]
        current_volume = self.data.volume[0]

        # 更新回调最低价
        if current_price < self.pullback_low_price:
            self.pullback_low_price = current_price

        # 检查回调是否过度或时间过长
        pullback_ratio = (self.uptrend_high_price - current_price) / self.uptrend_high_price
        days_since_pullback = (self.datas[0].datetime.date(0) - self.pullback_start_date).days

        if pullback_ratio > self.p.pullback_max_ratio or days_since_pullback > self.p.pullback_max_days:
            self.log(f'回调过度或时间过长，重新扫描。回调幅度: {pullback_ratio:.2%}, 天数: {days_since_pullback}')
            self._reset_strategy_state()
            return

        # 检查企稳信号（至少回调3天后才开始检查）
        if days_since_pullback >= self.p.pullback_min_days:
            # 更新信号状态（累积跟踪）
            self._update_signal_status()

            # 检查是否满足买入条件（路径1或路径2）
            if self._check_buy_signal():
                # 当天收盘买入（模拟尾盘买入）
                self._execute_buy_signal_eod()

    def _update_signal_status(self):
        """
        更新信号状态（每日检查并累积）
        
        在回调期间，每天检查三个信号是否出现，一旦出现就标记为True
        """
        # 1. 检查量价背离：价跌量增
        if not self.signal_divergence_date:
            if self._check_volume_price_divergence():
                self.signal_divergence_date = self.datas[0].datetime.date(0)
                self.log(f'✓ 量价背离信号出现 - 价跌量增')

        # 2. 检查量窒息：波段内成交量最小 或 低于120日均量
        if not self.signal_volume_dry_date:
            dry_result = self._check_volume_dry()
            if dry_result['is_dry']:
                self.signal_volume_dry_date = self.datas[0].datetime.date(0)
                self.log(f'✓ 量窒息信号出现 - {dry_result["reason"]}')

        # 3. 检查企稳K线
        if not self.signal_stabilization_date:
            # 方式1：收红K线（收盘>开盘）
            is_red_candle = self.data.close[0] > self.data.open[0]
            # 方式2：收盘价高于前日收盘价（止跌）
            prev_close = self.data.close[-1] if len(self) > 0 else 0
            is_price_up = self.data.close[0] > prev_close if prev_close > 0 else False

            if is_red_candle or is_price_up:
                self.signal_stabilization_date = self.datas[0].datetime.date(0)
                stab_type = []
                if is_red_candle:
                    stab_type.append('红K')
                if is_price_up:
                    stab_type.append('止跌')
                self.log(f'✓ 企稳K线信号出现 - {"/".join(stab_type)}')

        # 显示当前信号进度（仅在未满足买入条件时显示）
        if not self._check_buy_signal():
            # 显示各信号状态
            signals = []
            if self.signal_divergence_date:
                signals.append(f'量价背离✓ ({self.signal_divergence_date})')
            else:
                signals.append('量价背离✗')

            if self.signal_volume_dry_date:
                signals.append(f'量窒息✓ ({self.signal_volume_dry_date})')
            else:
                signals.append('量窒息✗')

            if self.signal_stabilization_date:
                signals.append(f'企稳K线✓ ({self.signal_stabilization_date})')
            else:
                signals.append('企稳K线✗')

            # 检查顺序和约束
            status = ""
            if self.signal_divergence_date and self.signal_volume_dry_date and self.signal_stabilization_date:
                # 三个都有，检查顺序
                if self.signal_divergence_date >= self.signal_volume_dry_date:
                    status = "✗背离和窒息顺序错误"
                elif self.signal_volume_dry_date >= self.signal_stabilization_date:
                    status = "✗窒息和企稳顺序错误"
                else:
                    # 顺序正确，检查顶部约束（如果启用）
                    if self.p.enable_top_constraint and self.uptrend_high_date:
                        from datetime import timedelta
                        day_after_high = self.uptrend_high_date + timedelta(days=1)
                        if self.signal_divergence_date == day_after_high:
                            status = "✗背离发生在顶部后第二天"
                        else:
                            status = "✓所有条件满足"
                    else:
                        status = "✓所有条件满足"
            elif self.signal_divergence_date and self.signal_volume_dry_date:
                # 检查前两个的顺序
                if self.signal_divergence_date >= self.signal_volume_dry_date:
                    status = "✗背离和窒息顺序错误"
                else:
                    status = "等待企稳K线"
            elif self.signal_divergence_date:
                status = "等待量窒息"
            else:
                status = "等待量价背离"

            self.log(f'信号进度: {" | ".join(signals)} || 状态: {status}')

    def _check_buy_signal(self):
        """
        检查买入信号（按顺序触发）
        
        量价背离 → 量窒息 → 企稳K线
        约束：背离不能发生在顶部（高点后第二天），可通过enable_top_constraint参数控制
        """
        # 检查三个信号是否都已出现
        if not self.signal_divergence_date or not self.signal_volume_dry_date or not self.signal_stabilization_date:
            return False

        # 检查顺序：背离 < 窒息 < 企稳
        if self.signal_divergence_date >= self.signal_volume_dry_date:
            return False
        if self.signal_volume_dry_date >= self.signal_stabilization_date:
            return False

        # 检查顶部约束：背离日期不能是高点后第二天（如果启用）
        if self.p.enable_top_constraint and self.uptrend_high_date:
            from datetime import timedelta
            day_after_high = self.uptrend_high_date + timedelta(days=1)
            if self.signal_divergence_date == day_after_high:
                return False

        # 所有条件满足，输出确认信息
        pullback_ratio = (self.uptrend_high_price - self.data.close[0]) / self.uptrend_high_price
        self.log(
            f'*** 企稳信号触发: 背离({self.signal_divergence_date}) → 窒息({self.signal_volume_dry_date}) → 企稳({self.signal_stabilization_date}) ***'
            f'; 主升浪高点: {self.uptrend_high_price:.2f}'
            f'; 当前价格: {self.data.close[0]:.2f} (回调 {pullback_ratio:.2%})'
        )
        return True

    def _check_volume_dry(self):
        """
        检查量窒息
        
        量窒息定义（满足任一条件）：
        a. 最近一个波段内成交量最小
           - 下跌波段：从回调开始到现在
           - 盘整波段：最近5~12根K线
        b. 成交量 < 120日均量（需要至少120天数据）
        
        返回：{'is_dry': bool, 'reason': str}
        """
        current_volume = self.data.volume[0]

        # 条件b：成交量 < 120日均量
        # 手动计算120日均量，避免backtrader指标的minperiod限制
        if len(self) >= 120:
            try:
                # 手动计算最近120天的平均成交量
                volumes_120 = [self.data.volume[-i] for i in range(119, -1, -1)]
                volume_120ma = sum(volumes_120) / 120

                if current_volume < volume_120ma:
                    return {
                        'is_dry': True,
                        'reason': f'成交量({current_volume:.0f}) < 120日均量({volume_120ma:.0f})'
                    }
            except (IndexError, TypeError):
                # 如果数据访问出错，跳过此条件，继续检查其他条件
                pass

        # 条件a：波段内成交量最小
        # 首先判断当前是下跌波段还是盘整波段
        wave_type, wave_volumes = self._identify_wave_type()

        if wave_type and wave_volumes:
            min_volume = min(wave_volumes)
            if current_volume <= min_volume:
                return {
                    'is_dry': True,
                    'reason': f'{wave_type}波段内成交量最小({current_volume:.0f})'
                }

        return {'is_dry': False, 'reason': ''}

    def _identify_wave_type(self):
        """
        识别当前波段类型
        
        返回：(wave_type, volumes)
        - wave_type: '下跌' 或 '盘整'
        - volumes: 波段内的成交量列表
        """
        current_price = self.data.close[0]

        # 方法1：如果在回调监控阶段，且从回调开始有足够数据
        if self.pullback_start_date and self.strategy_state == 'MONITORING_STABILIZATION':
            days_since_pullback = (self.datas[0].datetime.date(0) - self.pullback_start_date).days

            # 获取从回调开始到现在的数据
            if days_since_pullback >= 3 and days_since_pullback <= len(self):
                pullback_volumes = [self.data.volume[-i] for i in range(days_since_pullback, 0, -1)]
                pullback_volumes.append(self.data.volume[0])
                pullback_prices = [self.data.close[-i] for i in range(days_since_pullback, 0, -1)]
                pullback_prices.append(current_price)

                # 判断是下跌还是盘整
                price_start = pullback_prices[0]
                price_end = current_price
                price_high = max(pullback_prices)
                price_low = min(pullback_prices)
                price_range = (price_high - price_low) / price_low if price_low > 0 else 0

                # 如果价格波动小于5%，认为是盘整
                if price_range < 0.05:
                    # 盘整波段：使用最近5~12根K线
                    consolidation_period = min(12, len(self))
                    consolidation_volumes = [self.data.volume[-i] for i in range(consolidation_period, 0, -1)]
                    consolidation_volumes.append(self.data.volume[0])
                    return ('盘整', consolidation_volumes)
                else:
                    # 下跌波段：使用整个回调期间
                    return ('下跌', pullback_volumes)

        # 方法2：默认检查最近5~12根K线（盘整波段）
        consolidation_period = min(12, len(self))
        if consolidation_period >= 5:
            consolidation_volumes = [self.data.volume[-i] for i in range(consolidation_period, 0, -1)]
            consolidation_volumes.append(self.data.volume[0])
            return ('盘整', consolidation_volumes)

        return (None, None)

    def _check_volume_price_divergence(self, check_top_constraint=False):
        """
        检查量价背离：价格下跌 + 成交量放大（异常现象）
        
        正常的量价关系：
        - 价升量涨（正常）
        - 价跌量缩（正常）
        
        量价背离（异常，值得关注）：
        - 价升量缩
        - 价跌量增 ← 这个策略关注的重点
        
        当价格下跌但成交量反而放大时，说明：
        - 可能是恐慌盘集中释放，底部临近
        - 或主力吸筹，承接抛压
        
        参数：
        - check_top_constraint: 是否检查顶部约束（不能是最高点后第二天的背离）
        """
        if len(self) < 2:  # 需要至少2天数据来比较
            return False

        current_price = self.data.close[0]
        prev_price = self.data.close[-1]
        current_volume = self.data.volume[0]
        prev_volume = self.data.volume[-1]

        # 1. 确认处于回调状态
        if self.uptrend_high_price <= 0:
            return False

        # 2. 顶部约束检查（针对路径1）
        if check_top_constraint and self.uptrend_high_date:
            yesterday = self.datas[0].datetime.date(-1)
            # 如果昨天是最高点，今天不能算背离
            if yesterday == self.uptrend_high_date:
                return False

        # 3. 价格下跌：当前收盘价低于前一日收盘价
        is_price_down = current_price < prev_price

        # 4. 成交量放大：当前成交量明显高于前一日或高于均量
        # 方式1：相对于前日放量
        is_volume_surge_vs_prev = current_volume > prev_volume * 1.2
        # 方式2：相对于均量放量（但不能太夸张，说明是在缩量过程中的相对放量）
        volume_vs_ma = current_volume / self.volume_ma[0] if self.volume_ma[0] > 0 else 0
        is_volume_surge_vs_ma = volume_vs_ma > 0.8  # 相对于均量不能太低

        # 量价背离：价跌 + 放量
        is_divergence = is_price_down and (is_volume_surge_vs_prev or is_volume_surge_vs_ma)

        # 调试信息
        if self.p.debug and is_divergence:
            self.log(
                f'[量价背离] 价格: {prev_price:.2f}→{current_price:.2f} ({(current_price / prev_price - 1) * 100:.2f}%), '
                f'成交量: {prev_volume:.0f}→{current_volume:.0f} ({(current_volume / prev_volume - 1) * 100:.2f}%), '
                f'量/均量: {volume_vs_ma:.2f}'
            )

        return is_divergence

    def _execute_buy_signal_eod(self):
        """
        执行尾盘买入信号（当天收盘价买入）
        
        前提条件：必须先经历主升浪，然后回调企稳
        """
        # 再次验证前提条件
        if self.uptrend_high_price <= 0:
            self.log('⚠️ 警告：无主升浪数据，取消买入')
            return

        current_price = self.data.close[0]
        pullback_ratio = (self.uptrend_high_price - current_price) / self.uptrend_high_price

        stake = self.broker.getvalue() * self.p.initial_stake_pct
        size = int(stake / current_price)

        if size > 0:
            # 简单买入（下一个bar开盘）
            self.order = self.buy(size=size)
            self.log(
                f'*** 止跌反弹买入信号触发 @ {current_price:.2f} ***'
                f'; 主升浪高点: {self.uptrend_high_price:.2f} ({self.uptrend_high_date})'
                f'; 回调幅度: {pullback_ratio:.2%}'
                f'; 买入仓位: {self.p.initial_stake_pct:.0%}'
            )

    def _handle_position(self):
        """
        处理持仓的止盈止损
        
        止盈止损逻辑：
        1. 止盈：盈利达到12%（profit_target），落袋为安
        2. 止损：亏损超过5%（stop_loss），及时止损
        3. 时间止损：持有超过10天（max_hold_days），避免资金占用过久
        
        优先级：止盈 > 止损 > 时间止损
        """
        current_price = self.data.close[0]

        # 计算当前盈亏比例
        pnl_ratio = (current_price - self.buy_price) / self.buy_price

        # 1. 止盈：盈利达到目标
        if pnl_ratio >= self.p.profit_target:
            self.log(f'止盈卖出: 盈利 {pnl_ratio:.2%}')
            self.order = self.close()
            return

        # 2. 止损：亏损超过阈值
        if pnl_ratio <= -self.p.stop_loss:
            self.log(f'止损卖出: 亏损 {pnl_ratio:.2%}')
            self.order = self.close()
            return

        # 3. 时间止损：持有天数超限
        if self.hold_days >= self.p.max_hold_days:
            self.log(f'时间止损: 持有 {self.hold_days} 天')
            self.order = self.close()
            return

    def _reset_strategy_state(self):
        """重置策略状态"""
        self.strategy_state = 'SCANNING'
        self.uptrend_high_price = 0.0
        self.uptrend_high_date = None
        self.pullback_start_date = None
        self.pullback_low_price = float('inf')
        self.buy_price = 0.0
        self.buy_date = None
        self.hold_days = 0

        # 重置企稳信号状态
        self.signal_divergence_date = None
        self.signal_volume_dry_date = None
        self.signal_stabilization_date = None
